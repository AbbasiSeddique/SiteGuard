"""ADK tools — callable functions used by the Safety Orchestrator agent."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Optional

from models.schemas import Alert, Severity, Violation, ViolationCreate

logger = logging.getLogger(__name__)

# ─── Shared report context store (populated by /api/v1/aria/report-query) ─────
# Maps session_id → full report JSON dict so ADK tools can read report data.
_REPORT_STORE: dict[str, dict] = {}


def build_tools(firestore_svc, bigquery_svc, storage_svc):
    """
    Build and return all ADK FunctionTools, injecting service dependencies.
    """

    # ─── Log Violation ────────────────────────────────────────────────────────

    async def log_violation(
        session_id: str,
        camera_id: str,
        site_id: str,
        violation_type: str,
        description: str,
        osha_code: str,
        severity: str,
        remediation: str,
        confidence: float = 0.9,
        evidence_frame_b64: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Log a detected safety violation to Firestore and BigQuery.
        Also creates an Alert for the manager dashboard.
        Returns the violation ID and status.
        """
        violation = Violation(
            id=str(uuid.uuid4()),
            session_id=session_id,
            camera_id=camera_id,
            site_id=site_id,
            timestamp=datetime.utcnow(),
            violation_type=violation_type,
            description=description,
            osha_code=osha_code,
            severity=severity,
            remediation=remediation,
            confidence=confidence,
        )

        # Upload evidence frame if provided
        if evidence_frame_b64:
            try:
                url = await storage_svc.upload_evidence_frame_base64(
                    session_id=session_id,
                    camera_id=camera_id,
                    violation_id=violation.id,
                    frame_b64=evidence_frame_b64,
                )
                violation.evidence_image_url = url
            except Exception as e:
                logger.warning(f"Evidence upload failed: {e}")

        # Persist to Firestore
        await firestore_svc.save_violation(violation)

        # Log to BigQuery for analytics
        await bigquery_svc.log_violation(violation)

        # Create manager dashboard alert for high/critical
        if severity in ("critical", "high"):
            alert = Alert(
                violation_id=violation.id,
                session_id=session_id,
                camera_id=camera_id,
                site_id=site_id,
                title=f"{'🚨 CRITICAL' if severity == 'critical' else '⚠️ HIGH'}: {osha_code}",
                message=f"{description} — {remediation}",
                severity=Severity(severity),
            )
            await firestore_svc.create_alert(alert)

        logger.info(f"Violation logged: {violation.id} [{severity}] {osha_code}")
        return {"violation_id": violation.id, "logged": True, "severity": severity}

    # ─── Get Session Violations ───────────────────────────────────────────────

    async def get_session_violations(session_id: str) -> dict[str, Any]:
        """Get all violations for the current session (for report generation)."""
        violations = await firestore_svc.get_violations_for_session(session_id)
        return {
            "violations": [v.model_dump(mode="json") for v in violations],
            "count": len(violations),
        }

    # ─── Get Site Analytics ───────────────────────────────────────────────────

    async def get_site_risk_score(site_id: str) -> dict[str, Any]:
        """Get the current risk score for a site based on recent violations."""
        score = await bigquery_svc.get_site_risk_score(site_id)
        return {"site_id": site_id, "risk_score": score}

    # ─── Upload Evidence ─────────────────────────────────────────────────────

    async def upload_evidence(
        session_id: str,
        camera_id: str,
        violation_id: str,
        frame_b64: str,
        annotated: bool = False,
    ) -> dict[str, str]:
        """Upload an evidence frame or annotated snapshot to Cloud Storage."""
        url = await storage_svc.upload_evidence_frame_base64(
            session_id=session_id,
            camera_id=camera_id,
            violation_id=violation_id,
            frame_b64=frame_b64,
            annotated=annotated,
        )
        return {"url": url}

    # ─── Acknowledge Alert ────────────────────────────────────────────────────

    async def acknowledge_alert(alert_id: str, user_id: str) -> dict[str, bool]:
        """Acknowledge an active alert (called from manager dashboard)."""
        await firestore_svc.resolve_alert(alert_id)
        return {"acknowledged": True}

    return [
        log_violation,
        get_session_violations,
        get_site_risk_score,
        upload_evidence,
        acknowledge_alert,
    ]


# ─── ARIA Grounding Tools ─────────────────────────────────────────────────────

