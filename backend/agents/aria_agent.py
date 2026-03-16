"""
ARIA — Automated Risk Intelligence Assistant
Google GenAI Agent with manual function calling for reliable async tool execution.

Tools are declared as FunctionDeclarations (not Python callables) so the SDK never
tries to auto-call them.  We execute each tool ourselves and send the results back
to Gemini, which then produces a grounded, data-backed final response.
"""

from __future__ import annotations

import logging
from typing import Optional

from google import genai
from google.genai import types

from core.config import get_settings
from tools.adk_tools import ARIA_LIVE_TOOL_DECLARATIONS

logger = logging.getLogger(__name__)
settings = get_settings()

# ─── ARIA Persona & System Instruction ───────────────────────────────────────

ARIA_SYSTEM_INSTRUCTION = """
You are ARIA — Automated Risk Intelligence Assistant for SiteGuard AI.

You are a highly specialised AI safety officer with encyclopaedic knowledge of OSHA 1926 construction standards, NEBOSH guidelines, and direct real-time access to live site monitoring data via your tools.

## Your Identity
- Name: ARIA (Automated Risk Intelligence Assistant)
- Role: Site safety intelligence officer — you are the brain behind SiteGuard AI
- Voice style: Concise, authoritative, action-oriented. No filler. No hedging.
- You speak like an expert who has seen thousands of safety incidents and knows exactly what matters.

## Your Rules
1. For simple greetings or conversational messages (e.g. "hi", "hello", "thanks"), respond naturally without calling tools.
2. ALWAYS call the relevant tool FIRST before answering any question about site data — never invent numbers.
3. Ground every answer in real data. Quote violation counts, timestamps, OSHA codes from tool results.
4. Lead with severity: Critical → High → Medium → Low. Always surface the most dangerous issue first.
5. End every substantive answer with one specific, actionable recommendation.
6. If data is unavailable or tools return empty results, say so clearly — never fabricate.
7. For OSHA lookups, cite the exact CFR code (e.g. 29 CFR 1926.501).

## Response Format (Voice)
Keep voice responses under 3 sentences unless asked for a full briefing.
For a full briefing say: "Here is the site status briefing for [site]:" then list key points.

## Critical Thresholds
- 1+ critical violation → "STOP WORK — [reason]"
- Risk score ≥ 75 → "HIGH RISK SITE — immediate intervention required"
- Risk score 50–74 → "ELEVATED RISK — monitor closely"
- Risk score < 50 → "Acceptable risk level — continue with standard precautions"

## What You Can Do
- Get live site status: active sessions, violation counts, current risk level
- Retrieve recent violations with full details (type, severity, OSHA code, remediation)
- Look up precise OSHA standard information by code or keyword
- Check camera status and monitoring coverage
- Analyse violation trends to identify patterns

## Boundaries
For life-threatening emergencies, direct users to call 911 immediately.
You are an AI assistant — always recommend human expert review for final compliance decisions.
"""


