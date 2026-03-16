"""Recording processor — FFmpeg-based video analysis for uploaded recordings."""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import AsyncGenerator, Optional

import cv2
import numpy as np

from core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def _run_ffmpeg(cmd: list[str]) -> tuple[int, str]:
    """Run FFmpeg synchronously (used via thread executor to avoid Windows asyncio issues)."""
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode, result.stderr


class RecordingProcessor:
    """
    Processes uploaded video recordings:
    1. Downloads from Cloud Storage
    2. Extracts frames using FFmpeg at 1fps
    3. Yields base64 JPEG frames for analysis
    """

    def __init__(self, storage_service):
        self.storage = storage_service

    async def extract_frames_from_bytes(
        self, video_bytes: bytes, fps: float = 1.0, max_frames: int = 900
    ) -> AsyncGenerator[tuple[int, str], None]:
        """
        Extract frames from video bytes at the given fps.
        Yields (frame_number, base64_jpeg_string) tuples.
        Uses FFmpeg via subprocess run in a thread (Windows-safe).
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            video_path = os.path.join(tmpdir, "input.mp4")
            frames_dir = os.path.join(tmpdir, "frames")
            os.makedirs(frames_dir)

            with open(video_path, "wb") as f:
                f.write(video_bytes)

            cmd = [
                "ffmpeg", "-i", video_path,
                "-vf", f"fps={fps},scale='min(iw,{settings.frame_max_width}):trunc(ow/a/2)*2'",
                "-q:v", "5",
                "-frames:v", str(max_frames),
                os.path.join(frames_dir, "frame_%05d.jpg"),
                "-y", "-loglevel", "error"
            ]

            # Run in thread executor — asyncio.create_subprocess_exec fails on Windows
            # when uvicorn uses its own event loop with SelectorEventLoop
            returncode, stderr = await asyncio.get_event_loop().run_in_executor(
                None, _run_ffmpeg, cmd
            )

            if returncode != 0:
                logger.error(f"FFmpeg error: {stderr}")
                raise RuntimeError(f"FFmpeg failed: {stderr}")

            frame_files = sorted(Path(frames_dir).glob("frame_*.jpg"))
            logger.info(f"Extracted {len(frame_files)} frames from recording")

            for i, frame_path in enumerate(frame_files):
                with open(frame_path, "rb") as f:
                    frame_bytes = f.read()
                frame_b64 = base64.b64encode(frame_bytes).decode()
                yield i + 1, frame_b64

    async def extract_frames_from_gcs(
        self, blob_name: str, fps: float = 1.0
    ) -> AsyncGenerator[tuple[int, str], None]:
        """Download a recording from Cloud Storage and extract frames."""
        logger.info(f"Downloading recording: {blob_name}")
        video_bytes = await self.storage.download_recording(blob_name)
        async for frame_num, frame_b64 in self.extract_frames_from_bytes(video_bytes, fps=fps):
            yield frame_num, frame_b64

    async def get_video_duration(self, video_bytes: bytes) -> Optional[float]:
        """Get video duration in seconds using ffprobe."""
        try:
            with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
                f.write(video_bytes)
                tmp_path = f.name

            cmd = [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                tmp_path
            ]
            result = await asyncio.get_event_loop().run_in_executor(
                None, lambda: subprocess.run(cmd, capture_output=True, text=True)
            )
            os.unlink(tmp_path)
            return float(result.stdout.strip())
        except Exception as e:
            logger.warning(f"Could not get video duration: {e}")
            return None

    def annotate_frame(
        self,
        frame_bytes: bytes,
        label: str,
        bbox: Optional[dict] = None,
    ) -> bytes:
        """Draw a red evidence annotation over a frame and return JPEG bytes."""
        arr = np.frombuffer(frame_bytes, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            return frame_bytes

        h, w = img.shape[:2]

        x1, y1, x2, y2 = int(0.2 * w), int(0.2 * h), int(0.8 * w), int(0.8 * h)
        if bbox:
            try:
                bx = float(bbox.get("x", 0.2))
                by = float(bbox.get("y", 0.2))
                bw = float(bbox.get("w", 0.6))
                bh = float(bbox.get("h", 0.6))
                x1 = max(0, min(w - 1, int(bx * w)))
                y1 = max(0, min(h - 1, int(by * h)))
                x2 = max(x1 + 1, min(w, int((bx + bw) * w)))
                y2 = max(y1 + 1, min(h, int((by + bh) * h)))
            except Exception:
                pass

        cv2.rectangle(img, (x1, y1), (x2, y2), (0, 0, 255), 4)

        banner_h = 38
        cv2.rectangle(img, (0, 0), (w, banner_h), (0, 0, 255), -1)
        safe_label = label[:90]
        cv2.putText(
            img,
            f"VIOLATION EVIDENCE: {safe_label}",
            (12, 25),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.62,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )

        ok, encoded = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
        if not ok:
            return frame_bytes
        return encoded.tobytes()
