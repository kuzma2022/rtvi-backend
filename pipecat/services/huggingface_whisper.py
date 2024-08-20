#
# Copyright (c) 2024, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

"""This module implements Whisper transcription with a locally-downloaded model."""

import asyncio

from enum import Enum
from typing_extensions import AsyncGenerator
from transformers import pipeline
import numpy as np

from pipecat.frames.frames import ErrorFrame, Frame, TranscriptionFrame
from pipecat.services.ai_services import STTService
from pipecat.utils.time import time_now_iso8601
import torch

from loguru import logger


class Model(Enum):
    """Class of basic Whisper model selection options"""
    BELLE = "BELLE-2/Belle-whisper-large-v3-zh"


class HuggingFaceWhisperSTTService(STTService):
    """Class to transcribe audio with a locally-downloaded Whisper model"""

    def __init__(self,
                 *,
                 model: str | Model = Model.BELLE,
                 **kwargs):

        super().__init__(**kwargs)
        self._model_name: str | Model = model
        self._load()

    def can_generate_metrics(self) -> bool:
        return True

    def _load(self):
        """Loads the Whisper model. Note that if this is the first time
        this model is being run, it will take time to download."""
        logger.debug(f"Loading Whisper model {self._model_name.value}...")

        if torch.cuda.is_available():
            device = "cuda"
            torch_dtype = torch.float16
        elif torch.backends.mps.is_available():
            device = "mps"
            torch_dtype = torch.float16
        else:
            device = "cpu"
            torch_dtype = torch.float32

        self.transcriber = pipeline(
            "automatic-speech-recognition", 
            model= self._model_name.value,
            torch_dtype=torch_dtype,
            device=device,
        )

        self.transcriber.model.config.forced_decoder_ids = (
            self.transcriber.tokenizer.get_decoder_prompt_ids(
                language="zh", 
                task="transcribe"
            )
        )
        logger.debug("Loaded Whisper model")

    async def run_stt(self, audio: bytes) -> AsyncGenerator[Frame, None]:
        """Transcribes given audio using Whisper"""
        if not self.transcriber:
            logger.error(f"{self} error: Whisper model not available")
            yield ErrorFrame("Whisper model not available")
            return

        await self.start_ttfb_metrics()

        # Divide by 32768 because we have signed 16-bit data.
        audio_float = np.frombuffer(audio, dtype=np.int16).astype(np.float32) / 32768.0

        result = await asyncio.to_thread(self.transcriber, audio_float)
        text: str = result["text"]
    
        if text:
            await self.stop_ttfb_metrics()
            logger.debug(f"Transcription: [{text}]")
            yield TranscriptionFrame(text, "", time_now_iso8601())
