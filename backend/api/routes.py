"""REST API routes — cameras, reports, analytics, recordings, sites."""

from __future__ import annotations

import logging
import uuid
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel as PydanticBaseModel

from models.schemas import (
    Camera, CameraCreate, CameraMode, CameraUpdate,
    InspectionReport, Site
)
from services.bigquery_service import BigQueryService
from services.firestore_service import FirestoreService
from services.storage_service import StorageService
from api.vision_stream import vision_router

logger = logging.getLogger(__name__)

router = APIRouter()
router.include_router(vision_router)


# ─── Dependency injection placeholders (injected in main.py) ──────────────────

def get_orchestrator():
    from main import orchestrator
    return orchestrator

def get_firestore():
    from main import firestore_svc
    return firestore_svc

def get_bigquery():
    from main import bigquery_svc
    return bigquery_svc

def get_storage():
    from main import storage_svc
    return storage_svc


# ─── Sites ────────────────────────────────────────────────────────────────────

@router.get("/sites", tags=["Sites"])
async def list_sites(firestore: FirestoreService = Depends(get_firestore)):
    sites = await firestore.get_all_sites()
    return {"sites": [s.model_dump(mode="json") for s in sites]}


class SiteCreateRequest(PydanticBaseModel):
    name: str
    address: str = ""
    manager_ids: list[str] = []

@router.post("/sites", tags=["Sites"])
async def create_site(
    req: SiteCreateRequest,
    firestore: FirestoreService = Depends(get_firestore),
):
    import uuid
    from datetime import datetime
    site = Site(
        id=str(uuid.uuid4()),
        name=req.name,
        address=req.address,
        manager_ids=req.manager_ids,
        created_at=datetime.utcnow(),
    )
    await firestore.create_site(site)
    return {"site": site.model_dump(mode="json")}


@router.get("/sites/{site_id}/risk", tags=["Sites"])
async def get_site_risk(
    site_id: str,
    bigquery: BigQueryService = Depends(get_bigquery),
    firestore: FirestoreService = Depends(get_firestore),
):
    score = await bigquery.get_site_risk_score(site_id)
    alerts = await firestore.get_active_alerts(site_id)
    violations_today = await bigquery.get_violations_count_today(site_id)
    return {
        "site_id": site_id,
        "risk_score": round(score, 1),
        "active_alerts": len(alerts),
        "violations_today": violations_today,
    }


# ─── Cameras ──────────────────────────────────────────────────────────────────

@router.get("/sites/{site_id}/cameras", tags=["Cameras"])
async def list_cameras(
    site_id: str,
    firestore: FirestoreService = Depends(get_firestore),
):
    cameras = await firestore.get_cameras_for_site(site_id)
    return {"cameras": [c.model_dump(mode="json") for c in cameras]}


@router.post("/cameras", tags=["Cameras"])
async def create_camera(
    payload: CameraCreate,
    firestore: FirestoreService = Depends(get_firestore),
):
    camera = Camera(**payload.model_dump())
    await firestore.create_camera(camera)
    return camera.model_dump(mode="json")


@router.patch("/cameras/{camera_id}", tags=["Cameras"])
async def update_camera(
    camera_id: str,
    payload: CameraUpdate,
    firestore: FirestoreService = Depends(get_firestore),
):
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    await firestore.update_camera(camera_id, updates)
    return {"updated": True}


@router.post("/cameras/{camera_id}/start-autonomous", tags=["Cameras"])
async def start_autonomous_camera(
    camera_id: str,
    orchestrator=Depends(get_orchestrator),
    firestore: FirestoreService = Depends(get_firestore),
):
    """Start autonomous IP camera monitoring from the manager dashboard."""
    camera = await firestore.get_camera(camera_id)
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")
    if camera.mode != CameraMode.IP_CAMERA:
        raise HTTPException(status_code=400, detail="Camera is not an IP camera")

    session = await orchestrator.start_ip_camera_session(camera)
    return {"session_id": session.id, "status": "monitoring_started"}


@router.post("/cameras/{camera_id}/stop", tags=["Cameras"])
async def stop_camera(
    camera_id: str,
    firestore: FirestoreService = Depends(get_firestore),
    orchestrator=Depends(get_orchestrator),
):
    camera = await firestore.get_camera(camera_id)
    if camera and camera.current_session_id:
        await orchestrator.end_session(camera.current_session_id)
    return {"stopped": True}


# ─── Violations & Alerts ──────────────────────────────────────────────────────

