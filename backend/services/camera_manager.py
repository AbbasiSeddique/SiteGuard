"""Camera Manager — autonomous RTSP/HLS IP camera monitoring (no human input)."""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import time
from typing import Optional

import cv2
import numpy as np

from core.config import get_settings
from models.schemas import Camera, CameraMode, CameraStatus

logger = logging.getLogger(__name__)
settings = get_settings()


class IPCameraMonitor:
    """
    Monitors a single IP/CCTV camera via RTSP stream.
    Extracts frames at 1fps and forwards them to a LiveAPISession.
    Runs completely autonomously — no human required.
    """

    def __init__(
        self,
        camera: Camera,
        session_id: str,
        on_frame: callable,  # async (session_id, frame_bytes) -> None
        on_error: callable,  # async (camera_id, error) -> None
    ):
        self.camera = camera
        self.session_id = session_id
        self.on_frame = on_frame
        self.on_error = on_error

        self._cap: Optional[cv2.VideoCapture] = None
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._frame_count = 0
        self._last_frame_time = 0.0

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._capture_loop())
        logger.info(f"IP camera monitor started: {self.camera.id} → {self.camera.stream_url}")

    async def _capture_loop(self) -> None:
        retry_count = 0
        max_retries = 5

        while self._running:
            try:
                # Open stream (runs in thread to avoid blocking event loop)
                self._cap = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: cv2.VideoCapture(self.camera.stream_url)
                )

                if not self._cap.isOpened():
                    raise ConnectionError(f"Cannot open stream: {self.camera.stream_url}")

                retry_count = 0  # Reset on success
                logger.info(f"Stream opened for camera {self.camera.id}")

                interval = 1.0 / settings.frame_rate_fps  # seconds between frames

                while self._running:
                    now = time.monotonic()
                    elapsed = now - self._last_frame_time

                    if elapsed < interval:
                        await asyncio.sleep(interval - elapsed)
                        continue

                    # Read frame in executor (blocking I/O)
                    ret, frame = await asyncio.get_event_loop().run_in_executor(
                        None, self._cap.read
                    )

                    if not ret:
                        logger.warning(f"Frame read failed for {self.camera.id}, reconnecting...")
                        break

                    self._last_frame_time = time.monotonic()
                    self._frame_count += 1

                    # Resize for efficiency
                    frame = self._resize_frame(frame)

                    # Encode as JPEG
                    jpeg_bytes = self._encode_jpeg(frame)

                    # Send frame to Live API via callback
                    await self.on_frame(self.session_id, jpeg_bytes)

            except asyncio.CancelledError:
                break
            except Exception as e:
                retry_count += 1
                logger.error(f"Camera {self.camera.id} error (retry {retry_count}/{max_retries}): {e}")

                if retry_count >= max_retries:
                    await self.on_error(self.camera.id, str(e))
                    self._running = False
                    break

                # Exponential backoff
                await asyncio.sleep(min(2 ** retry_count, 30))

            finally:
                if self._cap:
                    self._cap.release()

    def _resize_frame(self, frame: np.ndarray) -> np.ndarray:
        h, w = frame.shape[:2]
        max_w = settings.frame_max_width
        if w > max_w:
            scale = max_w / w
            new_w, new_h = int(w * scale), int(h * scale)
            frame = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)
        return frame

    def _encode_jpeg(self, frame: np.ndarray) -> bytes:
        encode_params = [cv2.IMWRITE_JPEG_QUALITY, settings.frame_quality]
        _, buffer = cv2.imencode(".jpg", frame, encode_params)
        return buffer.tobytes()

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._cap:
            self._cap.release()
        logger.info(f"IP camera monitor stopped: {self.camera.id}")

    @property
    def frame_count(self) -> int:
        return self._frame_count


class CameraManager:
    """
    Manages all IP camera monitors and autonomous analysis loops.
    One monitor per IP camera, running continuously.
    """

    def __init__(self):
        self._monitors: dict[str, IPCameraMonitor] = {}  # camera_id → monitor

    async def start_camera(
        self,
        camera: Camera,
        session_id: str,
        on_frame: callable,
        on_error: callable,
    ) -> None:
        if camera.id in self._monitors:
            logger.warning(f"Camera {camera.id} already monitored, skipping.")
            return

        monitor = IPCameraMonitor(
            camera=camera,
            session_id=session_id,
            on_frame=on_frame,
            on_error=on_error,
        )
        self._monitors[camera.id] = monitor
        await monitor.start()

    async def stop_camera(self, camera_id: str) -> None:
        monitor = self._monitors.pop(camera_id, None)
        if monitor:
            await monitor.stop()

    async def stop_all(self) -> None:
        for camera_id in list(self._monitors.keys()):
            await self.stop_camera(camera_id)

    def is_monitoring(self, camera_id: str) -> bool:
        return camera_id in self._monitors

    @property
    def active_camera_ids(self) -> list[str]:
        return list(self._monitors.keys())

    @property
    def active_count(self) -> int:
        return len(self._monitors)
