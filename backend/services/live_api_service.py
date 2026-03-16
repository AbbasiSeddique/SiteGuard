"""Gemini Live API service — real-time bidirectional audio+vision streaming."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from typing import AsyncGenerator, Callable, Optional

from google import genai
from google.genai import types

from core.config import get_settings
from core.safety_standards import get_system_prompt

logger = logging.getLogger(__name__)
settings = get_settings()


class LiveAPISession:
    """
    Manages a single real-time Gemini Live API session for one camera/supervisor.
    Handles bidirectional audio+video streaming with barge-in support.
    """

    def __init__(
        self,
        session_id: str,
        language: str = "en",
        on_text_response: Optional[Callable] = None,
        on_audio_response: Optional[Callable] = None,
        on_violation_detected: Optional[Callable] = None,
    ):
        self.session_id = session_id
        self.language = language
        self.on_text_response = on_text_response
        self.on_audio_response = on_audio_response
        self.on_violation_detected = on_violation_detected

        self._client = genai.Client(
            api_key=settings.gemini_api_key,
            http_options={"api_version": "v1beta"},
        )
        self._session = None
        self._active = False

    async def start(self) -> None:
        """Establish a Live API WebSocket session."""
        system_prompt = get_system_prompt()
        if self.language != "en":
            system_prompt += f"\n\nIMPORTANT: Respond in {self.language} language. Match the worker's language for all voice responses."

        config = types.LiveConnectConfig(
            response_modalities=["AUDIO", "TEXT"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Aoede")
                )
            ),
            system_instruction=system_prompt,
            tools=[
                types.Tool(
                    function_declarations=[
                        types.FunctionDeclaration(
                            name="log_violation",
                            description="Log a detected safety violation to the system",
                            parameters=types.Schema(
                                type="OBJECT",
                                properties={
                                    "violation_type": types.Schema(type="STRING", description="Category: ppe, fall_protection, electrical, struck_by, housekeeping, equipment"),
                                    "description": types.Schema(type="STRING", description="Detailed description of what was observed"),
                                    "osha_code": types.Schema(type="STRING", description="OSHA standard code e.g. OSHA 1926.100(a)"),
                                    "severity": types.Schema(type="STRING", description="critical, high, medium, or low"),
                                    "remediation": types.Schema(type="STRING", description="Immediate corrective action required"),
                                    "confidence": types.Schema(type="NUMBER", description="Detection confidence 0.0-1.0"),
                                },
                                required=["violation_type", "description", "osha_code", "severity", "remediation"],
                            ),
                        )
                    ]
                )
            ],
        )

        self._session_ctx = self._client.aio.live.connect(
            model=settings.gemini_live_model, config=config
        )
        self._session = await self._session_ctx.__aenter__()
        self._active = True
        logger.info(f"Live API session started: {self.session_id} [{self.language}]")

        asyncio.create_task(self._receive_loop())

    async def _receive_loop(self) -> None:
        """Continuously receive and dispatch responses from Gemini."""
        try:
            async for response in self._session.receive():
                if not self._active:
                    break

                # Text response
                if response.text:
                    logger.debug(f"[{self.session_id}] Text: {response.text[:80]}")
                    if self.on_text_response:
                        await self.on_text_response(response.text)

                # Audio response (PCM 24kHz)
                if response.data:
                    if self.on_audio_response:
                        audio_b64 = base64.b64encode(response.data).decode()
                        await self.on_audio_response(audio_b64)

                # Tool call — violation detected by the model
                if response.tool_call:
                    for fc in response.tool_call.function_calls:
                        if fc.name == "log_violation":
                            logger.info(f"[{self.session_id}] Violation tool call: {fc.args}")
                            if self.on_violation_detected:
                                await self.on_violation_detected(dict(fc.args), fc.id)

                            # Return tool response to model
                            await self._session.send(
                                input=types.LiveClientToolResponse(
                                    function_responses=[
                                        types.FunctionResponse(
                                            name="log_violation",
                                            id=fc.id,
                                            response={"logged": True},
                                        )
                                    ]
                                )
                            )

        except Exception as e:
            logger.error(f"[{self.session_id}] Receive loop error: {e}")
            self._active = False

    async def send_audio(self, pcm_bytes: bytes) -> None:
        """Send raw PCM audio (16kHz, 16-bit, mono little-endian)."""
        if not self._session or not self._active:
            return
        await self._session.send(
            input=types.LiveClientRealtimeInput(
                audio=types.Blob(data=pcm_bytes, mime_type="audio/pcm;rate=16000")
            )
        )

    async def send_video_frame(self, jpeg_bytes: bytes) -> None:
        """Send a JPEG video frame (max 1fps)."""
        if not self._session or not self._active:
            return
        await self._session.send(
            input=types.LiveClientRealtimeInput(
                video=types.Blob(data=jpeg_bytes, mime_type="image/jpeg")
            )
        )

    async def send_text(self, message: str) -> None:
        """Send a text message (for autonomous camera mode with no voice input)."""
        if not self._session or not self._active:
            return
        await self._session.send(
            input=types.LiveClientContent(
                turns=[types.Content(role="user", parts=[types.Part(text=message)])],
                turn_complete=True,
            )
        )

    async def interrupt(self) -> None:
        """Stop model output mid-stream (barge-in)."""
        if self._session and self._active:
            await self._session.send(input=types.LiveClientContent(turn_complete=True))

    async def stop(self) -> None:
        """Close the Live API session."""
        self._active = False
        if self._session_ctx:
            try:
                await self._session_ctx.__aexit__(None, None, None)
            except Exception:
                pass
        logger.info(f"Live API session closed: {self.session_id}")


class LiveAPIService:
    """
    Manages a pool of LiveAPISession instances — one per active camera/supervisor.
    """

    def __init__(self):
        self._sessions: dict[str, LiveAPISession] = {}

    async def create_session(
        self,
        session_id: str,
        language: str = "en",
        on_text_response: Optional[Callable] = None,
        on_audio_response: Optional[Callable] = None,
        on_violation_detected: Optional[Callable] = None,
    ) -> LiveAPISession:
        session = LiveAPISession(
            session_id=session_id,
            language=language,
            on_text_response=on_text_response,
            on_audio_response=on_audio_response,
            on_violation_detected=on_violation_detected,
        )
        await session.start()
        self._sessions[session_id] = session
        return session

    def get_session(self, session_id: str) -> Optional[LiveAPISession]:
        return self._sessions.get(session_id)

    async def close_session(self, session_id: str) -> None:
        session = self._sessions.pop(session_id, None)
        if session:
            await session.stop()

    async def close_all(self) -> None:
        for session_id in list(self._sessions.keys()):
            await self.close_session(session_id)

    @property
    def active_count(self) -> int:
        return len(self._sessions)
