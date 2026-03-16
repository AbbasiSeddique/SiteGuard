"""FastAPI application entry point for SiteGuard AI backend."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from dotenv import load_dotenv
load_dotenv()  # Load .env into os.environ for GCP clients

from agents.orchestrator import SafetyOrchestrator
from agents.aria_agent import ARIAAgent
from api.routes import router
from api.websocket import manager_ws_handler, supervisor_ws_handler, connection_manager
from api.agent_ws import aria_ws_handler
from core.config import get_settings
from models.schemas import HealthCheck
from services.bigquery_service import BigQueryService
from services.firestore_service import FirestoreService
from services.storage_service import StorageService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)
settings = get_settings()

# ─── Global service instances ─────────────────────────────────────────────────

orchestrator = SafetyOrchestrator()
firestore_svc = orchestrator.firestore
bigquery_svc = orchestrator.bigquery
storage_svc = orchestrator.storage

# ARIA — ADK LlmAgent for conversational site intelligence
aria_agent = ARIAAgent(firestore_svc=firestore_svc, bigquery_svc=bigquery_svc)


# ─── Lifespan ────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 SiteGuard AI backend starting up...")

    # Ensure BigQuery dataset/tables exist
    try:
        bigquery_svc.ensure_dataset_and_tables()
        logger.info("✅ BigQuery dataset verified")
    except Exception as e:
        logger.warning(f"BigQuery setup warning (non-fatal): {e}")

    # Start autonomous monitoring for all active IP cameras
    try:
        await orchestrator.start_all_ip_cameras()
        logger.info("✅ IP camera monitoring started")
    except Exception as e:
        logger.warning(f"IP camera startup warning (non-fatal): {e}")

    logger.info("✅ SiteGuard AI ready")
    yield

    logger.info("🛑 SiteGuard AI shutting down...")
    await orchestrator.shutdown()


# ─── App ─────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="SiteGuard AI",
    description="Enterprise Field Safety & Compliance Agent — Powered by Gemini 3.1 Pro",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,          # do not allow cookies/credentials cross-origin
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Request-ID"],
)

app.include_router(router, prefix="/api/v1")


# ─── Health Check ─────────────────────────────────────────────────────────────

@app.get("/health", response_model=HealthCheck, tags=["Health"])
async def health():
    return HealthCheck(
        status="healthy",
        version="1.0.0",
        services={
            "active_supervisor_sessions": str(orchestrator.live_api.active_count),
            "active_ip_cameras": str(orchestrator.camera_mgr.active_count),
            "ws_supervisors": str(connection_manager.supervisor_count),
            "ws_managers": str(connection_manager.manager_count),
        },
    )


# ─── WebSocket Endpoints ──────────────────────────────────────────────────────

@app.websocket("/ws/supervisor")
async def supervisor_websocket(
    websocket: WebSocket,
    camera_id: str = Query(...),
    site_id: str = Query(...),
    language: str = Query(default="en"),
):
    """
    WebSocket for supervisor phone mode.
    Streams audio+video frames to Gemini Live API, returns AI voice + alerts.
    
    Query params:
      camera_id: Firestore camera document ID
      site_id:   Firestore site document ID
      language:  ISO language code (en, es, fr, ar, zh, hi, ...)
    """
    await supervisor_ws_handler(
        websocket=websocket,
        orchestrator=orchestrator,
        camera_id=camera_id,
        site_id=site_id,
        language=language,
    )


@app.websocket("/ws/dashboard")
async def manager_dashboard_websocket(
    websocket: WebSocket,
    site_id: str = Query(...),
):
    """
    WebSocket for manager dashboard.
    Receives real-time alerts and violation events for a site.
    """
    await manager_ws_handler(
        websocket=websocket,
        site_id=site_id,
        firestore_svc=firestore_svc,
    )


@app.websocket("/ws/aria")
async def aria_websocket(
    websocket: WebSocket,
    site_id: str = Query(default="demo-site"),
    language: str = Query(default="en"),
):
    """
    WebSocket for ARIA — Automated Risk Intelligence Assistant.
    Supports voice (Gemini Live API) and text (ADK Runner) interaction modes.
    ARIA has real-time grounding tools: site status, violations, OSHA lookup, cameras, trends.

    Query params:
      site_id:  Default site to monitor (can be overridden per message)
      language: ISO language code for voice responses
    """
    await aria_ws_handler(
        websocket=websocket,
        aria_agent=aria_agent,
        firestore_svc=firestore_svc,
        bigquery_svc=bigquery_svc,
        site_id=site_id,
        language=language,
    )


@app.post("/api/v1/aria/report-query", tags=["ARIA"])
async def aria_report_query(body: dict):
    """
    REST endpoint for ARIA to answer questions about a generated compliance report.
    The full report JSON is passed in the request body and injected as context so
    ARIA can answer natural-language questions without hallucinating.

    Body:
      {
        "report":     { ...ReportPayload... },   // full report JSON from analyze-sync
        "message":    "What are the critical findings?",
        "session_id": "report-abc123",           // stable ID for multi-turn within same report
        "user_id":    "anonymous"
      }
    Returns: { "response": "...", "tool_calls": [...], "session_id": "..." }
    """
    from tools.adk_tools import _REPORT_STORE

    report = body.get("report")
    message = body.get("message", "").strip()
    session_id = body.get("session_id", f"report-{id(report)}")
    user_id = body.get("user_id", "anonymous")

    if not message:
        return {"response": "Please provide a question.", "tool_calls": []}
    if not report:
        return {"response": "No report provided.", "tool_calls": []}

    # Store report so ADK tools can access it by session_id
    _REPORT_STORE[session_id] = report

    # Build compact context string from the report data
    violations = report.get("violations", [])
    critical_count = sum(1 for v in violations if v.get("severity") == "critical")
    high_count = sum(1 for v in violations if v.get("severity") == "high")

    vio_lines = "\n".join(
        f"  [{v.get('severity', '').upper()}] {v.get('violation_type', '')} — "
        f"{v.get('osha_code', 'N/A')} — {v.get('description', '')[:100]}"
        f"\n    Remediation: {v.get('remediation', '')}"
        for v in violations[:20]
    )

    context_str = f"""Report: {report.get('title', 'Compliance Report')}
