"""Pydantic schemas for SiteGuard AI API contracts."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ─── Enums ───────────────────────────────────────────────────────────────────

class Severity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class HazardCategory(str, Enum):
    PPE = "ppe"
    FALL_PROTECTION = "fall_protection"
    ELECTRICAL = "electrical"
    STRUCK_BY = "struck_by"
    CAUGHT_IN = "caught_in"
    FIRE_EXPLOSION = "fire_explosion"
    CHEMICAL = "chemical"
    HOUSEKEEPING = "housekeeping"
    EQUIPMENT = "equipment"


class CameraStatus(str, Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    MONITORING = "monitoring"
    ERROR = "error"


class CameraMode(str, Enum):
    PHONE = "phone"          # Supervisor mobile browser
    IP_CAMERA = "ip_camera"  # Autonomous RTSP/HLS feed
    RECORDING = "recording"  # Uploaded video file


class SessionStatus(str, Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    ERROR = "error"


class AlertStatus(str, Enum):
    ACTIVE = "active"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


class UserRole(str, Enum):
    ADMIN = "admin"
    SITE_MANAGER = "site_manager"
    SUPERVISOR = "supervisor"
    AUDITOR = "auditor"


# ─── Violation ────────────────────────────────────────────────────────────────

class Violation(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str
    camera_id: str
    site_id: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    violation_type: HazardCategory
    description: str
    osha_code: str
    severity: Severity
    remediation: str
    confidence: float = Field(ge=0.0, le=1.0, default=0.9)
    evidence_image_url: Optional[str] = None
    annotated_image_url: Optional[str] = None
    frame_number: Optional[int] = None
    timestamp_in_video: Optional[float] = None
    acknowledged: bool = False
    acknowledged_by: Optional[str] = None
    acknowledged_at: Optional[datetime] = None

    class Config:
        use_enum_values = True


class ViolationCreate(BaseModel):
    """Tool-callable payload sent by the Orchestrator agent."""
    violation_type: str
    description: str
    osha_code: str
    severity: str
    remediation: str
    confidence: float = 0.9


# ─── Alert ───────────────────────────────────────────────────────────────────

class Alert(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    violation_id: str
    session_id: str
    camera_id: str
    site_id: str
    title: str
    message: str
    severity: Severity
    status: AlertStatus = AlertStatus.ACTIVE
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        use_enum_values = True


# ─── Camera ───────────────────────────────────────────────────────────────────

class Camera(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    site_id: str
    name: str
    mode: CameraMode
    stream_url: Optional[str] = None     # RTSP/HLS URL for IP cameras
    status: CameraStatus = CameraStatus.OFFLINE
    location_description: str = ""
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_seen: Optional[datetime] = None
    current_session_id: Optional[str] = None
    thumbnail_url: Optional[str] = None

    class Config:
        use_enum_values = True


class CameraCreate(BaseModel):
    site_id: str
    name: str
    mode: CameraMode
    stream_url: Optional[str] = None
    location_description: str = ""


class CameraUpdate(BaseModel):
    name: Optional[str] = None
    stream_url: Optional[str] = None
    is_active: Optional[bool] = None
    location_description: Optional[str] = None


# ─── Session ─────────────────────────────────────────────────────────────────

class Session(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    camera_id: str
    site_id: str
    mode: CameraMode
    status: SessionStatus = SessionStatus.ACTIVE
    started_at: datetime = Field(default_factory=datetime.utcnow)
    ended_at: Optional[datetime] = None
    violation_count: int = 0
    frame_count: int = 0
    supervisor_id: Optional[str] = None
    language: str = "en"

    class Config:
        use_enum_values = True


# ─── Report ──────────────────────────────────────────────────────────────────

class ReportSummary(BaseModel):
    total_violations: int
    critical_count: int
    high_count: int
    medium_count: int
    low_count: int
    compliance_score: float   # 0-100
    top_hazard_categories: list[str]
    osha_standards_violated: list[str]


class InspectionReport(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str
    site_id: str
    camera_id: str
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    title: str
    executive_summary: str
    violations: list[Violation]
    summary: ReportSummary
    recommendations: list[str]
    pdf_url: Optional[str] = None
    inspector_name: Optional[str] = None


# ─── Site ────────────────────────────────────────────────────────────────────

class Site(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    address: str
    manager_ids: list[str] = []
    camera_ids: list[str] = []
    risk_score: float = 0.0     # 0-100, updated periodically
    created_at: datetime = Field(default_factory=datetime.utcnow)
    is_active: bool = True


# ─── WebSocket Messages ───────────────────────────────────────────────────────

class WSMessageType(str, Enum):
    # Client → Server
    AUDIO_CHUNK = "audio_chunk"       # Raw PCM audio bytes (base64)
    VIDEO_FRAME = "video_frame"       # JPEG frame (base64)
    TEXT_INPUT = "text_input"         # Text message from supervisor
    START_SESSION = "start_session"   # Begin a session
    END_SESSION = "end_session"       # End a session
    PING = "ping"

    # Server → Client
    AUDIO_RESPONSE = "audio_response" # AI voice PCM bytes (base64)
    TEXT_RESPONSE = "text_response"   # AI text response
    VIOLATION_DETECTED = "violation_detected"
    ALERT = "alert"
    SESSION_STARTED = "session_started"
    SESSION_ENDED = "session_ended"
    STATUS = "status"
    PONG = "pong"
    ERROR = "error"


class WSMessage(BaseModel):
    type: WSMessageType
    data: Any = None
    session_id: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        use_enum_values = True


class StartSessionRequest(BaseModel):
    camera_id: str
    site_id: str
    mode: CameraMode
    language: str = "en"
    supervisor_id: Optional[str] = None


# ─── API Responses ────────────────────────────────────────────────────────────

class SiteRiskScore(BaseModel):
    site_id: str
    site_name: str
    risk_score: float
    active_cameras: int
    active_alerts: int
    violations_today: int
    updated_at: datetime


class AnalyticsSummary(BaseModel):
    period_days: int
    total_violations: int
    by_severity: dict[str, int]
    by_category: dict[str, int]
    by_site: dict[str, int]
    compliance_trend: list[dict[str, Any]]   # [{date, score}]
    top_violations: list[dict[str, Any]]


class HealthCheck(BaseModel):
    status: str = "healthy"
    version: str = "1.0.0"
    services: dict[str, str] = {}
