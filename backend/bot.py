#
# Voice pipeline — Prosper AI Software Engineer Challenge
#
# The runnable voice agent: WebRTC transport + ElevenLabs STT/TTS + OpenAI LLM,
# driven by a Pipecat Flows node graph. This file is generic — it loads an agent
# definition (JSON) via AgentBuilder and runs it. Swapping the agent is a data
# change (edit/replace the JSON), not a code change.
#
#   example_flow.json  ->  AgentBuilder  ->  Pipecat Flows graph  ->  FlowManager
#
# Run:  python bot.py   then open http://localhost:7860/client
#

import os
from uuid import uuid4
from pathlib import Path
from pipecat.transcriptions.language import Language
from pipecat.turns.user_turn_strategies import UserTurnStrategies
from voice_support import (RealWordsStartStrategy, InterruptedSilenceRecovery, VOICE_MIN_WORDS,
    tool_trace_wrapper)

from loguru import logger

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.processors.aggregators.llm_response_universal import (
    LLMUserAggregatorParams,
)
from pipecat.runner.types import RunnerArguments
from pipecat.runner.utils import create_transport
from pipecat.services.elevenlabs.stt import ElevenLabsRealtimeSTTService
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
from pipecat.transports.base_transport import BaseTransport, TransportParams
from pipecat.workers.runner import WorkerRunner

from agent_builder import AgentBuilder
from agent_runtime import build_agent_runtime
from scheduling_runtime import load_selected_scheduling_agent


transport_params = {
    "webrtc": lambda: TransportParams(audio_in_enabled=True, audio_out_enabled=True),
}


async def run_bot(
    transport: BaseTransport, runner_args: RunnerArguments, builder: AgentBuilder
) -> None:
    config = builder.config
    call_id = runner_args.session_id or str(uuid4())
    builder.set_function_handler_wrapper(tool_trace_wrapper(
        call_id, builder, Path(__file__).parent / "logs" / "voice-tools.jsonl"))
    logger.info(f"Starting '{config.name}' with {len(config.nodes)} nodes")

    stt = ElevenLabsRealtimeSTTService(api_key=os.environ["ELEVENLABS_API_KEY"],
        settings=ElevenLabsRealtimeSTTService.Settings(language=Language.EN))
    tts = ElevenLabsTTSService(
        api_key=os.environ["ELEVENLABS_API_KEY"],
        settings=ElevenLabsTTSService.Settings(voice=config.voice_id),
    )
    runtime = build_agent_runtime(
        builder=builder,
        user_params=LLMUserAggregatorParams(vad_analyzer=SileroVADAnalyzer(),
            user_turn_strategies=UserTurnStrategies(start=[RealWordsStartStrategy(min_words=VOICE_MIN_WORDS)])),
        input_processors=[transport.input(), stt],
        output_processors=[tts, transport.output()],
        transport=transport,
        call_id=call_id,
        idle_timeout_secs=runner_args.pipeline_idle_timeout_secs,
    )
    logger.info(f"Per-turn metrics enabled | call_id={runtime.call_id}")

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        logger.info("Client connected — starting flow at initial node")
        await runtime.initialize()

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info("Client disconnected")
        await runtime.worker.cancel()

    runner = WorkerRunner(handle_sigint=runner_args.handle_sigint)
    await runner.add_workers(runtime.worker)
    await runner.run()


async def bot(runner_args: RunnerArguments):
    """Entry point invoked by the Pipecat dev runner (and Pipecat Cloud)."""
    transport = await create_transport(runner_args, transport_params)
    builder, _engine = load_selected_scheduling_agent()
    await run_bot(transport, runner_args, builder)


if __name__ == "__main__":
    from pipecat.runner.run import main

    main()