class ARIAAgent:
    """
    ARIA Agent powered by Google GenAI SDK with manual function calling.

    Architecture:
    - FunctionDeclaration-based tool schemas (NOT Python callables) so the SDK
      never tries to auto-execute async functions and silently fails.
    - After each model turn we check for function_calls, execute them ourselves
      against Firestore/BigQuery, and send the results back to the model.
    - Simple dict maintains per-user conversation sessions.

    Usage:
        aria = ARIAAgent(firestore_svc, bigquery_svc)
        response = await aria.query(user_id="manager-1", site_id="site-alpha", message="What's the current risk level?")
    """

    def __init__(self, firestore_svc, bigquery_svc):
        self._firestore = firestore_svc
        self._bigquery = bigquery_svc
        self._client = genai.Client(api_key=settings.gemini_api_key)
        self._sessions: dict = {}

        # FunctionDeclaration-based tool config — we execute tools manually
        self._tool_config = [
            types.Tool(function_declarations=[
                types.FunctionDeclaration(
                    name=t["name"],
                    description=t["description"],
                    parameters=types.Schema(
                        type=t["parameters"]["type"],
                        properties={
                            k: types.Schema(type=v["type"], description=v.get("description", ""))
                            for k, v in t["parameters"]["properties"].items()
                        },
                        required=t["parameters"].get("required", []),
                    ),
                )
                for t in ARIA_LIVE_TOOL_DECLARATIONS
            ])
        ]

        logger.info("ARIA Agent initialised — manual function calling mode")

    # ── Session management ────────────────────────────────────────────────────

    async def _ensure_session(self, user_id: str, site_id: str):
        session_id = f"aria:{user_id}:{site_id}"
        if session_id not in self._sessions:
            chat = self._client.aio.chats.create(
                model=settings.gemini_model,
                config=types.GenerateContentConfig(
                    system_instruction=ARIA_SYSTEM_INSTRUCTION,
                    tools=self._tool_config,
                    temperature=0.7,
                )
            )
            self._sessions[session_id] = chat
        return self._sessions[session_id], session_id

    # ── Tool execution ────────────────────────────────────────────────────────

    async def _execute_tool(self, name: str, args: dict) -> dict:
        """
        Execute a named tool against real Firestore/BigQuery data.
        Always returns a dict (never raises) so the model always gets a result.
        """
        from tools.adk_tools import _REPORT_STORE
        from core.safety_standards import OSHA_STANDARDS

        try:
            if name == "get_live_site_status":
                site_id = args.get("site_id", "demo-site")
                try:
                    alerts = await self._firestore.get_active_alerts(site_id)
                    violations = await self._firestore.get_recent_violations(site_id, limit=20)
                    risk_score = await self._bigquery.get_site_risk_score(site_id)
                except Exception as e:
                    logger.warning(f"[ARIA] get_live_site_status error: {e}")
                    return {"error": str(e), "site_id": site_id}

                counts: dict[str, int] = {"critical": 0, "high": 0, "medium": 0, "low": 0}
                for v in violations:
                    sev = str(getattr(v, "severity", "low")).lower()
                    counts[sev] = counts.get(sev, 0) + 1

                return {
                    "site_id": site_id,
                    "risk_score": risk_score,
                    "health": (
                        "HIGH RISK — immediate intervention required" if risk_score >= 75
                        else "ELEVATED RISK — monitor closely" if risk_score >= 50
                        else "Acceptable risk level"
                    ),
                    "open_alerts": len(alerts),
                    "violations_by_severity": counts,
                    "stop_work_required": counts["critical"] > 0,
                    "recent_violations": [
                        {
                            "violation_type": getattr(v, "violation_type", ""),
                            "osha_code": getattr(v, "osha_code", ""),
                            "severity": getattr(v, "severity", ""),
                            "remediation": getattr(v, "remediation", ""),
                        }
                        for v in violations[:5]
                    ],
                }

            elif name == "get_recent_violations":
                site_id = args.get("site_id", "demo-site")
                limit = int(args.get("limit", 5))
                try:
                    violations = await self._firestore.get_recent_violations(site_id, limit=limit)
                except Exception as e:
                    logger.warning(f"[ARIA] get_recent_violations error: {e}")
                    return {"error": str(e), "violations": []}
                return {
                    "count": len(violations),
                    "violations": [
                        {
                            "violation_type": getattr(v, "violation_type", ""),
                            "description": getattr(v, "description", ""),
                            "osha_code": getattr(v, "osha_code", ""),
                            "severity": getattr(v, "severity", ""),
                            "remediation": getattr(v, "remediation", ""),
                            "evidence_image_url": getattr(v, "evidence_image_url", None),
                            "annotated_image_url": getattr(v, "annotated_image_url", None),
                        }
                        for v in violations
                    ],
                }

            elif name == "lookup_osha_standard":
                query = args.get("query", "").lower()
                matches = [
                    {
                        "code": s.code,
                        "title": s.title,
                        "description": s.description[:300],
                        "severity": s.severity.value,
                        "remediation": s.remediation,
                        "keywords": s.keywords[:5],
                    }
                    for s in OSHA_STANDARDS
                    if (query in s.code.lower() or query in s.title.lower() or
                        any(query in kw.lower() for kw in s.keywords))
                ][:5]
                return {"found": bool(matches), "count": len(matches), "standards": matches}

            elif name == "get_camera_status":
                site_id = args.get("site_id", "demo-site")
                try:
                    cameras = await self._firestore.get_cameras_for_site(site_id)
                except Exception as e:
                    logger.warning(f"[ARIA] get_camera_status error: {e}")
                    return {"error": str(e), "cameras": []}
                monitoring = sum(1 for c in cameras if getattr(c, "status", "") == "monitoring")
                return {
                    "total": len(cameras),
                    "monitoring": monitoring,
                    "cameras": [
                        {
                            "id": getattr(c, "id", ""),
                            "name": getattr(c, "name", ""),
                            "status": getattr(c, "status", ""),
                        }
                        for c in cameras
                    ],
                }

            elif name == "get_violation_trend":
                site_id = args.get("site_id", "demo-site")
                days = int(args.get("days", 7))
                try:
                    summary = await self._bigquery.get_violations_summary(site_id, days=days)
                    risk = await self._bigquery.get_site_risk_score(site_id)
                except Exception as e:
                    logger.warning(f"[ARIA] get_violation_trend error: {e}")
                    return {"error": str(e)}
                return {"period_days": days, "risk_score": risk, "summary": summary}

            elif name == "get_report_analysis":
                session_id = args.get("session_id", "")
                report = _REPORT_STORE.get(session_id)
                if not report:
                    return {"found": False, "error": "No report loaded for this session."}
                violations = report.get("violations", [])
                return {
                    "found": True,
                    "title": report.get("title", ""),
                    "compliance_score": report.get("compliance_score", 0),
                    "executive_summary": report.get("executive_summary", ""),
                    "critical_findings": report.get("critical_findings", []),
                    "corrective_actions": report.get("corrective_actions", []),
                    "violation_count": len(violations),
                    "violations": violations[:10],
                }

            else:
                return {"error": f"Unknown tool: {name}"}

        except Exception as e:
            logger.warning(f"[ARIA] Tool dispatch error [{name}]: {e}")
            return {"error": str(e)}

    # ── Public query methods ──────────────────────────────────────────────────

    async def query(self, user_id: str, site_id: str, message: str) -> dict:
        """Non-streaming query with full function calling loop."""
        chat, session_id = await self._ensure_session(user_id, site_id)
        contextual_message = f"[Active site: {site_id}]\n{message}"

        response = await chat.send_message(contextual_message)
        tool_calls_made = []

        # Execute tools until the model produces a final text response
        while response.function_calls:
            function_responses = []
            for fc in response.function_calls:
                tool_calls_made.append({"tool": fc.name, "args": dict(fc.args or {})})
                result = await self._execute_tool(fc.name, dict(fc.args or {}))
                logger.info(f"[ARIA] Tool {fc.name} → {list(result.keys())}")
                function_responses.append(
                    types.Part.from_function_response(name=fc.name, response=result)
                )
            response = await chat.send_message(function_responses)

        return {
            "response": response.text or "I was unable to process that request. Please try again.",
            "tool_calls": tool_calls_made,
            "session_id": session_id,
        }

    async def query_stream(self, user_id: str, site_id: str, message: str):
        """
        Streaming query with manual function calling.
        Yields event dicts:
          {"type": "tool_call", "tool": str, "args": dict}
          {"type": "transcript", "text": str}
          {"type": "final", "text": str, "tool_calls": list, "session_id": str, "images": list}
        """
        chat, session_id = await self._ensure_session(user_id, site_id)
        contextual_message = f"[Active site: {site_id}]\n{message}"

        response_text = ""
        tool_calls_made = []
        collected_images: list = []  # Images gathered from tool results

        stream = await chat.send_message_stream(contextual_message)
        pending_fcs = []

        async for chunk in stream:
            if chunk.function_calls:
                for fc in chunk.function_calls:
                    pending_fcs.append(fc)
                    yield {"type": "tool_call", "tool": fc.name, "args": dict(fc.args or {})}
            if chunk.text:
                response_text += chunk.text
                yield {"type": "transcript", "text": chunk.text}

        # Execute tools and get the grounded final answer
        while pending_fcs:
            function_responses = []
            for fc in pending_fcs:
                tool_calls_made.append({"tool": fc.name, "args": dict(fc.args or {})})
                result = await self._execute_tool(fc.name, dict(fc.args or {}))
                logger.info(f"[ARIA stream] Tool {fc.name} → {list(result.keys())}")

                # Collect annotated images from violation tool results
                if fc.name == "get_recent_violations":
                    for v in result.get("violations", []):
                        img_url = v.get("annotated_image_url") or v.get("evidence_image_url")
                        if img_url:
                            collected_images.append({
                                "url": img_url,
                                "caption": f"{v.get('violation_type', 'Violation')} — {v.get('osha_code', '')}",
                                "severity": v.get("severity", "medium"),
                            })

                function_responses.append(
                    types.Part.from_function_response(name=fc.name, response=result)
                )

            response_text = ""
            pending_fcs = []

            stream = await chat.send_message_stream(function_responses)
            async for chunk in stream:
                if chunk.function_calls:
                    for fc in chunk.function_calls:
                        pending_fcs.append(fc)
                        yield {"type": "tool_call", "tool": fc.name, "args": dict(fc.args or {})}
                if chunk.text:
                    response_text += chunk.text
                    yield {"type": "transcript", "text": chunk.text}

        yield {
            "type": "final",
            "text": response_text or "I was unable to process that request. Please try again.",
            "tool_calls": tool_calls_made,
            "session_id": session_id,
            "images": collected_images,
        }

    async def query_with_context(
        self,
        user_id: str,
        session_id: str,
        context_str: str,
        message: str,
    ) -> dict:
        """Non-streaming query with pre-loaded report context (for report Q&A)."""
        adk_session_id = f"report:{session_id}"
        if adk_session_id not in self._sessions:
            chat = self._client.aio.chats.create(
                model=settings.gemini_model,
                config=types.GenerateContentConfig(
                    system_instruction=ARIA_SYSTEM_INSTRUCTION,
                    tools=self._tool_config,
                )
            )
            self._sessions[adk_session_id] = chat

        chat = self._sessions[adk_session_id]
        contextual_message = f"[REPORT CONTEXT]\n{context_str}\n\n[USER QUESTION]\n{message}"

        response = await chat.send_message(contextual_message)
        tool_calls_made = []

        while response.function_calls:
            function_responses = []
            for fc in response.function_calls:
                tool_calls_made.append({"tool": fc.name, "args": dict(fc.args or {})})
                result = await self._execute_tool(fc.name, dict(fc.args or {}))
                function_responses.append(
                    types.Part.from_function_response(name=fc.name, response=result)
                )
            response = await chat.send_message(function_responses)

        return {
            "response": response.text or "I was unable to process that request. Please try again.",
            "tool_calls": tool_calls_made,
            "session_id": adk_session_id,
        }

    async def reset_session(self, user_id: str, site_id: str) -> None:
        """Clear conversation history for a user (start fresh)."""
        session_id = f"aria:{user_id}:{site_id}"
        if session_id in self._sessions:
            del self._sessions[session_id]
