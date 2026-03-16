"""
ARIA Voice WebSocket — Gemini Live API bidirectional real-time streaming.

Two interaction modes on the same /ws/aria endpoint:
  • Voice  — Gemini Live API (gemini-live-2.5-flash-native-audio) via Vertex AI
              PCM 16kHz in → native PCM 24kHz audio + transcripts
              VAD handles turn-taking; persistent multi-turn session (10 min default, extendable)
  • Text   — Fast-path Firestore/BigQuery + ADK fallback

Audio response path:
  response.data → raw PCM bytes (SDK concatenates inline_data parts automatically)
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import uuid
from typing import Any, Callable, Coroutine, Optional

from fastapi import WebSocket, WebSocketDisconnect
from google import genai
from google.genai import types

from agents.aria_agent import ARIA_SYSTEM_INSTRUCTION, ARIAAgent
from core.config import get_settings
from tools.adk_tools import ARIA_LIVE_TOOL_DECLARATIONS

logger = logging.getLogger(__name__)
settings = get_settings()


# ─── ARIA Live Session ────────────────────────────────────────────────────────

class ARIALiveSession:
    """
    Wraps a Gemini Live API session for real-time voice interaction.

    Handles:
    - Bidirectional audio streaming (PCM 16kHz → Gemini → PCM 24kHz)
    - Both standard audio response path (response.data) and native-audio path
      (server_content.model_turn.parts[].inline_data)
    - VAD-based natural interruption
    - Grounding tool execution
    - Vision frame injection via gemini-2.0-flash
    - Configurable voice (Aoede, Puck, Charon, Kore, Fenrir)
    """

    VALID_VOICES = {"Aoede", "Puck", "Charon", "Kore", "Fenrir"}

    def __init__(
        self,
        site_id: str,
        language: str,
        firestore_svc: Any,
        bigquery_svc: Any,
        on_audio: Callable[[str], Coroutine],
        on_text: Callable[[str, bool], Coroutine],
        on_tool_call: Callable[[str, dict, dict], Coroutine],
        on_interrupted: Callable[[], Coroutine],
        on_user_transcript: Callable[[str], Coroutine],
        on_session_ended: Optional[Callable[[], Coroutine]] = None,
        voice_name: str = "Aoede",
        system_prompt: Optional[str] = None,
        google_search: bool = False,
    ):
        self.site_id = site_id
        self.language = language
        self.voice_name = voice_name if voice_name in self.VALID_VOICES else "Aoede"
        self.system_prompt = system_prompt
        self.google_search = google_search
        self._firestore = firestore_svc
        self._bigquery = bigquery_svc
        self.on_audio = on_audio
        self.on_text = on_text
        self.on_tool_call = on_tool_call
        self.on_interrupted = on_interrupted
        self.on_user_transcript = on_user_transcript
        self._on_session_ended = on_session_ended

        # gemini-live-2.5-flash-native-audio is a Vertex AI model — use project/location auth.
        # Falls back to API key if GCP project is not configured.
        if settings.gcp_project_id:
            self._client = genai.Client(
                vertexai=True,
                project=settings.gcp_project_id,
                location=settings.gcp_region,
            )
        else:
            # AI Studio / API key fallback
            self._client = genai.Client(
                api_key=settings.gemini_api_key,
                http_options={"api_version": "v1beta"},
            )
        # Vision frame analysis always uses API key (generateContent, any region)
        self._vision_client = genai.Client(
            api_key=settings.gemini_api_key,
        )

        self._session: Any = None
        self._session_ctx: Any = None
        self._active = False
        self._last_frame_time = 0.0
        self._last_finding = ""
        # Suppress mic while ARIA is speaking to prevent echo/VAD false triggers.
        # Start False — mic is open immediately, ARIA responds when user speaks.
        self._aria_turn_active = False
        self._user_stopped = False   # True when stop() is called by the WS handler

    async def start(self) -> None:
        _LANGUAGE_NAMES = {
            "en": "English", "es": "Spanish", "fr": "French",
            "ar": "Arabic", "zh": "Chinese", "hi": "Hindi",
            "de": "German", "pt": "Portuguese", "ja": "Japanese",
        }

        if self.system_prompt:
            system_prompt = self.system_prompt
        else:
            system_prompt = ARIA_SYSTEM_INSTRUCTION
            lang_name = _LANGUAGE_NAMES.get(self.language, self.language)
            system_prompt += f"\n\nIMPORTANT: Always respond in {lang_name}. Transcribe and reply in {lang_name} only, regardless of background noise."
            system_prompt += f"\n\nActive monitoring site: {self.site_id}. Always use site_id='{self.site_id}' in tool calls."

        # Inject a compact site snapshot — enough for ARIA to answer voice queries.
        # Keep it short: the native audio Live API is sensitive to large system prompts.
        try:
            status = await self._get_live_site_status(self.site_id)
            sev = status.get("violations_by_severity", {})
            top_v = await self._get_recent_violations(self.site_id, 3)
            top_line = "; ".join(
                f"{v.get('violation_type','')} ({v.get('osha_code','')})"
                for v in top_v.get("violations", [])[:3]
            ) or "none"
            system_prompt += (
                f"\n\nCURRENT SITE SNAPSHOT [{self.site_id}]: "
                f"Risk {status.get('risk_score',0)}/100 | "
                f"Critical={sev.get('critical',0)} High={sev.get('high',0)} "
                f"Med={sev.get('medium',0)} Low={sev.get('low',0)} | "
                f"Stop-work={'YES' if status.get('stop_work_required') else 'no'} | "
                f"Top issues: {top_line}"
                f"\nSpeak full sentences. Give detailed safety answers using this data."
            )
            logger.info(f"[ARIA Live] Snapshot injected: risk={status.get('risk_score')}")
        except Exception as e:
            logger.warning(f"[ARIA Live] Snapshot fetch failed: {e}")

        config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=self.voice_name)
                )
            ),
            system_instruction=system_prompt,
            # No function declarations — native audio Live model doesn't trigger them
            # reliably and the extra schema causes session rejection (1000).
            # Safety data is pre-injected via the compact site snapshot above.
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            realtime_input_config=types.RealtimeInputConfig(
                automatic_activity_detection=types.AutomaticActivityDetection(
                    disabled=False,
                )
            ),
        )

        self._session_ctx = self._client.aio.live.connect(
            model=settings.gemini_live_model,
            config=config,
        )
        self._session = await self._session_ctx.__aenter__()
        self._active = True
        logger.info(f"[ARIA Live] Session started — site={self.site_id} model={settings.gemini_live_model} voice={self.voice_name}")
        asyncio.create_task(self._receive_loop())

    async def _receive_loop(self) -> None:
        audio_chunks_received = 0
        try:
            async for response in self._session.receive():
                if not self._active:
                    break

                # ── Audio path ─────────────────────────────────────────────────
                # response.data works for ALL models:
                #   • Standard Live models  → raw PCM bytes directly in response.data
                #   • Native-audio models   → SDK auto-concatenates inline_data parts
                #                             into response.data (SDK warning is benign)
                # Do NOT also read model_turn.parts[].inline_data — that would double-play
                # the same bytes and cause robotic/distorted audio.
                if response.data:
                    audio_chunks_received += 1
                    self._aria_turn_active = True  # ARIA is speaking — mic suppressed
                    b64 = base64.b64encode(response.data).decode()
                    await self.on_audio(b64)

                sc = response.server_content
                if sc:
                    # ── Output transcript (what ARIA said) — always stream as non-final ──
                    # turn_complete arrives in a separate message, so we can't rely on
                    # is_final = turn_complete in the same event. Instead we flush on
                    # turn_complete below.
                    out_trans = getattr(sc, "output_audio_transcription", None)
                    if out_trans:
                        text = getattr(out_trans, "text", None)
                        if text:
                            await self.on_text(text, False)

                    # ── Turn complete — ARIA finished speaking, flush transcript ──
                    if getattr(sc, "turn_complete", False):
                        self._aria_turn_active = False
                        # Send empty final signal so frontend commits accumulated transcript
                        await self.on_text("", True)
                        logger.debug("[ARIA Live] Turn complete — transcript flushed, mic re-enabled")

                    # ── Interruption ──────────────────────────────────────────
                    if getattr(sc, "interrupted", False):
                        self._aria_turn_active = False  # User interrupted — open mic
                        await self.on_text("", True)    # Flush partial transcript
                        logger.info("[ARIA Live] Interrupted by user")
                        await self.on_interrupted()

                    # ── Input transcript (what user said) ─────────────────────
                    in_trans = getattr(sc, "input_transcription", None)
                    if in_trans:
                        text = getattr(in_trans, "text", None)
                        if text and text.strip():
                            await self.on_user_transcript(text)

                # ── Tool calls ────────────────────────────────────────────────
                if response.tool_call:
                    for fc in response.tool_call.function_calls:
                        result = await self._dispatch_tool(fc.name, dict(fc.args or {}))
                        if self.on_tool_call:
                            await self.on_tool_call(fc.name, dict(fc.args or {}), result)
                        try:
                            await self._session.send_tool_response(
                                function_responses=[
                                    types.FunctionResponse(
                                        name=fc.name,
                                        id=fc.id,
                                        response=result,
                                    )
                                ]
                            )
                        except Exception as e:
                            logger.warning(f"[ARIA Live] Tool response send error: {e}")

        except Exception as e:
            # APIError 1000 = clean WebSocket closure (e.g. user stopped session) — not a real error
            err_str = str(e)
            if "1000" in err_str:
                logger.info(f"[ARIA Live] Session closed normally (1000)")
            else:
                logger.error(f"[ARIA Live] Receive loop error: {e}", exc_info=True)
        finally:
            self._active = False
            self._aria_turn_active = False
            logger.info(f"[ARIA Live] Receive loop ended. Audio chunks received: {audio_chunks_received}")
            # Only notify of unexpected close — not when user explicitly stopped voice
            if self._on_session_ended and not self._user_stopped:
                try:
                    await self._on_session_ended()
                except Exception:
                    pass

    # ── Tool dispatch ─────────────────────────────────────────────────────────

    async def _dispatch_tool(self, name: str, args: dict) -> dict:
        from core.safety_standards import OSHA_STANDARDS
        try:
            if name == "get_live_site_status":
                return await self._get_live_site_status(args.get("site_id", self.site_id))
            elif name == "get_recent_violations":
                return await self._get_recent_violations(
                    args.get("site_id", self.site_id), int(args.get("limit", 5))
                )
            elif name == "lookup_osha_standard":
                return self._lookup_osha_standard(args.get("query", ""))
            elif name == "get_camera_status":
                return await self._get_camera_status(args.get("site_id", self.site_id))
            elif name == "get_violation_trend":
                return await self._get_violation_trend(
                    args.get("site_id", self.site_id), int(args.get("days", 7))
                )
            elif name == "get_report_analysis":
                from tools.adk_tools import _REPORT_STORE
                session_id = args.get("session_id", "")
                report = _REPORT_STORE.get(session_id)
                if not report:
                    return {"found": False, "error": "No report loaded for this session."}
                violations = report.get("violations", [])
                return {
                    "found": True,
                    "title": report.get("title", ""),
                    "compliance_score": report.get("compliance_score", 0),
                    "executive_summary": report.get("executive_summary", ""),
                    "critical_findings": report.get("critical_findings", []),
                    "corrective_actions": report.get("corrective_actions", []),
                    "violation_count": len(violations),
                    "violations": violations[:10],
                }
            else:
                return {"error": f"Unknown tool: {name}"}
        except Exception as e:
            logger.error(f"[ARIA Live] Tool dispatch error [{name}]: {e}")
            return {"error": str(e)}

    async def _get_live_site_status(self, site_id: str) -> dict:
        alerts, violations, risk_score = await asyncio.gather(
            self._safe(self._firestore.get_active_alerts(site_id), []),
            self._safe(self._firestore.get_recent_violations(site_id, limit=20), []),
            self._safe(self._bigquery.get_site_risk_score(site_id), 0),
        )
        counts: dict[str, int] = {"critical": 0, "high": 0, "medium": 0, "low": 0}
        for v in violations:
            sev = str(getattr(v, "severity", "low")).lower()
            counts[sev] = counts.get(sev, 0) + 1
        return {
            "site_id": site_id,
            "risk_score": risk_score,
            "health": "HIGH RISK" if risk_score >= 75 else ("ELEVATED" if risk_score >= 50 else "OK"),
            "open_alerts": len(alerts),
            "violations_by_severity": counts,
            "stop_work_required": counts["critical"] > 0,
        }

    async def _get_recent_violations(self, site_id: str, limit: int) -> dict:
        violations = await self._safe(self._firestore.get_recent_violations(site_id, limit=limit), [])
        return {
            "count": len(violations),
            "violations": [
                {
                    "violation_type": getattr(v, "violation_type", ""),
                    "description": getattr(v, "description", ""),
                    "osha_code": getattr(v, "osha_code", ""),
                    "severity": getattr(v, "severity", ""),
                    "remediation": getattr(v, "remediation", ""),
                }
                for v in violations
            ],
        }

    def _lookup_osha_standard(self, query: str) -> dict:
        q = query.lower()
        matches = [
            {
                "code": s.code, "title": s.title,
                "description": s.description[:200],
                "severity": s.severity.value,
                "remediation": s.remediation,
            }
            for s in OSHA_STANDARDS
            if q in s.code.lower() or q in s.title.lower() or any(q in kw.lower() for kw in s.keywords)
        ][:3]
        return {"found": bool(matches), "standards": matches}

    async def _get_camera_status(self, site_id: str) -> dict:
        cameras = await self._safe(self._firestore.get_cameras_for_site(site_id), [])
        monitoring = sum(1 for c in cameras if getattr(c, "status", "") == "monitoring")
        return {
            "total": len(cameras),
            "monitoring": monitoring,
            "cameras": [
                {"id": getattr(c, "id", ""), "name": getattr(c, "name", ""),
                 "status": getattr(c, "status", ""), "location": getattr(c, "location_description", "")}
                for c in cameras
            ],
        }

    async def _get_violation_trend(self, site_id: str, days: int) -> dict:
        summary = await self._safe(self._bigquery.get_violations_summary(site_id, days=days), {})
        risk = await self._safe(self._bigquery.get_site_risk_score(site_id), 0)
        return {"period_days": days, "risk_score": risk, "summary": summary}

    async def _safe(self, coro: Any, fallback: Any) -> Any:
        try:
            return await coro
        except Exception as e:
            logger.warning(f"[ARIA Live] Tool query failed: {e}")
            return fallback

    # ── Audio / video input ───────────────────────────────────────────────────

    async def send_audio(self, pcm_bytes: bytes) -> None:
        if not self._session or not self._active:
            return
        if self._aria_turn_active:
            # ARIA is speaking — send PCM silence instead of real mic audio.
            # Silence keeps the native audio model WebSocket alive (it closes in ~200ms
            # if it receives no input at all) WITHOUT triggering Gemini's VAD, so
            # ARIA can complete her response without being interrupted by echo/noise.
            silence = bytes(len(pcm_bytes))
            try:
                await self._session.send_realtime_input(
                    audio=types.Blob(data=silence, mime_type="audio/pcm;rate=16000")
                )
            except Exception:
                pass
            return
        try:
            await self._session.send_realtime_input(
                audio=types.Blob(data=pcm_bytes, mime_type="audio/pcm;rate=16000")
            )
        except Exception as e:
            logger.warning(f"[ARIA Live] Audio send error: {e}")

    async def send_video_frame(self, jpeg_bytes: bytes) -> None:
        """
        Rate-limited vision analysis: gemini-2.0-flash analyzes the JPEG frame
        and injects text findings into the Live audio session (max 1 analysis per 3s).
        """
        if not self._session or not self._active:
            return
        import time
        now = time.monotonic()
        if now - self._last_frame_time < 3.0:
            return
        self._last_frame_time = now
        asyncio.create_task(self._analyze_and_inject(jpeg_bytes))

    async def _analyze_and_inject(self, jpeg_bytes: bytes) -> None:
        try:
            response = await self._vision_client.aio.models.generate_content(
                model=settings.gemini_model,
                contents=types.Content(
                    parts=[
                        types.Part(text=(
                            "Construction site safety inspector. Identify any safety violations, "
                            "missing PPE, hazards, or OSHA non-compliance in one sentence maximum. "
                            "Lead with the most critical finding. If everything is safe, reply: Clear."
                        )),
                        types.Part(inline_data=types.Blob(data=jpeg_bytes, mime_type="image/jpeg")),
                    ]
                ),
            )
            analysis = (response.text or "").strip()
            if not analysis or analysis.lower().startswith("clear"):
                return
            if analysis == self._last_finding:
                return
            self._last_finding = analysis
            if self._active and self._session:
                await self._session.send_client_content(
                    turns=[types.Content(
                        role="user",
                        parts=[types.Part(text=f"[Camera frame analysis]: {analysis}")],
                    )],
                    turn_complete=True,
                )
        except Exception as e:
            logger.warning(f"[ARIA Live] Frame analysis error: {e}")

    async def send_text(self, message: str) -> None:
        if not self._session or not self._active:
            return
        try:
            await self._session.send_client_content(
                turns=[types.Content(role="user", parts=[types.Part(text=message)])],
                turn_complete=True,
            )
        except Exception as e:
            logger.warning(f"[ARIA Live] Text send error: {e}")

    async def stop(self) -> None:
        self._user_stopped = True   # Mark as intentional — suppress on_session_ended
        self._active = False
        if self._session_ctx:
            try:
                await self._session_ctx.__aexit__(None, None, None)
            except Exception:
                pass
        logger.info(f"[ARIA Live] Session stopped site={self.site_id}")


# ─── Fast direct-query path (no ADK overhead for simple intents) ──────────────

async def _fast_query(text: str, site_id: str, firestore_svc: Any, bigquery_svc: Any, session_id: str = "") -> Optional[dict]:
    from core.safety_standards import OSHA_STANDARDS

    async def _safe(coro: Any, fallback: Any) -> Any:
        try:
            return await coro
        except Exception:
            return fallback

    q = text.lower()

    # Briefing / status / stop-work queries
    if any(kw in q for kw in ("briefing", "status", "overview", "risk", "how is", "site report",
                               "stop work", "stop-work", "stopwork", "needed", "should we stop",
                               "work order", "critical", "safe to continue", "safe to work")):
        alerts, violations, risk_score = await asyncio.gather(
            _safe(firestore_svc.get_active_alerts(site_id), []),
            _safe(firestore_svc.get_recent_violations(site_id, limit=20), []),
            _safe(bigquery_svc.get_site_risk_score(site_id), 0),
        )
        counts: dict[str, int] = {"critical": 0, "high": 0, "medium": 0, "low": 0}
        for v in violations:
            sev = str(getattr(v, "severity", "low")).lower()
            counts[sev] = counts.get(sev, 0) + 1
        top3 = violations[:3]
        top3_lines = "\n".join(
            f"  • [{getattr(v, 'severity', '').upper()}] {getattr(v, 'violation_type', '')} ({getattr(v, 'osha_code', 'N/A')})"
            for v in top3
        )
        header = (
            f"Risk Score: {risk_score}/100 | Alerts: {len(alerts)} | "
            f"Critical: {counts['critical']}, High: {counts['high']}, "
            f"Medium: {counts['medium']}, Low: {counts['low']}"
        )
        body = f"{header}\n\nTop violations:\n{top3_lines}" if top3_lines else header
        prefix = "🚨 STOP WORK — " if counts["critical"] > 0 else ""
        return {"text": f"{prefix}{body}", "tool_calls": ["get_live_site_status"]}

    # Violations — "violat" matches both "violation" and "violated"; "osha"/"cfr" catches code queries
    if any(kw in q for kw in ("violat", "detected", "found", "recent", "hazard", "evidence", "image", "osha", "cfr", "protective", "ppe", "risk")):
        # Filter to current scan session when available so ARIA never shows stale data
        if session_id:
            violations = await _safe(firestore_svc.get_violations_for_session(session_id), [])
        else:
            violations = await _safe(firestore_svc.get_recent_violations(site_id, limit=10), [])
        if not violations:
            return {"text": "No violations found for this video scan.", "tool_calls": [], "images": []}
        lines = "\n".join(
            f"  • [{str(getattr(v, 'severity', '')).upper()}] {getattr(v, 'violation_type', '')} ({getattr(v, 'osha_code', 'N/A')}) — {str(getattr(v, 'description', ''))[:80]}"
            for v in violations
        )
        # Collect evidence images from this session's violations
        images = []
        for v in violations:
            img_url = getattr(v, "annotated_image_url", None) or getattr(v, "evidence_image_url", None)
            if img_url:
                sev = str(getattr(v, "severity", "medium"))
                sev = sev.value if hasattr(sev, "value") else str(sev).lower()
                images.append({
                    "url": img_url,
                    "caption": f"{getattr(v, 'violation_type', 'Violation')} — {getattr(v, 'osha_code', '')}",
                    "severity": sev,
                })
        return {"text": f"Violations detected ({len(violations)}):\n{lines}", "tool_calls": ["get_recent_violations"], "images": images}

    # Camera / monitoring
    if any(kw in q for kw in ("camera", "monitoring", "feed", "coverage")):
        cameras = await _safe(firestore_svc.get_cameras_for_site(site_id), [])
        active_count = sum(1 for c in cameras if getattr(c, "status", "") == "monitoring")
        cam_lines = "\n".join(
            f"  • {getattr(c, 'name', getattr(c, 'id', '?'))} — {getattr(c, 'status', 'unknown')}"
            for c in cameras
        )
        body = f"Total: {len(cameras)} | Active: {active_count}\n{cam_lines}" if cam_lines else f"Total: {len(cameras)} | Active: {active_count}"
        return {"text": body, "tool_calls": ["get_camera_status"]}

    return None  # Let ADK handle complex queries


# ─── ARIA WebSocket Handler ────────────────────────────────────────────────────

async def aria_ws_handler(
    websocket: WebSocket,
    aria_agent: ARIAAgent,
    firestore_svc: Any,
    bigquery_svc: Any,
    site_id: str,
    language: str = "en",
) -> None:
    await websocket.accept()
    logger.info(f"[ARIA WS] Connected — site={site_id} lang={language}")

    live_session: Optional[ARIALiveSession] = None
    demo_prefix: str = ""
    # Current inspection session ID — set by the frontend when a video scan finishes.
    # All subsequent fast-path queries are scoped to this session so ARIA only
    # shows violations from the most recent video, not stale historical data.
    current_inspection_session_id: str = ""

    async def send(msg_type: str, data: Any = None) -> None:
        try:
            await websocket.send_json({"type": msg_type, "data": data or {}})
        except Exception:
            pass

    try:
        while True:
            raw = await websocket.receive()

            # ── Binary PCM audio ───────────────────────────────────────────────
            if "bytes" in raw and raw["bytes"]:
                if live_session and live_session._active:
                    await live_session.send_audio(raw["bytes"])
                continue

            if "text" not in raw or not raw["text"]:
                continue

            msg = json.loads(raw["text"])
            msg_type = msg.get("type", "")

            # ── Start voice session ────────────────────────────────────────────
            if msg_type == "start_voice":
                if live_session:
                    await live_session.stop()

                session_site = msg.get("site_id", site_id)
                session_lang = msg.get("language", language)
                session_voice = msg.get("voice_name", "Aoede")
                system_prompt = msg.get("system_prompt")
                google_search = msg.get("google_search", False)
                demo_prefix = f"demo-{uuid.uuid4().hex[:8]}-" if msg.get("demo_mode") else ""

                async def on_audio(b64: str) -> None:
                    await send("aria_audio", {"audio": b64})

                async def on_text(text: str, final: bool = False) -> None:
                    await send("aria_transcript", {"text": text, "final": final})

                async def on_tool_call(tool: str, args: dict, result: dict) -> None:
                    await send("tool_call", {"tool": tool, "args": args, "result": result})

                async def on_interrupted() -> None:
                    await send("aria_interrupted")

                async def on_user_transcript(text: str) -> None:
                    await send("user_transcript", {"text": text})

                async def on_session_ended() -> None:
                    # Session closed unexpectedly — tell the frontend so it can restart
                    await send("voice_session_died", {"site_id": session_site})

                live_session = ARIALiveSession(
                    site_id=session_site,
                    language=session_lang,
                    firestore_svc=firestore_svc,
                    bigquery_svc=bigquery_svc,
                    on_audio=on_audio,
                    on_text=on_text,
                    on_tool_call=on_tool_call,
                    on_interrupted=on_interrupted,
                    on_user_transcript=on_user_transcript,
                    on_session_ended=on_session_ended,
                    voice_name=session_voice,
                    system_prompt=system_prompt,
                    google_search=google_search,
                )
                await live_session.start()
                await send("session_started", {"site_id": session_site, "voice_name": session_voice})

            # ── Stop voice session ─────────────────────────────────────────────
            elif msg_type == "stop_voice":
                if live_session:
                    await live_session.stop()
                    live_session = None
                demo_prefix = ""
                await send("session_ended")

            # ── Video frame ────────────────────────────────────────────────────
            elif msg_type == "video_frame":
                if live_session:
                    frame_b64 = msg.get("data", "")
                    if frame_b64:
                        await live_session.send_video_frame(base64.b64decode(frame_b64))

            # ── Interrupt (user pressed button) ────────────────────────────────
            elif msg_type == "interrupt":
                if live_session and live_session._active and live_session._session:
                    # Open mic first — user wants to speak
                    live_session._aria_turn_active = False
                    try:
                        # Minimal text turn signals turn_complete to stop generation
                        await live_session._session.send_client_content(
                            turns=[types.Content(role="user", parts=[types.Part(text="")])],
                            turn_complete=True,
                        )
                    except Exception as e:
                        logger.warning(f"[ARIA WS] Interrupt error: {e}")
                await send("aria_interrupted")

            # ── Text query ─────────────────────────────────────────────────────
            elif msg_type == "text_query":
                text = msg.get("text", "").strip()
                query_site = msg.get("site_id", site_id)
                raw_user_id = msg.get("user_id", "anonymous")
                if not text:
                    continue

                adk_user_id = f"{demo_prefix}{raw_user_id}" if demo_prefix else raw_user_id

                # Fast path first (instant response from Firestore/BigQuery)
                # Prefer the session_id from the message, fall back to the stored one
                text_session_id = msg.get("session_id", "") or current_inspection_session_id
                fast = await _fast_query(text, query_site, firestore_svc, bigquery_svc, session_id=text_session_id)
                if fast is not None:
                    raw_tools = fast.get("tool_calls", [])
                    norm_tools = [
                        {"tool": t, "args": {}, "result": {}} if isinstance(t, str) else t
                        for t in raw_tools
                    ]
                    await send("aria_text", {
                        "text": fast["text"],
                        "tool_calls": norm_tools,
                        "images": fast.get("images", []),
                    })
                else:
                    # ADK fallback for complex queries
                    await send("aria_thinking", {"query": text})
                    try:
                        async for event in aria_agent.query_stream(
                            user_id=adk_user_id,
                            site_id=query_site,
                            message=text,
                        ):
                            if event["type"] == "tool_call":
                                await send("tool_call", {"tool": event["tool"], "args": event["args"]})
                            elif event["type"] == "transcript":
                                await send("aria_transcript", {"text": event["text"], "final": False})
                            elif event["type"] == "final":
                                # aria_text clears the live transcript accumulator in the frontend
                                # — do NOT also send aria_transcript final or the message appears twice
                                await send("aria_text", {
                                    "text": event["text"],
                                    "tool_calls": event["tool_calls"],
                                    "images": event.get("images", []),
                                })
                    except Exception as e:
                        logger.error(f"[ARIA WS] ADK query error: {e}", exc_info=True)
                        await send("error", {"message": f"Query failed: {e}"})

            # ── Inspection session context ─────────────────────────────────────
            # Sent by the frontend when a video scan finishes so subsequent
            # ARIA queries are automatically scoped to the current session.
            elif msg_type == "set_inspection_session":
                current_inspection_session_id = msg.get("session_id", "")
                logger.info(f"[ARIA WS] Inspection session set: {current_inspection_session_id}")

            elif msg_type == "ping":
                await send("pong")

    except WebSocketDisconnect:
        logger.info(f"[ARIA WS] Disconnected — site={site_id}")
    except RuntimeError as e:
        # "Cannot call receive once a disconnect message has been received" — normal closure
        if "disconnect" in str(e).lower():
            logger.info(f"[ARIA WS] Connection closed — site={site_id}")
        else:
            logger.error(f"[ARIA WS] Handler error: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"[ARIA WS] Handler error: {e}", exc_info=True)
        try:
            await send("error", {"message": str(e)})
        except Exception:
            pass
    finally:
        if live_session:
            await live_session.stop()
