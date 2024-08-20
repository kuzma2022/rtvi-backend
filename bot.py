import asyncio
import sys
import os
import argparse
import json

from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.pipeline.runner import PipelineRunner
from pipecat.processors.frameworks.rtvi import (
    RTVIConfig,
    RTVIProcessor,
    RTVISetup)
from pipecat.frames.frames import EndFrame
from pipecat.services.azure import AzureSTTService
from pipecat.services.doubao import BytedanceTTSService
from pipecat.transports.services.daily import DailyParams, DailyTransport
from pipecat.vad.silero import SileroVADAnalyzer

from loguru import logger

from dotenv import load_dotenv
load_dotenv(override=True)

logger.remove(0)
logger.add(sys.stderr, level="DEBUG")


async def main(room_url, token, bot_config):
    daily_paras = DailyParams(
            audio_out_enabled=True,
            transcription_enabled=False,
            vad_enabled=True,
            vad_audio_passthrough=True,
            vad_analyzer=SileroVADAnalyzer(),
        )

    if bot_config["tts"]["model"] == "doubao" or bot_config["tts"]["model"] == "openai":
         daily_paras = DailyParams(
            audio_out_enabled=True,
            transcription_enabled=False,
            vad_enabled=True,
            vad_audio_passthrough=True,
            vad_analyzer=SileroVADAnalyzer(),
            audio_out_sample_rate=24_000,
        )
        
    transport = DailyTransport(
        room_url,
        token,
        "Realtime AI",
        daily_paras)

    llm_base_url= os.getenv("OPENAI_BASE_URL", "")
    if "llama" in bot_config["llm"]["model"]:
        llm_base_url=os.getenv("LLAMA_BASE_URL", "")
       
    rtai = RTVIProcessor(
        transport=transport,
        setup=RTVISetup(config=RTVIConfig(**bot_config)),
        llm_api_key=os.getenv("OPENAI_API_KEY", ""),
        llm_base_url= llm_base_url,  
    )

    runner = PipelineRunner()

    pipeline = Pipeline([transport.input(), rtai])

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            allow_interruptions=True,
            enable_metrics=True,
            send_initial_empty_metrics=False,
        ))

    @transport.event_handler("on_first_participant_joined")
    async def on_first_participant_joined(transport, participant):
        transport.capture_participant_transcription(participant["id"])
        logger.info("First participant joined")

    @transport.event_handler("on_participant_left")
    async def on_participant_left(transport, participant, reason):
        await task.queue_frame(EndFrame())
        logger.info("Partcipant left. Exiting.")

    @transport.event_handler("on_call_state_updated")
    async def on_call_state_updated(transport, state):
        logger.info("Call state %s " % state)
        if state == "left":
            await task.queue_frame(EndFrame())

    await runner.run(task)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="RTVI Bot Example")
    parser.add_argument("-u", type=str, help="Room URL")
    parser.add_argument("-t", type=str, help="Token")
    parser.add_argument("-c", type=str, help="Bot configuration blob")
    config = parser.parse_args()

    bot_config = json.loads(config.c) if config.c else {}

    if config.u and config.t and bot_config:
        asyncio.run(main(config.u, config.t, bot_config))
    else:
        logger.error("Room URL and Token are required")
