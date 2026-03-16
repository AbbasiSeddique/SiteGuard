"""
Safety Orchestrator — Root ADK agent that coordinates all specialist agents.
Handles three modes: phone (Live API), IP camera (autonomous), recording (batch).
"""

from __future__ import annotations

import asyncio
import base64
import logging
import uuid
from datetime import datetime
from typing import Optional

from google.adk.agents import LlmAgent, SequentialAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService

from core.config import get_settings
from core.safety_standards import get_system_prompt
from models.schemas import CameraMode, Session, SessionStatus
from services.bigquery_service import BigQueryService
from services.camera_manager import CameraManager
from services.firestore_service import FirestoreService
from services.live_api_service import LiveAPIService, LiveAPISession
from services.report_pdf_service import ReportPDFService
from services.recording_processor import RecordingProcessor
from services.storage_service import StorageService
from services.vertex_ai_service import VertexAIService
from tools.adk_tools import build_tools

logger = logging.getLogger(__name__)
settings = get_settings()


class SafetyOrchestrator:
    """
    Root orchestrator that manages the full pipeline:
    - Live phone sessions → Gemini Live API
    - IP camera sessions → autonomous frame streaming to Gemini Live API
    - Recording uploads → batch analysis with Gemini 3.1 Pro
    """

    def __init__(self):
        self.firestore = FirestoreService()
        self.bigquery = BigQueryService()
        self.storage = StorageService()
        self.live_api = LiveAPIService()
        self.camera_mgr = CameraManager()
        self.recording_proc = RecordingProcessor(self.storage)
        self.vertex_ai = VertexAIService()
        self.report_pdf = ReportPDFService()

        self.adk_tools = build_tools(self.firestore, self.bigquery, self.storage)

        # Active sessions: session_id → metadata
        self._active_sessions: dict[str, Session] = {}

        # Callback registry: session_id → callable (sends data back to WebSocket)
        self._ws_callbacks: dict[str, callable] = {}

    # ─── Phone / Supervisor Live Session ──────────────────────────────────────

    async def start_phone_session(
        self,
        camera_id: str,
        site_id: str,
        language: str,
        supervisor_id: Optional[str],
        ws_callback: callable,
    ) -> Session:
        """Start a real-time Live API session for a supervisor's phone camera."""
        session = Session(
            id=str(uuid.uuid4()),
            camera_id=camera_id,
            site_id=site_id,
            mode=CameraMode.PHONE,
            language=language,
            supervisor_id=supervisor_id,
        )

        await self.firestore.create_session(session)
        await self.firestore.update_camera_status(camera_id, "monitoring", session.id)

        self._active_sessions[session.id] = session
        self._ws_callbacks[session.id] = ws_callback

        # Wire violation handler → WebSocket + persistence
        async def on_violation(tool_args: dict, tool_id: str):
            await self._handle_violation(session, tool_args)

        async def on_text(text: str):
            await ws_callback("text_response", {"text": text})

        async def on_audio(audio_b64: str):
            await ws_callback("audio_response", {"audio": audio_b64})

        await self.live_api.create_session(
            session_id=session.id,
            language=language,
            on_text_response=on_text,
            on_audio_response=on_audio,
            on_violation_detected=on_violation,
        )

        logger.info(f"Phone session started: {session.id} cam={camera_id} site={site_id}")
        return session

    async def send_audio(self, session_id: str, pcm_bytes: bytes) -> None:
        """Forward PCM audio bytes from supervisor to Live API."""
        live_session = self.live_api.get_session(session_id)
        if live_session:
            await live_session.send_audio(pcm_bytes)
            await self._increment_frame_count(session_id)

    async def send_video_frame(self, session_id: str, jpeg_bytes: bytes) -> None:
        """Forward a JPEG video frame from supervisor to Live API."""
        live_session = self.live_api.get_session(session_id)
        if live_session:
            await live_session.send_video_frame(jpeg_bytes)
            await self._increment_frame_count(session_id)

    # ─── IP Camera Autonomous Session ─────────────────────────────────────────

    async def start_ip_camera_session(
        self,
        camera,
        ws_callback: Optional[callable] = None,
    ) -> Session:
        """Start autonomous monitoring for an IP/CCTV camera. No human needed."""
        session = Session(
            id=str(uuid.uuid4()),
            camera_id=camera.id,
            site_id=camera.site_id,
            mode=CameraMode.IP_CAMERA,
        )
        await self.firestore.create_session(session)
        await self.firestore.update_camera_status(camera.id, "monitoring", session.id)
        self._active_sessions[session.id] = session

        if ws_callback:
            self._ws_callbacks[session.id] = ws_callback

        async def on_violation(tool_args: dict, tool_id: str):
            await self._handle_violation(session, tool_args)

        async def on_text(text: str):
            # For autonomous cameras, log text responses
            logger.info(f"[Autonomous {camera.id}] AI: {text}")
            if ws_callback:
                await ws_callback("text_response", {"text": text, "camera_id": camera.id})

        async def on_audio(_):
            pass  # No audio playback for autonomous cameras

        await self.live_api.create_session(
            session_id=session.id,
            language="en",
            on_text_response=on_text,
            on_audio_response=on_audio,
            on_violation_detected=on_violation,
        )

        # Wire camera frame capture → Live API
        async def on_frame(sid: str, jpeg_bytes: bytes):
            live_s = self.live_api.get_session(sid)
            if live_s:
                await live_s.send_video_frame(jpeg_bytes)
                # Periodically prompt the agent to analyze (every 10 frames)
                sess = self._active_sessions.get(sid)
                if sess:
                    sess.frame_count = getattr(sess, 'frame_count', 0) + 1
                    if sess.frame_count % 10 == 0:
                        await live_s.send_text(
                            "Analyze the current camera view for any safety violations. "
                            "Report any hazards you can see."
                        )

        async def on_camera_error(cam_id: str, error: str):
            logger.error(f"Camera {cam_id} error: {error}")
            await self.firestore.update_camera_status(cam_id, "error")

        await self.camera_mgr.start_camera(
            camera=camera,
            session_id=session.id,
            on_frame=on_frame,
            on_error=on_camera_error,
        )

        logger.info(f"IP camera session started: {session.id} cam={camera.id}")
        return session

    # ─── Recording Analysis ───────────────────────────────────────────────────

    async def _safe_firestore(self, coro, fallback=None):
        """Run a Firestore coroutine, returning fallback on failure (DB may not exist)."""
        try:
            return await coro
        except Exception as e:
            logger.warning(f"Firestore unavailable, continuing without persistence: {e}")
            return fallback

    async def analyze_recording(
        self,
        camera_id: str,
        site_id: str,
        blob_name: str,
        on_progress: Optional[callable] = None,
    ) -> dict:
        """Process an uploaded recording with Gemini 3.1 Pro batch analysis."""
        session = Session(
            id=str(uuid.uuid4()),
            camera_id=camera_id,
            site_id=site_id,
            mode=CameraMode.RECORDING,
        )
        await self._safe_firestore(self.firestore.create_session(session))
        self._active_sessions[session.id] = session

        # Track violations in memory in case Firestore is unavailable
        in_memory_violations: list = []

        frames_b64 = []
        frames_by_index: dict[int, bytes] = {}
        async for frame_num, frame_b64 in self.recording_proc.extract_frames_from_gcs(blob_name):
            if frame_num > 240:
                break
            frames_b64.append(frame_b64)
            frames_by_index[frame_num] = base64.b64decode(frame_b64)
            if on_progress:
                await on_progress({"frame": frame_num, "status": "extracting"})

        # Batch analyze with Gemini 3.1 Pro (uses 1M context window)
        analysis = await self.vertex_ai.analyze_frames_batch(
            frames_b64=frames_b64,
            context=f"Construction site recording. Camera: {camera_id}",
        )

        # Save detected violations with frame-backed evidence.
        for v_data in analysis.get("violations", []):
            confidence = float(v_data.get("confidence", 0.0))
            if confidence < 0.78:
                continue

            frames_observed = v_data.get("frames_observed") or []
            frame_num = int(frames_observed[0]) if frames_observed else None
            frame_bytes = frames_by_index.get(frame_num) if frame_num else None

            evidence_url = None
            annotated_url = None
            if frame_bytes:
                evidence_url = await self.storage.upload_evidence_frame(
                    session_id=session.id,
                    camera_id=session.camera_id,
                    violation_id=str(uuid.uuid4()),
                    frame_bytes=frame_bytes,
                    annotated=False,
                )

                annotated_bytes = self.recording_proc.annotate_frame(
                    frame_bytes=frame_bytes,
                    label=f"{v_data.get('violation_type', 'violation')} | {v_data.get('osha_code', '')}",
                    bbox=v_data.get("evidence_box"),
                )
                annotated_url = await self.storage.upload_evidence_frame(
                    session_id=session.id,
                    camera_id=session.camera_id,
                    violation_id=str(uuid.uuid4()),
                    frame_bytes=annotated_bytes,
                    annotated=True,
                )

            v_data["evidence_image_url"] = evidence_url
            v_data["annotated_image_url"] = annotated_url
            v_data["frame_number"] = frame_num
            v_data["timestamp_in_video"] = float(frame_num) if frame_num else None

            violation_obj = await self._handle_violation_safe(session, v_data)
            if violation_obj:
                in_memory_violations.append(violation_obj)

        # Try to get violations from Firestore, fall back to in-memory list
        violations = await self._safe_firestore(
            self.firestore.get_violations_for_session(session.id),
            fallback=None,
        )
        if not violations:
            violations = in_memory_violations

        report_text = await self.vertex_ai.generate_report_text(
            violations_data=[v.model_dump(mode="json") if hasattr(v, "model_dump") else v for v in violations],
            session_metadata={
                "site_name": site_id,
                "date": datetime.utcnow().strftime("%Y-%m-%d"),
                "camera_name": camera_id,
                "duration": f"{len(frames_b64)} seconds analyzed",
            },
        )

        osha_annex = self._build_osha_annex(violations)
        nebosh_annex = self._build_nebosh_annex(violations)

        violations_dicts = [v.model_dump(mode="json") if hasattr(v, "model_dump") else v for v in violations]

        report_payload = {
            "title": report_text.get("title", "Engineering Safety Dossier"),
            "session_id": session.id,
            "site_id": site_id,
            "camera_id": camera_id,
            "generated_at": datetime.utcnow().isoformat(),
            "executive_summary": report_text.get("executive_summary", ""),
            "critical_findings": report_text.get("critical_findings", []),
            "corrective_actions": report_text.get("corrective_actions", []),
            "compliance_score": report_text.get("compliance_score", 0),
            "violations": violations_dicts,
            "osha_annex": osha_annex,
            "nebosh_annex": nebosh_annex,
        }

        pdf_bytes = self.report_pdf.build_pdf(report_payload)
        report_id = str(uuid.uuid4())
        pdf_url = await self.storage.upload_report_pdf(session.id, report_id, pdf_bytes)
        json_url = await self.storage.upload_report_json(session.id, report_id, __import__("json").dumps(report_payload, indent=2))

        report_payload["pdf_url"] = pdf_url
        report_payload["json_url"] = json_url

        await self._safe_firestore(self.firestore.end_session(session.id))
        return {
            "session_id": session.id,
            "report": report_payload,
            "violation_count": len(violations),
            "pdf_url": pdf_url,
            "json_url": json_url,
        }

    # ─── End Session ──────────────────────────────────────────────────────────

    async def end_session(self, session_id: str) -> dict:
        """End a live session and generate a compliance report."""
        session = self._active_sessions.pop(session_id, None)
        if not session:
            return {"error": "Session not found"}

        # Close Live API session
        await self.live_api.close_session(session_id)

        # Stop IP camera monitor if applicable
        if session.mode == CameraMode.IP_CAMERA:
            await self.camera_mgr.stop_camera(session.camera_id)

        # Fetch violations and generate report
        violations = await self.firestore.get_violations_for_session(session_id)
        report_data = await self.vertex_ai.generate_report_text(
            violations_data=[v.model_dump(mode="json") for v in violations],
            session_metadata={
                "site_name": session.site_id,
                "date": session.started_at.strftime("%Y-%m-%d"),
                "camera_name": session.camera_id,
            },
        )

        # Update Firestore
        await self.firestore.end_session(session_id)
        await self.firestore.update_camera_status(session.camera_id, "online")

        # Update site risk score
        risk_score = await self.bigquery.get_site_risk_score(session.site_id)
        await self.firestore.update_site_risk_score(session.site_id, risk_score)

        self._ws_callbacks.pop(session_id, None)

        return {
            "session_id": session_id,
            "violation_count": len(violations),
            "report": report_data,
            "risk_score": risk_score,
        }

    # ─── Internal Helpers ─────────────────────────────────────────────────────

    async def _handle_violation_safe(self, session: Session, args: dict):
        """Like _handle_violation but returns the Violation object and doesn't crash on Firestore errors."""
        from models.schemas import Alert, Violation, Severity

        valid_types = {
            "ppe", "fall_protection", "electrical", "struck_by",
            "caught_in", "fire_explosion", "chemical", "housekeeping", "equipment",
        }
        valid_severity = {"critical", "high", "medium", "low"}

        violation_type = str(args.get("violation_type", "equipment")).lower().strip()
        if violation_type not in valid_types:
            violation_type = "equipment"

        severity = str(args.get("severity", "medium")).lower().strip()
        if severity not in valid_severity:
            severity = "medium"

        violation = Violation(
            session_id=session.id,
            camera_id=session.camera_id,
            site_id=session.site_id,
            violation_type=violation_type,
            description=args.get("description", ""),
            osha_code=args.get("osha_code", "Unknown"),
            severity=severity,
            remediation=args.get("remediation", ""),
            confidence=float(args.get("confidence", 0.9)),
            evidence_image_url=args.get("evidence_image_url"),
            annotated_image_url=args.get("annotated_image_url"),
            frame_number=args.get("frame_number"),
            timestamp_in_video=args.get("timestamp_in_video"),
        )

        await self._safe_firestore(self.firestore.save_violation(violation))
        await self._safe_firestore(self.bigquery.log_violation(violation))

        if violation.severity in ("critical", "high"):
            alert = Alert(
                violation_id=violation.id,
                session_id=session.id,
                camera_id=session.camera_id,
                site_id=session.site_id,
                title=f"{'🚨 CRITICAL' if violation.severity == 'critical' else '⚠️ HIGH'}: {violation.osha_code}",
                message=f"{violation.description} — {violation.remediation}",
                severity=Severity(violation.severity),
            )
            await self._safe_firestore(self.firestore.create_alert(alert))

        cb = self._ws_callbacks.get(session.id)
        if cb:
            await cb("violation_detected", violation.model_dump(mode="json"))

        return violation

    async def _handle_violation(self, session: Session, args: dict) -> None:
        """Persist a violation and notify the manager dashboard via WS callback."""
        from models.schemas import Alert, Violation, Severity
        import json

        valid_types = {
            "ppe", "fall_protection", "electrical", "struck_by",
            "caught_in", "fire_explosion", "chemical", "housekeeping", "equipment",
        }
        valid_severity = {"critical", "high", "medium", "low"}

        violation_type = str(args.get("violation_type", "equipment")).lower().strip()
        if violation_type not in valid_types:
            violation_type = "equipment"

        severity = str(args.get("severity", "medium")).lower().strip()
        if severity not in valid_severity:
            severity = "medium"

        violation = Violation(
            session_id=session.id,
            camera_id=session.camera_id,
            site_id=session.site_id,
            violation_type=violation_type,
            description=args.get("description", ""),
            osha_code=args.get("osha_code", "Unknown"),
            severity=severity,
            remediation=args.get("remediation", ""),
            confidence=float(args.get("confidence", 0.9)),
            evidence_image_url=args.get("evidence_image_url"),
            annotated_image_url=args.get("annotated_image_url"),
            frame_number=args.get("frame_number"),
            timestamp_in_video=args.get("timestamp_in_video"),
        )

        await self.firestore.save_violation(violation)
        await self.bigquery.log_violation(violation)

        # Alert for critical/high
        if violation.severity in ("critical", "high"):
            alert = Alert(
                violation_id=violation.id,
                session_id=session.id,
                camera_id=session.camera_id,
                site_id=session.site_id,
                title=f"{'🚨 CRITICAL' if violation.severity == 'critical' else '⚠️ HIGH'}: {violation.osha_code}",
                message=f"{violation.description} — {violation.remediation}",
                severity=Severity(violation.severity),
            )
            await self.firestore.create_alert(alert)

        # Push to WebSocket clients
        cb = self._ws_callbacks.get(session.id)
        if cb:
            await cb("violation_detected", violation.model_dump(mode="json"))

    async def _increment_frame_count(self, session_id: str) -> None:
        session = self._active_sessions.get(session_id)
        if session:
            session.frame_count = getattr(session, "frame_count", 0) + 1

    async def start_all_ip_cameras(self) -> None:
        """Called on startup — start autonomous monitoring for all active IP cameras."""
        cameras = await self.firestore.get_all_ip_cameras()
        logger.info(f"Starting autonomous monitoring for {len(cameras)} IP cameras")
        for cam in cameras:
            if not self.camera_mgr.is_monitoring(cam.id):
                await self.start_ip_camera_session(cam)

    async def shutdown(self) -> None:
        """Gracefully shut down all sessions."""
        await self.live_api.close_all()
        await self.camera_mgr.stop_all()
        logger.info("Safety Orchestrator shutdown complete.")

    def _build_osha_annex(self, violations: list) -> list[str]:
        standards = [
            "29 CFR 1926.20 General safety and health provisions",
            "29 CFR 1926.21 Safety training and education",
            "29 CFR 1926.25 Housekeeping",
            "29 CFR 1926.28 Personal protective equipment responsibilities",
            "29 CFR 1926.95 Personal protective equipment",
            "29 CFR 1926.100 Head protection",
            "29 CFR 1926.102 Eye and face protection",
            "29 CFR 1926.103 Respiratory protection",
            "29 CFR 1926.104 Safety belts lifelines and lanyards",
            "29 CFR 1926.105 Safety nets",
            "29 CFR 1926.106 Working over or near water",
            "29 CFR 1926.150 Fire protection",
            "29 CFR 1926.151 Fire prevention",
            "29 CFR 1926.200 Accident prevention signs and tags",
            "29 CFR 1926.201 Signaling",
            "29 CFR 1926.250 Material handling and storage",
            "29 CFR 1926.251 Rigging equipment",
            "29 CFR 1926.300 Hand and power tools",
            "29 CFR 1926.302 Power-operated hand tools",
            "29 CFR 1926.350 Gas welding and cutting",
            "29 CFR 1926.351 Arc welding and cutting",
            "29 CFR 1926.400 Electrical general requirements",
            "29 CFR 1926.403 General requirements for electrical equipment",
            "29 CFR 1926.404 Wiring design and protection",
            "29 CFR 1926.416 Electrical safety-related work practices",
            "29 CFR 1926.417 Lockout and tagging of circuits",
            "29 CFR 1926.450 Scaffolds general",
            "29 CFR 1926.451 Scaffolds",
            "29 CFR 1926.452 Additional scaffold requirements",
            "29 CFR 1926.453 Aerial lifts",
            "29 CFR 1926.454 Scaffold training",
            "29 CFR 1926.500 Fall protection systems criteria",
            "29 CFR 1926.501 Duty to have fall protection",
            "29 CFR 1926.502 Fall protection systems criteria and practices",
            "29 CFR 1926.503 Fall protection training requirements",
            "29 CFR 1926.550 Cranes and derricks",
            "29 CFR 1926.600 Equipment",
            "29 CFR 1926.601 Motor vehicles",
            "29 CFR 1926.602 Material handling equipment",
            "29 CFR 1926.650 Excavations scope application definitions",
            "29 CFR 1926.651 Specific excavation requirements",
            "29 CFR 1926.652 Excavations protective systems",
        ]
        observed = {v.osha_code for v in violations if getattr(v, "osha_code", None)}
        annex = []
        for s in standards:
            status = "Covered - Violation Observed" if any(code in s for code in observed) else "Covered - Not Observed In This Video"
            annex.append(f"{s}: {status}")
        return annex

    def _build_nebosh_annex(self, violations: list) -> list[str]:
        # Coverage list for practical NEBOSH-aligned management controls.
        elements = [
            "Element 1 Why we should manage workplace health and safety",
            "Element 2 How health and safety management systems work",
            "Element 3 Managing risk understanding people and processes",
            "Element 4 Health and safety monitoring and measuring",
            "Element 5 Physical and psychological health",
            "Element 6 Musculoskeletal health",
            "Element 7 Chemical and biological agents",
            "Element 8 General workplace issues",
            "Element 9 Work equipment",
            "Element 10 Fire",
            "Element 11 Electricity",
            "Element 12 Construction and excavation safety",
            "Element 13 Incident investigation learning and legal response",
            "Element 14 Leadership worker consultation and culture",
            "Element 15 Emergency preparedness and resilience",
            "Element 16 Contractor control and permit to work",
            "Element 17 Occupational health surveillance",
            "Element 18 Competence training and supervision",
            "Element 19 Performance review and continual improvement",
            "Element 20 Audit assurance and governance",
        ]
        high_sev = sum(1 for v in violations if str(getattr(v, "severity", "")) in ("critical", "high"))
        annex = []
        for i, el in enumerate(elements):
            status = "Priority Action Required" if i in (2, 4, 8, 10) and high_sev > 0 else "Reviewed"
            annex.append(f"{el}: {status}")
        return annex
