#
# Copyright (c) 2024, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

import json
import uuid
import base64
import asyncio
import time
import gzip
from typing import AsyncGenerator

from pipecat.processors.frame_processor import FrameDirection
from pipecat.frames.frames import (
    Frame,
    AudioRawFrame,
    StartInterruptionFrame,
    StartFrame,
    EndFrame,
    TextFrame,
    LLMFullResponseEndFrame
)
from pipecat.services.ai_services import TTSService

from loguru import logger

# See .env.example for Cartesia configuration needed
try:
    import websockets
except ModuleNotFoundError as e:
    logger.error(f"Exception: {e}")
    raise Exception(f"Missing module: {e}")

class BytedanceTTSService(TTSService):

    """This service uses the  Bytedance TTS API to generate audio from text.
    The returned audio is PCM encoded at 24kHz. When using the DailyTransport, set the sample rate in the DailyParams accordingly:
    ```
    DailyParams(
        audio_out_enabled=True,
        audio_out_sample_rate=24000,
    )
    ```
    """

    def __init__(
            self,
            *,
            appid: str,
            api_key: str,
            cluster: str = "volcano_tts",
            voice_id: str= "zh_female_shuangkuaisisi_moon_bigtts",
            api_url: str = "wss://openspeech.bytedance.com/api/v1/tts/ws_binary",
            encoding: str = "pcm",
            **kwargs):
        super().__init__(**kwargs)

        self._appid = appid
        self._token = api_key
        self._cluster = cluster
        self._voice = voice_id
        self._api_url = api_url
        self._encoding = encoding


        self._websocket = None
    
    def can_generate_metrics(self) -> bool:
        return True

    async def set_voice(self, voice: str):
        logger.debug(f"Switching TTS voice to: [{voice}]")
        self._voice = voice

    async def start(self, frame: StartFrame):
        await super().start(frame)
        await self._connect()

    async def stop(self, frame: EndFrame):
        await super().stop(frame)
        await self._disconnect()

    async def _connect(self):
        try:
            header = {"Authorization": f"Bearer; {self._token}"}
            self._websocket = await websockets.connect(self._api_url, extra_headers=header, ping_interval=None)
        except Exception as e:
            logger.exception(f"{self} initialization error: {e}")
            self._websocket = None

    async def _disconnect(self):
        try:
            if self._websocket:
                ws = self._websocket
                self._websocket = None
                await ws.close()
        except Exception as e:
            logger.exception(f"{self} error closing websocket: {e}")

    async def _handle_interruption(self, frame: StartInterruptionFrame, direction: FrameDirection):
        await super()._handle_interruption(frame, direction)
        await self._disconnect()

    async def run_tts(self, text: str) -> AsyncGenerator[Frame, None]:
        try:
            logger.debug(f"doubao run_tts text: {text}")
            if not self._websocket:
                await self._connect()

            request_json = {
                "app": {
                    "appid": self._appid,
                    "token": self._token,
                    "cluster": self._cluster
                },
                "user": {
                    "uid": "388808087185088"
                },
                "audio": {
                    "voice_type": self._voice,
                    "encoding": self._encoding,
                    "speed_ratio": 1.0,
                    "volume_ratio": 1.0,
                    "pitch_ratio": 1.0,
                },
                "request": {
                    "reqid": str(uuid.uuid4()),
                    "text": text,
                    "text_type": "plain",
                    "operation": "submit"
                }
            }

            payload_bytes = str.encode(json.dumps(request_json))
            payload_bytes = gzip.compress(payload_bytes)
            full_client_request = bytearray(b'\x11\x10\x11\x00')
            full_client_request.extend((len(payload_bytes)).to_bytes(4, 'big'))
            full_client_request.extend(payload_bytes)

            await self.start_ttfb_metrics()
            await self._websocket.send(full_client_request)

            while True:
                res = await self._websocket.recv()
                done = await self.parse_response(res)
                if done:
                    break
            yield None

        except Exception as e:
            logger.exception(f"{self} exception: {e}")


    async def parse_response(self,res):
        protocol_version = res[0] >> 4
        header_size = res[0] & 0x0f
        message_type = res[1] >> 4
        message_type_specific_flags = res[1] & 0x0f
        serialization_method = res[2] >> 4
        message_compression = res[2] & 0x0f
        reserved = res[3]
        header_extensions = res[4:header_size*4]
        payload = res[header_size*4:]
        if header_size != 1:
            print(f"           Header extensions: {header_extensions}")
        if message_type == 0xb:  # audio-only server response
            if message_type_specific_flags == 0:  # no sequence number as ACK
                return False
            else:
                sequence_number = int.from_bytes(payload[:4], "big", signed=True)
                payload_size = int.from_bytes(payload[4:8], "big", signed=False)
                payload = payload[8:]

            await self.stop_ttfb_metrics()
            frame = AudioRawFrame(payload, 24000, 1)
            await self.push_frame(frame)

            if sequence_number < 0:
                return True
            else:
                return False
        elif message_type == 0xf:
            code = int.from_bytes(payload[:4], "big", signed=False)
            msg_size = int.from_bytes(payload[4:8], "big", signed=False)
            error_msg = payload[8:]
            if message_compression == 1:
                error_msg = gzip.decompress(error_msg)
            error_msg = str(error_msg, "utf-8")
            return True
        elif message_type == 0xc:
            msg_size = int.from_bytes(payload[:4], "big", signed=False)
            payload = payload[4:]
            if message_compression == 1:
                payload = gzip.decompress(payload)
        else:
            print("undefined message type!")
            return True

   