Compliance Score: {report.get('compliance_score', 0)}/100
Session: {report.get('session_id', session_id)}  Site: {report.get('site_id', 'N/A')}
Generated: {report.get('generated_at', 'N/A')}
Severity summary: {critical_count} critical, {high_count} high, {len(violations)} total violations

Executive Summary:
{report.get('executive_summary', 'N/A')}

Critical Findings ({len(report.get('critical_findings', []))}):
{chr(10).join(f'  {i+1}. {f}' for i, f in enumerate(report.get('critical_findings', [])))}

Violations ({len(violations)} total):
{vio_lines}

Corrective Actions:
{chr(10).join(f'  {i+1}. {a}' for i, a in enumerate(report.get('corrective_actions', [])))}

OSHA Standards Referenced:
{chr(10).join(f'  · {s}' for s in report.get('osha_annex', []))}"""

    try:
        result = await aria_agent.query_with_context(
            user_id=user_id,
            session_id=session_id,
            context_str=context_str,
            message=message,
        )
        return result
    except Exception as e:
        logger.error(f"ARIA report query error: {e}")
        return {"response": f"ARIA is unavailable: {str(e)}", "tool_calls": [], "error": True}


@app.post("/api/v1/aria/query", tags=["ARIA"])
async def aria_text_query(body: dict):
    """
    REST endpoint for ARIA text queries (for inline chat panels).
    Uses ADK Runner with InMemorySessionService for conversation state.

    Body: { "site_id": "...", "message": "...", "user_id": "..." }
    Returns: { "response": "...", "tool_calls": [...], "session_id": "..." }
    """
    site_id = body.get("site_id", "demo-site")
    message = body.get("message", "").strip()
    user_id = body.get("user_id", "anonymous")
    if not message:
        return {"response": "Please provide a message.", "tool_calls": []}
    try:
        result = await aria_agent.query(user_id=user_id, site_id=site_id, message=message)
        return result
    except Exception as e:
        logger.error(f"ARIA REST query error: {e}")
        return {"response": f"ARIA is unavailable: {str(e)}", "tool_calls": [], "error": True}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", 8080)),
        reload=os.getenv("ENVIRONMENT", "production") == "development",
    )
