"""Opt-in v4 text entry point; the demo text runner remains unchanged."""
import asyncio
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from v4.agent_config import DEFAULT_AGENT_PATH, load_agent
from v4.interpreter import OpenAIInterpreter
from v4.session import Session,load_engine


class V4TextSession:
    """Thin programmatic interface. Text display is explicitly not audio proof."""
    def __init__(self, *, engine=None, interpreter=None, run_id=None, log_dir=None, agent_path=DEFAULT_AGENT_PATH):
        """agent_path: the v4 agent file (wording, voice, clinic guidance), as in voice calls."""
        metadata={'availability_mode':'supplied_fixture'}
        if engine is None:engine,metadata=load_engine()
        agent=load_agent(agent_path)
        interpreter=interpreter or OpenAIInterpreter(guidance=agent.guidance,model=agent.model)
        self.session=Session(engine,interpreter,run_id=run_id,log_dir=log_dir,metadata=metadata,agent=agent)
        self._lock=asyncio.Lock()

    async def start(self):
        reply=await self.session.start()
        self.session.record('text_display',attempt_id=reply.attempt_id)
        self.session.delivery(reply.attempt_id,'completed')
        return reply

    async def send(self, text, *, event_id=None):
        async with self._lock:
            self.session.endpoint(True)
            reply=await asyncio.shield(self.session.receive(event_id or str(uuid4()),text))
            if reply:
                self.session.record('text_display',attempt_id=reply.attempt_id)
                self.session.delivery(reply.attempt_id,'completed')
            return reply

    async def close(self):
        await self.session.close()


async def main():
    load_dotenv(Path(__file__).parent/'.env',override=True)
    session=V4TextSession()
    try:
        print('Assistant:',(await session.start()).text)
        while True:
            try:text=await asyncio.to_thread(input,'Patient: ')
            except EOFError:break
            reply=await session.send(text)
            if reply:print('Assistant:',reply.text)
    finally:await session.close()


if __name__=='__main__':
    asyncio.run(main())