def build_aria_tools(firestore_svc, bigquery_svc) -> list:
    """
    Build read-only grounding FunctionTools for the ARIA agent.
    These tools give ARIA real-time access to site data without hallucination.
    """
    from core.safety_standards import OSHA_STANDARDS

    # ── get_live_site_status ──────────────────────────────────────────────────

    async def get_live_site_status(site_id: str) -> dict[str, Any]:
        """
        Get the real-time safety status of a construction site.
        Returns active session count, open alert count, recent violation summary,
        current risk score, and overall site health assessment.
        Use this as the first tool when a user asks about site conditions.
        """
        try:
            alerts = await firestore_svc.get_active_alerts(site_id)
            sessions = await firestore_svc.get_recent_sessions(site_id, limit=5)
            violations = await firestore_svc.get_recent_violations(site_id, limit=20)
            risk_score = await bigquery_svc.get_site_risk_score(site_id)
        except Exception as e:
            logger.warning(f"ARIA get_live_site_status error: {e}")
            return {"error": str(e), "site_id": site_id}

        critical = sum(1 for v in violations if getattr(v, "severity", "") == "critical")
        high = sum(1 for v in violations if getattr(v, "severity", "") == "high")
        medium = sum(1 for v in violations if getattr(v, "severity", "") == "medium")
        low = sum(1 for v in violations if getattr(v, "severity", "") == "low")

        active_sessions = [s for s in sessions if getattr(s, "status", "") == "active"]

        if risk_score >= 75:
            health = "HIGH RISK — immediate intervention required"
        elif risk_score >= 50:
            health = "ELEVATED RISK — monitor closely"
        else:
            health = "Acceptable risk level — standard precautions apply"

        return {
            "site_id": site_id,
            "risk_score": risk_score,
            "health_assessment": health,
            "active_sessions": len(active_sessions),
            "open_alerts": len(alerts),
            "violations_last_24h": {
                "total": len(violations),
                "critical": critical,
                "high": high,
                "medium": medium,
                "low": low,
            },
            "stop_work_required": critical > 0,
            "alerts_summary": [
                {"title": a.title, "severity": a.severity, "created_at": str(getattr(a, "created_at", ""))}
                for a in alerts[:3]
            ],
        }

    # ── get_recent_violations ─────────────────────────────────────────────────

    async def get_recent_violations(site_id: str, limit: int = 5) -> dict[str, Any]:
        """
        Get the most recent safety violations for a site with full details.
        Returns violation type, description, OSHA code, severity, remediation,
        confidence score, and timestamp. Use when user asks what was detected.
        """
        try:
            violations = await firestore_svc.get_recent_violations(site_id, limit=limit)
        except Exception as e:
            logger.warning(f"ARIA get_recent_violations error: {e}")
            return {"error": str(e), "violations": []}

        return {
            "site_id": site_id,
            "count": len(violations),
            "violations": [
                {
                    "id": str(getattr(v, "id", "")),
                    "violation_type": getattr(v, "violation_type", ""),
                    "description": getattr(v, "description", ""),
                    "osha_code": getattr(v, "osha_code", ""),
                    "severity": getattr(v, "severity", ""),
                    "remediation": getattr(v, "remediation", ""),
                    "confidence": round(float(getattr(v, "confidence", 0)) * 100, 1),
                    "timestamp": str(getattr(v, "timestamp", "")),
                    "camera_id": getattr(v, "camera_id", ""),
                }
                for v in violations
            ],
        }

    # ── lookup_osha_standard ──────────────────────────────────────────────────

    async def lookup_osha_standard(query: str) -> dict[str, Any]:
        """
        Look up precise OSHA standard information by code or keyword.
        Use this when user asks about a specific regulation, what a code means,
        or how to comply with a particular standard. Returns title, description,
        severity level, and required remediation. This is grounded in the internal
        OSHA compliance database — never hallucinate standard details.
        """
        query_lower = query.lower()
        matches = []
        for std in OSHA_STANDARDS:
            if (query_lower in std.code.lower() or
                    query_lower in std.title.lower() or
                    any(query_lower in kw.lower() for kw in std.keywords)):
                matches.append({
                    "code": std.code,
                    "title": std.title,
                    "description": std.description,
                    "hazard_category": std.hazard_category.value,
                    "severity": std.severity.value,
                    "remediation": std.remediation,
                    "keywords": std.keywords[:5],
                })
        if not matches:
            return {
                "query": query,
                "found": False,
                "message": f"No OSHA standard found matching '{query}'. Try a different code or keyword.",
            }
        return {
            "query": query,
            "found": True,
            "count": len(matches),
            "standards": matches[:3],  # Return top 3 matches
        }

    # ── get_camera_status ─────────────────────────────────────────────────────

    async def get_camera_status(site_id: str) -> dict[str, Any]:
        """
        Get the status of all monitoring cameras at a site.
        Returns camera IDs, current status (online/offline/monitoring/error),
        mode (phone/ip_camera), and active session info.
        Use when user asks about coverage or camera health.
        """
        try:
            cameras = await firestore_svc.get_cameras_for_site(site_id)
        except Exception as e:
            logger.warning(f"ARIA get_camera_status error: {e}")
            return {"error": str(e), "cameras": []}

        monitoring = [c for c in cameras if getattr(c, "status", "") == "monitoring"]
        online = [c for c in cameras if getattr(c, "status", "") == "online"]
        offline = [c for c in cameras if getattr(c, "status", "") in ("offline", "error")]

        return {
            "site_id": site_id,
            "total_cameras": len(cameras),
            "actively_monitoring": len(monitoring),
            "online_idle": len(online),
            "offline_or_error": len(offline),
            "coverage_assessment": (
                "Full coverage" if len(monitoring) == len(cameras) and len(cameras) > 0
                else f"{len(monitoring)}/{len(cameras)} cameras active — gaps in coverage" if cameras
                else "No cameras configured"
            ),
            "cameras": [
                {
                    "id": getattr(c, "id", ""),
                    "name": getattr(c, "name", ""),
                    "status": getattr(c, "status", ""),
                    "mode": getattr(c, "mode", ""),
                    "location": getattr(c, "location_description", ""),
                    "session_id": getattr(c, "current_session_id", None),
                }
                for c in cameras
            ],
        }

    # ── get_violation_trend ───────────────────────────────────────────────────

    async def get_violation_trend(site_id: str, days: int = 7) -> dict[str, Any]:
        """
        Get violation trend data over the past N days for a site.
        Returns daily counts, top violation categories, and trend direction.
        Use when user asks if things are getting better or worse, or for weekly summaries.
        """
        try:
            summary = await bigquery_svc.get_violations_summary(site_id, days=days)
            risk_score = await bigquery_svc.get_site_risk_score(site_id)
        except Exception as e:
            logger.warning(f"ARIA get_violation_trend error: {e}")
            return {"error": str(e)}

        return {
            "site_id": site_id,
            "period_days": days,
            "current_risk_score": risk_score,
            "summary": summary,
        }

    # ── get_report_analysis ───────────────────────────────────────────────────

    async def get_report_analysis(session_id: str) -> dict[str, Any]:
        """
        Retrieve the full compliance analysis report for the current report session.
        Returns violations list, compliance score, executive summary, critical findings,
        corrective actions, and OSHA/NEBOSH references.
        Use this when the user asks about findings, violations, scores, or actions
        from an uploaded recording report.
        """
        report = _REPORT_STORE.get(session_id)
        if not report:
            return {
                "found": False,
                "error": "No report loaded for this session. Submit the report first.",
            }
        violations = report.get("violations", [])
        return {
            "found": True,
            "title": report.get("title", ""),
            "compliance_score": report.get("compliance_score", 0),
            "executive_summary": report.get("executive_summary", ""),
            "critical_findings": report.get("critical_findings", []),
            "corrective_actions": report.get("corrective_actions", []),
            "violation_count": len(violations),
            "violations": violations,
            "osha_annex": report.get("osha_annex", []),
            "nebosh_annex": report.get("nebosh_annex", []),
        }

    return [
        get_live_site_status,
        get_recent_violations,
        lookup_osha_standard,
        get_camera_status,
        get_violation_trend,
        get_report_analysis,
    ]


