"""Configuration management for SiteGuard AI backend."""

import os
from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # GCP Project
    gcp_project_id: str = os.getenv("GCP_PROJECT_ID", "siteguard-ai")
    gcp_region: str = os.getenv("GCP_REGION", "us-central1")

    # Gemini / Vertex AI
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    vertex_ai_location: str = os.getenv("VERTEX_AI_LOCATION", "us-central1")
    gemini_model: str = "gemini-2.5-flash"                 # Vision + text analysis
    gemini_live_model: str = "gemini-live-2.5-flash-native-audio"   # Live API — GA, native audio, persistent multi-turn
    firestore_collection_sessions: str = "sessions"
    firestore_collection_violations: str = "violations"
    firestore_collection_cameras: str = "cameras"
    firestore_collection_alerts: str = "alerts"
    firestore_collection_reports: str = "reports"

    # BigQuery
    bigquery_dataset: str = "siteguard"
    bigquery_table_violations: str = "violations"
    bigquery_table_events: str = "events"

    # Cloud Storage
    gcs_bucket_evidence: str = os.getenv("GCS_BUCKET_EVIDENCE", "siteguard-evidence")
    gcs_bucket_reports: str = os.getenv("GCS_BUCKET_REPORTS", "siteguard-reports")
    gcs_bucket_recordings: str = os.getenv("GCS_BUCKET_RECORDINGS", "siteguard-recordings")

    # Camera ingestion
    max_cameras: int = 20
    frame_rate_fps: float = 1.0          # 1 frame per second to Gemini
    frame_quality: int = 85              # JPEG quality
    frame_max_width: int = 1280

    # API — set CORS_ORIGINS as comma-separated list in .env for production
    # e.g. CORS_ORIGINS=https://yourapp.run.app,https://yourfrontend.com
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            o.strip() for o in os.getenv(
                "CORS_ORIGINS",
                "http://localhost:3000,http://localhost:5173"
            ).split(",") if o.strip()
        ]
    )
    max_ws_connections: int = 100

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
