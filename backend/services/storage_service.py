"""Cloud Storage service — evidence frames, annotated images, reports."""

from __future__ import annotations

import base64
import io
import logging
import uuid
from datetime import datetime, timedelta
from typing import Optional

from google.cloud import storage

from core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class StorageService:
    def __init__(self):
        self.client = storage.Client(project=settings.gcp_project_id)
        self._evidence_bucket = self.client.bucket(settings.gcs_bucket_evidence)
        self._reports_bucket = self.client.bucket(settings.gcs_bucket_reports)
        self._recordings_bucket = self.client.bucket(settings.gcs_bucket_recordings)

    # ─── Evidence Frames ──────────────────────────────────────────────────────

    async def upload_evidence_frame(
        self,
        session_id: str,
        camera_id: str,
        violation_id: str,
        frame_bytes: bytes,
        annotated: bool = False,
    ) -> str:
        """Upload a violation evidence frame and return the public URL."""
        tag = "annotated" if annotated else "raw"
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        blob_name = f"evidence/{camera_id}/{session_id}/{violation_id}_{tag}_{timestamp}.jpg"

        blob = self._evidence_bucket.blob(blob_name)
        blob.upload_from_string(frame_bytes, content_type="image/jpeg")

        # Generate a signed URL valid for 7 days (for report embedding)
        url = blob.generate_signed_url(expiration=timedelta(days=7))
        logger.info(f"Evidence frame uploaded: {blob_name}")
        return url

    async def upload_evidence_frame_base64(
        self,
        session_id: str,
        camera_id: str,
        violation_id: str,
        frame_b64: str,
        annotated: bool = False,
    ) -> str:
        frame_bytes = base64.b64decode(frame_b64)
        return await self.upload_evidence_frame(
            session_id, camera_id, violation_id, frame_bytes, annotated
        )

    async def upload_thumbnail(self, camera_id: str, frame_bytes: bytes) -> str:
        """Upload the latest camera thumbnail for the manager dashboard grid."""
        blob_name = f"thumbnails/{camera_id}/latest.jpg"
        blob = self._evidence_bucket.blob(blob_name)
        blob.cache_control = "no-cache, max-age=0"
        blob.upload_from_string(frame_bytes, content_type="image/jpeg")
        url = blob.generate_signed_url(expiration=timedelta(hours=1))
        return url

    # ─── Reports ──────────────────────────────────────────────────────────────

    async def upload_report_pdf(
        self, session_id: str, report_id: str, pdf_bytes: bytes
    ) -> str:
        """Upload a compliance report PDF and return a signed URL."""
        timestamp = datetime.utcnow().strftime("%Y%m%d")
        blob_name = f"reports/{timestamp}/{session_id}/{report_id}.pdf"

        blob = self._reports_bucket.blob(blob_name)
        blob.upload_from_string(pdf_bytes, content_type="application/pdf")

        url = blob.generate_signed_url(expiration=timedelta(days=30))
        logger.info(f"Report uploaded: {blob_name}")
        return url

    async def upload_report_json(
        self, session_id: str, report_id: str, report_json: str
    ) -> str:
        """Upload the raw JSON report for archival."""
        timestamp = datetime.utcnow().strftime("%Y%m%d")
        blob_name = f"reports/{timestamp}/{session_id}/{report_id}.json"

        blob = self._reports_bucket.blob(blob_name)
        blob.upload_from_string(report_json.encode(), content_type="application/json")
        url = blob.generate_signed_url(expiration=timedelta(days=30))
        return url

    # ─── Recordings ───────────────────────────────────────────────────────────

    async def generate_upload_url(self, filename: str, content_type: str = "video/mp4") -> tuple[str, str]:
        """Generate a signed upload URL for recording uploads. Returns (upload_url, blob_name)."""
        recording_id = str(uuid.uuid4())
        blob_name = f"uploads/{recording_id}/{filename}"
        blob = self._recordings_bucket.blob(blob_name)

        signed_url = blob.generate_signed_url(
            expiration=timedelta(hours=2),
            method="PUT",
            content_type=content_type,
        )
        return signed_url, blob_name

    async def upload_recording_bytes(
        self,
        filename: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> str:
        """Upload a recording file from backend and return blob name."""
        recording_id = str(uuid.uuid4())
        blob_name = f"uploads/{recording_id}/{filename}"
        blob = self._recordings_bucket.blob(blob_name)
        blob.upload_from_string(data, content_type=content_type)
        logger.info(f"Recording uploaded: {blob_name}")
        return blob_name

    async def upload_recording_fileobj(
        self,
        filename: str,
        file_obj,
        content_type: str = "application/octet-stream",
    ) -> str:
        """Upload a recording file-like object directly to avoid high memory usage."""
        recording_id = str(uuid.uuid4())
        blob_name = f"uploads/{recording_id}/{filename}"
        blob = self._recordings_bucket.blob(blob_name)
        file_obj.seek(0)
        blob.upload_from_file(file_obj, content_type=content_type, rewind=True)
        logger.info(f"Recording uploaded (stream): {blob_name}")
        return blob_name

    async def download_recording(self, blob_name: str) -> bytes:
        """Download a recording for processing."""
        blob = self._recordings_bucket.blob(blob_name)
        return blob.download_as_bytes()

    async def get_recording_as_stream(self, blob_name: str) -> io.BytesIO:
        """Stream a recording file."""
        blob = self._recordings_bucket.blob(blob_name)
        buffer = io.BytesIO()
        blob.download_to_file(buffer)
        buffer.seek(0)
        return buffer