# ─── ARIA Live API Tool Declarations (for Gemini Live API voice sessions) ────

ARIA_LIVE_TOOL_DECLARATIONS = [
    {
        "name": "get_live_site_status",
        "description": "Get real-time safety status of a site: risk score, violations, alerts, active sessions",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "site_id": {"type": "STRING", "description": "The site identifier"},
            },
            "required": ["site_id"],
        },
    },
    {
        "name": "get_recent_violations",
        "description": "Get the most recent safety violations detected at a site with full details",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "site_id": {"type": "STRING", "description": "The site identifier"},
                "limit": {"type": "INTEGER", "description": "Maximum number of violations to return (default 5)"},
            },
            "required": ["site_id"],
        },
    },
    {
        "name": "lookup_osha_standard",
        "description": "Look up OSHA standard details by code (e.g. '1926.501') or keyword (e.g. 'fall protection')",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {"type": "STRING", "description": "OSHA code or keyword to look up"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_camera_status",
        "description": "Get current status of all monitoring cameras at a site",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "site_id": {"type": "STRING", "description": "The site identifier"},
            },
            "required": ["site_id"],
        },
    },
    {
        "name": "get_violation_trend",
        "description": "Get violation trend over past N days to assess if site safety is improving or worsening",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "site_id": {"type": "STRING", "description": "The site identifier"},
                "days": {"type": "INTEGER", "description": "Number of days to analyse (default 7)"},
            },
            "required": ["site_id"],
        },
    },
    {
        "name": "get_report_analysis",
        "description": "Retrieve the full compliance analysis report for the current report session including violations, compliance score, critical findings, and corrective actions",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "session_id": {"type": "STRING", "description": "The report session ID to look up"},
            },
            "required": ["session_id"],
        },
    },
]
