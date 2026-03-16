"""FastAPI WebSocket server — real-time streaming for supervisors and managers."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from typing import Any, Optional

from fastapi import WebSocket, WebSocketDisconnect

from models.schemas import CameraMode, StartSessionRequest, WSMessage, WSMessageType

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages all active WebSocket connections."""

    def __init__(self):
        # supervisor connections: session_id → WebSocket
        self._supervisor_conns: dict[str, WebSocket] = {}
        # manager dashboard connections: site_id → set of WebSockets
        self._manager_conns: dict[str, set[WebSocket]] = {}

    async def connect_supervisor(self, session_id: str, ws: WebSocket) -> None:
        await ws.accept()
        self._supervisor_conns[session_id] = ws
        logger.info(f"Supervisor connected: {session_id}")

    async def connect_manager(self, site_id: str, ws: WebSocket) -> None:
        await ws.accept()
        if site_id not in self._manager_conns:
            self._manager_conns[site_id] = set()
        self._manager_conns[site_id].add(ws)
        logger.info(f"Manager connected to site: {site_id} (total: {len(self._manager_conns[site_id])})")

    async def disconnect_supervisor(self, session_id: str) -> None:
        self._supervisor_conns.pop(session_id, None)

    async def disconnect_manager(self, site_id: str, ws: WebSocket) -> None:
        if site_id in self._manager_conns:
            self._manager_conns[site_id].discard(ws)

    async def send_to_supervisor(self, session_id: str, msg_type: str, data: Any) -> None:
        ws = self._supervisor_conns.get(session_id)
        if ws:
            try:
                await ws.send_json({"type": msg_type, "data": data})
            except Exception as e:
                logger.warning(f"Failed to send to supervisor {session_id}: {e}")

    async def broadcast_to_managers(self, site_id: str, msg_type: str, data: Any) -> None:
        conns = self._manager_conns.get(site_id, set())
        if not conns:
            return
        msg = json.dumps({"type": msg_type, "data": data})
        dead = set()
        for ws in list(conns):
            try:
                await ws.send_text(msg)
            except Exception:
                dead.add(ws)
        for ws in dead:
            conns.discard(ws)

    @property
    def supervisor_count(self) -> int:
        return len(self._supervisor_conns)

    @property
    def manager_count(self) -> int:
        return sum(len(v) for v in self._manager_conns.values())


# Global connection manager
connection_manager = ConnectionManager()


async def supervisor_ws_handler(
    websocket: WebSocket,
    orchestrator,
    camera_id: str,
    site_id: str,
    language: str = "en",
) -> None:
    """
    WebSocket handler for supervisor phone mode.
    Accepts audio chunks + video frames, streams back AI voice responses.
    """
    session_id: Optional[str] = None

    try:
        await connection_manager.connect_supervisor("pending", websocket)

        # Create the Live API session
        async def ws_callback(msg_type: str, data: Any) -> None:
            await connection_manager.send_to_supervisor(session_id, msg_type, data)

            # Also broadcast violations/alerts to manager dashboard
            if msg_type == "violation_detected":
                await connection_manager.broadcast_to_managers(site_id, "violation_detected", data)

        session = await orchestrator.start_phone_session(
            camera_id=camera_id,
            site_id=site_id,
            language=language,
            supervisor_id=None,
            ws_callback=ws_callback,
        )
        session_id = session.id

        # Re-register with actual session_id
        connection_manager._supervisor_conns.pop("pending", None)
        await connection_manager.connect_supervisor(session_id, websocket)

        # Notify client session is ready
        await websocket.send_json({
            "type": WSMessageType.SESSION_STARTED,
            "data": {"session_id": session_id},
        })

        # Message receive loop
        while True:
            raw = await websocket.receive()

            if "bytes" in raw and raw["bytes"]:
                # Binary message — determine if audio or video by size/header
                data_bytes = raw["bytes"]
                # Video frames are sent with a 4-byte type prefix: b'VIDF'
                if data_bytes[:4] == b"VIDF":
                    await orchestrator.send_video_frame(session_id, data_bytes[4:])
                else:
                    # Default: PCM audio
                    await orchestrator.send_audio(session_id, data_bytes)

            elif "text" in raw and raw["text"]:
                msg = json.loads(raw["text"])
                msg_type = msg.get("type")

                if msg_type == WSMessageType.TEXT_INPUT:
                    live_s = orchestrator.live_api.get_session(session_id)
                    if live_s:
                        await live_s.send_text(msg["data"].get("text", ""))

                elif msg_type == WSMessageType.VIDEO_FRAME:
                    frame_b64 = msg["data"].get("frame")
                    if frame_b64:
                        jpeg_bytes = base64.b64decode(frame_b64)
                        await orchestrator.send_video_frame(session_id, jpeg_bytes)

                elif msg_type == WSMessageType.AUDIO_CHUNK:
                    audio_b64 = msg["data"].get("audio")
                    if audio_b64:
                        pcm_bytes = base64.b64decode(audio_b64)
                        await orchestrator.send_audio(session_id, pcm_bytes)

                elif msg_type == WSMessageType.END_SESSION:
                    break

                elif msg_type == WSMessageType.PING:
                    await websocket.send_json({"type": WSMessageType.PONG})

    except WebSocketDisconnect:
        logger.info(f"Supervisor disconnected: {session_id}")
    except Exception as e:
        logger.error(f"Supervisor WS error [{session_id}]: {e}")
        try:
            await websocket.send_json({"type": WSMessageType.ERROR, "data": {"message": str(e)}})
        except Exception:
            pass
    finally:
        if session_id:
            result = await orchestrator.end_session(session_id)
            await connection_manager.send_to_supervisor(
                session_id, WSMessageType.SESSION_ENDED, result
            )
            await connection_manager.disconnect_supervisor(session_id)


async def manager_ws_handler(
    websocket: WebSocket,
    site_id: str,
    firestore_svc,
) -> None:
    """
    WebSocket handler for the manager dashboard.
    Pushes real-time alerts, violations, and camera status updates.
    """
    try:
        await connection_manager.connect_manager(site_id, websocket)

        # Send current active alerts on connect
        try:
            alerts = await firestore_svc.get_active_alerts(site_id)
            await websocket.send_json({
                "type": "initial_state",
                "data": {
                    "active_alerts": [a.model_dump(mode="json") for a in alerts],
                }
            })
        except Exception as e:
            logger.warning(f"Failed to send initial state: {e}")

        # Keep alive — wait for disconnect or ping
        while True:
            raw = await websocket.receive()
            if "text" in raw:
                msg = json.loads(raw["text"])
                if msg.get("type") == WSMessageType.PING:
                    await websocket.send_json({"type": WSMessageType.PONG})
                elif msg.get("type") == "acknowledge_alert":
                    alert_id = msg.get("data", {}).get("alert_id")
                    if alert_id:
                        await firestore_svc.resolve_alert(alert_id)

    except WebSocketDisconnect:
        logger.info(f"Manager disconnected from site: {site_id}")
    except Exception as e:
        logger.error(f"Manager WS error: {e}")
    finally:
        await connection_manager.disconnect_manager(site_id, websocket)
