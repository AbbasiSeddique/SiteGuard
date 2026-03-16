"""Firestore service — session, violation, alert, camera, and site CRUD."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

from google.cloud import firestore

from core.config import get_settings
from models.schemas import (
    Alert, AlertStatus, Camera, CameraCreate, CameraUpdate,
    Session, Site, Violation
)

logger = logging.getLogger(__name__)
settings = get_settings()


class FirestoreService:
    def __init__(self):
        self.db = firestore.AsyncClient(project=settings.gcp_project_id)

    # ─── Sessions ─────────────────────────────────────────────────────────────

    async def create_session(self, session: Session) -> Session:
        doc_ref = self.db.collection(settings.firestore_collection_sessions).document(session.id)
        await doc_ref.set(session.model_dump(mode="json"))
        logger.info(f"Session created: {session.id}")
        return session

    async def get_session(self, session_id: str) -> Optional[Session]:
        doc = await self.db.collection(settings.firestore_collection_sessions).document(session_id).get()
        if doc.exists:
            return Session(**doc.to_dict())
        return None

    async def update_session(self, session_id: str, updates: dict[str, Any]) -> None:
        updates["updated_at"] = datetime.utcnow().isoformat()
        await self.db.collection(settings.firestore_collection_sessions).document(session_id).update(updates)

    async def end_session(self, session_id: str) -> None:
        await self.update_session(session_id, {
            "status": "completed",
            "ended_at": datetime.utcnow().isoformat(),
        })

    async def get_recent_sessions(self, site_id: str, limit: int = 20) -> list[Session]:
        """Return the most recent sessions for a site, newest first."""
        query = (
            self.db.collection(settings.firestore_collection_sessions)
            .where("site_id", "==", site_id)
            .limit(limit * 3)  # Over-fetch since we can't order without composite index
        )
        docs = query.stream()
        sessions = [Session(**doc.to_dict()) async for doc in docs]
        sessions.sort(key=lambda s: getattr(s, "started_at", datetime.min), reverse=True)
        return sessions[:limit]

    # ─── Violations ───────────────────────────────────────────────────────────

    async def save_violation(self, violation: Violation) -> Violation:
        doc_ref = self.db.collection(settings.firestore_collection_violations).document(violation.id)
        await doc_ref.set(violation.model_dump(mode="json"))

        # Increment violation count on session
        session_ref = self.db.collection(settings.firestore_collection_sessions).document(violation.session_id)
        await session_ref.update({"violation_count": firestore.Increment(1)})

        logger.info(f"Violation saved: {violation.id} [{violation.severity}] {violation.osha_code}")
        return violation

    async def get_violations_for_session(self, session_id: str) -> list[Violation]:
        query = self.db.collection(settings.firestore_collection_violations).where("session_id", "==", session_id)
        docs = query.stream()
        return [Violation(**doc.to_dict()) async for doc in docs]

    async def get_recent_violations(self, site_id: str, limit: int = 50) -> list[Violation]:
        query = (
            self.db.collection(settings.firestore_collection_violations)
            .where("site_id", "==", site_id)
            .limit(limit * 2)
        )
        docs = query.stream()
        violations = [Violation(**doc.to_dict()) async for doc in docs]
        violations.sort(key=lambda v: getattr(v, "timestamp", datetime.min), reverse=True)
        return violations[:limit]

    async def acknowledge_violation(self, violation_id: str, user_id: str) -> None:
        await self.db.collection(settings.firestore_collection_violations).document(violation_id).update({
            "acknowledged": True,
            "acknowledged_by": user_id,
            "acknowledged_at": datetime.utcnow().isoformat(),
        })

    # ─── Alerts ───────────────────────────────────────────────────────────────

    async def create_alert(self, alert: Alert) -> Alert:
        await self.db.collection(settings.firestore_collection_alerts).document(alert.id).set(
            alert.model_dump(mode="json")
        )
        logger.info(f"Alert created: {alert.id} [{alert.severity}]")
        return alert

    async def get_active_alerts(self, site_id: str) -> list[Alert]:
        query = (
            self.db.collection(settings.firestore_collection_alerts)
            .where("site_id", "==", site_id)
            .where("status", "==", AlertStatus.ACTIVE.value)
        )
        docs = query.stream()
        alerts = [Alert(**doc.to_dict()) async for doc in docs]
        # Sort in Python to avoid requiring a composite Firestore index
        alerts.sort(key=lambda a: getattr(a, "created_at", datetime.min), reverse=True)
        return alerts

    async def resolve_alert(self, alert_id: str) -> None:
        await self.db.collection(settings.firestore_collection_alerts).document(alert_id).update({
            "status": AlertStatus.RESOLVED.value,
            "updated_at": datetime.utcnow().isoformat(),
        })

    def listen_to_alerts(self, site_id: str, callback):
        """Set up real-time Firestore listener for the manager dashboard."""
        query = (
            self.db.collection(settings.firestore_collection_alerts)
            .where("site_id", "==", site_id)
            .where("status", "==", AlertStatus.ACTIVE.value)
        )
        return query.on_snapshot(callback)

    # ─── Cameras ──────────────────────────────────────────────────────────────

    async def create_camera(self, camera: Camera) -> Camera:
        await self.db.collection(settings.firestore_collection_cameras).document(camera.id).set(
            camera.model_dump(mode="json")
        )
        return camera

    async def get_camera(self, camera_id: str) -> Optional[Camera]:
        doc = await self.db.collection(settings.firestore_collection_cameras).document(camera_id).get()
        if doc.exists:
            return Camera(**doc.to_dict())
        return None

    async def get_cameras_for_site(self, site_id: str) -> list[Camera]:
        query = self.db.collection(settings.firestore_collection_cameras).where("site_id", "==", site_id)
        docs = query.stream()
        return [Camera(**doc.to_dict()) async for doc in docs]

    async def update_camera(self, camera_id: str, updates: dict[str, Any]) -> None:
        await self.db.collection(settings.firestore_collection_cameras).document(camera_id).update(updates)

    async def update_camera_status(self, camera_id: str, status: str, session_id: Optional[str] = None) -> None:
        updates: dict[str, Any] = {
            "status": status,
            "last_seen": datetime.utcnow().isoformat(),
        }
        if session_id is not None:
            updates["current_session_id"] = session_id
        await self.update_camera(camera_id, updates)

    async def get_all_ip_cameras(self) -> list[Camera]:
        """Return all active IP cameras that should be autonomously monitored."""
        query = (
            self.db.collection(settings.firestore_collection_cameras)
            .where("mode", "==", "ip_camera")
            .where("is_active", "==", True)
        )
        docs = query.stream()
        return [Camera(**doc.to_dict()) async for doc in docs]

    # ─── Sites ────────────────────────────────────────────────────────────────

    async def get_site(self, site_id: str) -> Optional[Site]:
        doc = await self.db.collection("sites").document(site_id).get()
        if doc.exists:
            return Site(**doc.to_dict())
        return None

    async def update_site_risk_score(self, site_id: str, score: float) -> None:
        await self.db.collection("sites").document(site_id).update({
            "risk_score": score,
            "risk_score_updated_at": datetime.utcnow().isoformat(),
        })

    async def get_all_sites(self) -> list[Site]:
        docs = self.db.collection("sites").stream()
        return [Site(**doc.to_dict()) async for doc in docs]

    async def create_site(self, site: Site) -> Site:
        await self.db.collection("sites").document(site.id).set(site.model_dump(mode="json"))
        logger.info(f"Site created: {site.id} — {site.name}")
        return site

    async def update_site(self, site_id: str, updates: dict[str, Any]) -> None:
        await self.db.collection("sites").document(site_id).update(updates)
