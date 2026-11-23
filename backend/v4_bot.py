"""The v4 voice entry point: one call from a v4 agent file. Does not construct the Flows runtime."""
import asyncio
import os

from dotenv import load_dotenv
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.pipeline.pipeline import Pipeline
from pipecat.frames.frames import EndFrame
from pipecat.pipeline.worker import PipelineParams,PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMUserAggregatorParams
from pipecat.runner.utils import create_transport
from pipecat.services.elevenlabs.stt import ElevenLabsRealtimeSTTService
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
from pipecat.transcriptions.language import Language
from pipecat.transports.base_transport import TransportParams
from pipecat.turns.user_stop import SpeechTimeoutUserTurnStopStrategy, TurnAnalyzerUserTurnStopStrategy
from pipecat.turns.user_turn_strategies import UserTurnStrategies
from pipecat.workers.runner import WorkerRunner

from voice_support import RealWordsStartStrategy
from v4.agent_config import DEFAULT_AGENT_PATH, load_agent
from v4.interpreter import OpenAIInterpreter
from v4.pipeline import FinalInput,ReplySource,PlaybackDelivery,SpeakAttempt,EndpointAggregator,AudioAttemptTagger
from v4.session import Session,load_engine,BACKEND

DEFAULT_MAX_INTERPRETATIONS=40
SMART_TURN_ENV='V4_SMART_TURN'


def turn_stop(env=None, *, analyzer=None):
    """(stop strategies, record) for one call. Smart Turn v3 (Pipecat's local
    ONNX end-of-turn model) ends a turn when the speaker has finished, not after a
    fixed silence. On by default; V4_SMART_TURN=0 turns it off. If the model does
    not load, the call falls back to the silence timeout and says why."""
    env=os.environ if env is None else env
    value=(env.get(SMART_TURN_ENV) or '1').strip().casefold()
    fallback=lambda reason,**extra:([SpeechTimeoutUserTurnStopStrategy()],
        dict(mode='speech_timeout',reason=reason,user_speech_timeout_secs=0.6,env=value,**extra))
    if value in {'0','false','off','no'}:
        return fallback('disabled')
    try:
        if analyzer is None:
            from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
            analyzer=LocalSmartTurnAnalyzerV3()
        else:
            analyzer=analyzer()
    except Exception as error:
        return fallback('load_failed',error_type=type(error).__name__)
    return ([TurnAnalyzerUserTurnStopStrategy(turn_analyzer=analyzer)],
        dict(mode='smart_turn_v3',analyzer=type(analyzer).__name__,env=value))


class AttemptTTS(ElevenLabsTTSService):
    """Bind each actual TTS context to the composer's immutable message attempt."""
    current_attempt=None
    context_created=None

    def create_context_id(self):
        context_id=super().create_context_id()
        if self.current_attempt and self.context_created:
            self.context_created(context_id,self.current_attempt)
        return context_id

    async def process_frame(self,frame,direction):
        if isinstance(frame,SpeakAttempt):self.current_attempt=frame.attempt_id
        try:await super().process_frame(frame,direction)
        finally:
            if isinstance(frame,SpeakAttempt):self.current_attempt=None


def build_pipeline(session, *, input_processors,tts,output, user_params):
    # The user aggregator supplies VAD/endpoints only. Its context inference is
    # sunk by ReplySource. No LLM service or FlowManager is instantiated, so both
    # immediate Flows inference and post-tool inference are disabled by topology.
    aggregator=EndpointAggregator(LLMContext(),session,params=user_params)
    source=ReplySource(session);delivery=PlaybackDelivery(session)
    # on_tts_request handlers run in background tasks in Pipecat 1.4. Bind
    # synchronously at context creation instead of reading a later current ID.
    tts.context_created=delivery.bind_context
    return Pipeline([*input_processors,FinalInput(session),aggregator,source,tts,AudioAttemptTagger(delivery),output,delivery])


def hang_up(worker):
    """The session's end hook: an EndFrame queued behind the final reply, so the
    goodbye is spoken and then the pipeline (and the call) ends."""
    async def end():
        await worker.queue_frames([EndFrame()])
    return end


def prepare_call(agent_path=DEFAULT_AGENT_PATH, *, client=None):
    """The session and the TTS voice for one call, both from the saved agent file."""
    agent=load_agent(agent_path)
    engine,metadata=load_engine()
    # Manual calls: at most this many interpreter requests per call (default 40).
    limit=int(os.getenv('V4_MAX_INTERPRETATIONS') or DEFAULT_MAX_INTERPRETATIONS)
    interpreter=OpenAIInterpreter(client,request_limit=limit,guidance=agent.guidance,model=agent.model)
    return Session(engine,interpreter,metadata=metadata,agent=agent),agent.voice_id


async def bot(runner_args, agent_path=DEFAULT_AGENT_PATH):
    load_dotenv(BACKEND/'.env',override=True)
    transport=await create_transport(runner_args,{'webrtc':lambda:TransportParams(audio_in_enabled=True,audio_out_enabled=True)})
    session,voice=prepare_call(agent_path)
    stt=ElevenLabsRealtimeSTTService(api_key=os.environ['ELEVENLABS_API_KEY'],
        settings=ElevenLabsRealtimeSTTService.Settings(language=Language.EN))
    tts=AttemptTTS(api_key=os.environ['ELEVENLABS_API_KEY'],
        settings=ElevenLabsTTSService.Settings(voice=voice))
    stop,turn_record=turn_stop()
    session.record('turn_detection',**turn_record)
    pipeline=build_pipeline(session,input_processors=[transport.input(),stt],tts=tts,output=transport.output(),
        user_params=LLMUserAggregatorParams(vad_analyzer=SileroVADAnalyzer(),
            user_turn_strategies=UserTurnStrategies(start=[RealWordsStartStrategy(min_words=1)],stop=stop)))
    worker=PipelineWorker(pipeline,params=PipelineParams(enable_metrics=True,enable_usage_metrics=True),
        conversation_id=session.run_id,idle_timeout_secs=runner_args.pipeline_idle_timeout_secs)
    session.on_end=hang_up(worker)

    @transport.event_handler('on_client_connected')
    async def connected(transport,client):
        # Do not block transport startup waiting for downstream StartFrame.
        asyncio.create_task(session.start())

    @transport.event_handler('on_client_disconnected')
    async def disconnected(transport,client):
        await session.close();await worker.cancel()

    runner=WorkerRunner(handle_sigint=runner_args.handle_sigint)
    try:
        await runner.add_workers(worker);await runner.run()
    finally:await session.close()


if __name__=='__main__':
    from pipecat.runner.run import main
    main()