@router.get("/sites/{site_id}/sessions", tags=["Sessions"])
async def get_recent_sessions(
    site_id: str,
    limit: int = 20,
    firestore: FirestoreService = Depends(get_firestore),
):
    sessions = await firestore.get_recent_sessions(site_id, limit=limit)
    return {"sessions": [s.model_dump(mode="json") for s in sessions]}


@router.get("/sites/{site_id}/violations", tags=["Violations"])
async def get_recent_violations(
    site_id: str,
    limit: int = 50,
    firestore: FirestoreService = Depends(get_firestore),
):
    violations = await firestore.get_recent_violations(site_id, limit=limit)
    return {"violations": [v.model_dump(mode="json") for v in violations]}


@router.get("/sites/{site_id}/alerts", tags=["Alerts"])
async def get_active_alerts(
    site_id: str,
    firestore: FirestoreService = Depends(get_firestore),
):
    alerts = await firestore.get_active_alerts(site_id)
    return {"alerts": [a.model_dump(mode="json") for a in alerts]}


@router.post("/alerts/{alert_id}/resolve", tags=["Alerts"])
async def resolve_alert(
    alert_id: str,
    firestore: FirestoreService = Depends(get_firestore),
):
    await firestore.resolve_alert(alert_id)
    return {"resolved": True}


# ─── Analytics ────────────────────────────────────────────────────────────────

@router.get("/sites/{site_id}/analytics", tags=["Analytics"])
async def get_analytics(
    site_id: str,
    days: int = 30,
    bigquery: BigQueryService = Depends(get_bigquery),
):
    summary = await bigquery.get_violations_summary(site_id, days=days)
    top = await bigquery.get_top_violations(site_id, days=days)
    return {"summary": summary, "top_violations": top}


# ─── Reports ──────────────────────────────────────────────────────────────────

@router.get("/sessions/{session_id}/report", tags=["Reports"])
async def get_session_report(
    session_id: str,
    orchestrator=Depends(get_orchestrator),
    firestore: FirestoreService = Depends(get_firestore),
):
    session = await firestore.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    violations = await firestore.get_violations_for_session(session_id)
    from services.vertex_ai_service import VertexAIService
    vertex = VertexAIService()
    report = await vertex.generate_report_text(
        violations_data=[v.model_dump(mode="json") for v in violations],
        session_metadata={
            "site_name": session.site_id,
            "date": session.started_at.strftime("%Y-%m-%d"),
            "camera_name": session.camera_id,
        },
    )
    return {"session_id": session_id, "report": report, "violations": [v.model_dump(mode="json") for v in violations]}


# ─── Recording Upload ─────────────────────────────────────────────────────────

@router.post("/recordings/upload-url", tags=["Recordings"])
async def get_upload_url(
    filename: str,
    storage: StorageService = Depends(get_storage),
):
    """Get a signed GCS URL to upload a recording directly."""
    signed_url, blob_name = await storage.generate_upload_url(filename)
    return {"upload_url": signed_url, "blob_name": blob_name}


@router.post("/recordings/upload", tags=["Recordings"])
async def upload_recording(
    file: UploadFile = File(...),
    storage: StorageService = Depends(get_storage),
):
    """Upload a recording through backend to avoid browser signed-URL/CORS failures."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="Missing file name")

    # Use streaming upload path to avoid loading large videos into memory.
    blob_name = await storage.upload_recording_fileobj(
        filename=file.filename or "recording.mp4",
        file_obj=file.file,
        content_type=file.content_type or "application/octet-stream",
    )
    return {"blob_name": blob_name}


@router.post("/recordings/analyze", tags=["Recordings"])
async def analyze_recording(
    blob_name: str,
    camera_id: str,
    site_id: str,
    background_tasks: BackgroundTasks,
    orchestrator=Depends(get_orchestrator),
):
    """Trigger background analysis of an uploaded recording."""
    task_id = str(uuid.uuid4())

    async def run():
        await orchestrator.analyze_recording(
            camera_id=camera_id,
            site_id=site_id,
            blob_name=blob_name,
        )

    background_tasks.add_task(run)
    return {"task_id": task_id, "status": "processing", "message": "Recording analysis started in background"}


@router.post("/recordings/analyze-sync", tags=["Recordings"])
async def analyze_recording_sync(
    blob_name: str,
    camera_id: str,
    site_id: str,
    orchestrator=Depends(get_orchestrator),
):
    """Run uploaded recording analysis and return full report payload synchronously."""
    try:
        result = await orchestrator.analyze_recording(
            camera_id=camera_id,
            site_id=site_id,
            blob_name=blob_name,
        )
        return result
    except Exception as e:
        logger.exception(f"analyze-sync failed: {e}")
        raise HTTPException(status_code=500, detail="Analysis failed. See server logs for details.")
