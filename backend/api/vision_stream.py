"""Vision Stream SSE endpoint — frame-by-frame Gemini Vision analysis.

GET /api/v1/inspect/vision-stream?blob_name=...&site_id=...&camera_id=...

Streams Server-Sent Events:
  frame     — { frame_num, frame_b64 }
  analysis  — { frame_num, text, safe }
  violation — { frame_num, violation_id, violation_type, description, severity,
                osha_code, confidence, analysis_text, annotated_b64, site_id,
                session_id, timestamp }
  done      — { total_frames, total_violations, session_id }
  error     — { message }
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import uuid
from datetime import datetime
from typing import AsyncGenerator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from google import genai
from google.genai import types

from core.config import get_settings
from models.schemas import HazardCategory, Severity, Violation
from services.firestore_service import FirestoreService
from services.recording_processor import RecordingProcessor
from services.storage_service import StorageService

logger = logging.getLogger(__name__)
settings = get_settings()

vision_router = APIRouter()


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _map_hazard_category(violation_type_str: str) -> HazardCategory:
    """Best-effort map of free-text violation type to HazardCategory enum."""
    s = violation_type_str.lower()
    if any(k in s for k in ("ppe", "hard hat", "helmet", "vest", "glove", "goggle", "respirator", "boot")):
        return HazardCategory.PPE
    if any(k in s for k in ("fall", "scaffold", "guardrail", "harness", "opening", "edge")):
        return HazardCategory.FALL_PROTECTION
    if any(k in s for k in ("electric", "wire", "cord", "live", "arc", "shock")):
        return HazardCategory.ELECTRICAL
    if any(k in s for k in ("struck", "projectile", "flying", "debris")):
        return HazardCategory.STRUCK_BY
    if any(k in s for k in ("caught", "entangle", "pinch", "crush")):
        return HazardCategory.CAUGHT_IN
    if any(k in s for k in ("fire", "flammable", "explosion", "spark", "ignition")):
        return HazardCategory.FIRE_EXPLOSION
    if any(k in s for k in ("chemical", "hazmat", "spill", "toxic", "corrosive")):
        return HazardCategory.CHEMICAL
    if any(k in s for k in ("housekeeping", "clutter", "debris", "slip", "trip")):
        return HazardCategory.HOUSEKEEPING
    if any(k in s for k in ("equipment", "machinery", "vehicle", "forklift", "crane", "tool")):
        return HazardCategory.EQUIPMENT
    return HazardCategory.PPE  # safest default for unlabeled hazards


VISION_PROMPT = """You are a construction site safety inspector AI.
Analyze this video frame and respond with ONLY a JSON object (no markdown, no code fences):
{
  "violation_detected": true or false,
  "safe": true or false,
  "analysis_text": "One clear sentence describing what you see safety-wise.",
  "violation_type": "e.g. Missing Hard Hat / Fall Hazard / No Safety Vest / Unsafe Equipment Use / Electrical Hazard / Fire Hazard / Housekeeping Hazard / Missing Safety Harness",
  "description": "Specific description of the hazard observed.",
  "osha_code": "e.g. 29 CFR 1926.100",
  "severity": "critical / high / medium / low",
  "confidence": 0.0 to 1.0,
  "bbox": {"x": 0.0, "y": 0.0, "w": 0.6, "h": 0.6}
}
If no violation is detected set violation_detected to false, safe to true, and use empty strings for violation fields."""


# ─── Dependency helpers ───────────────────────────────────────────────────────

def _get_firestore() -> FirestoreService:
    from main import firestore_svc
    return firestore_svc


def _get_storage() -> StorageService:
    from main import storage_svc
    return storage_svc


# ─── SSE Endpoint ─────────────────────────────────────────────────────────────

@vision_router.get("/inspect/vision-stream", tags=["Vision"])
async def vision_stream(
    blob_name: str,
    site_id: str,
    camera_id: str = "vision-stream",
    session_id: str = "",
    firestore: FirestoreService = Depends(_get_firestore),
    storage: StorageService = Depends(_get_storage),
):
    """Stream frame-by-frame Gemini Vision analysis of an uploaded recording."""
    _session_id = session_id or f"vision-{uuid.uuid4().hex[:8]}"
    client = genai.Client(api_key=settings.gemini_api_key)
    processor = RecordingProcessor(storage)

    async def generate() -> AsyncGenerator[str, None]:
        frame_num = 0
        violations_found = 0
        # Deduplication: track last frame_num each violation_type was reported.
        # Same violation type within DEDUPE_WINDOW frames is silently dropped.
        recent_detections: dict[str, int] = {}
        DEDUPE_WINDOW = 20  # frames (~40 s at 0.5 fps)
        try:
            # 0.5 fps = 1 sample every 2 seconds — halves API calls vs 1 fps
            # while still catching short-lived hazards.
            async for fn, frame_b64 in processor.extract_frames_from_gcs(blob_name, fps=0.5):
                frame_num = fn

                # ── Stream raw frame thumbnail ─────────────────────────────────
                yield _sse("frame", {"frame_num": frame_num, "frame_b64": frame_b64})

                # ── Analyze frame with Gemini Vision ──────────────────────────
                raw = ""
                try:
                    frame_bytes = base64.b64decode(frame_b64)
                    response = await asyncio.wait_for(
                        client.aio.models.generate_content(
                            model=settings.gemini_model,
                            contents=types.Content(
                                parts=[
                                    types.Part(text=VISION_PROMPT),
                                    types.Part(inline_data=types.Blob(
                                        data=frame_bytes,
                                        mime_type="image/jpeg",
                                    )),
                                ]
                            ),
                        ),
                        timeout=20.0,
                    )
                    raw = (response.text or "").strip()
                    # Strip code fences in case model wraps output
                    if raw.startswith("```"):
                        raw = raw.split("```")[1]
                        if raw.startswith("json"):
                            raw = raw[4:]
                    raw = raw.strip()
                    result = json.loads(raw)

                except asyncio.TimeoutError:
                    logger.warning(f"[VisionStream] Frame {frame_num} timed out")
                    yield _sse("analysis", {"frame_num": frame_num, "text": "Analysis timed out", "safe": True})
                    continue
                except json.JSONDecodeError as e:
                    logger.warning(f"[VisionStream] JSON parse error frame {frame_num}: {e} — raw: {raw[:200]}")
                    yield _sse("analysis", {"frame_num": frame_num, "text": raw[:200] or "Could not parse response", "safe": True})
                    continue
                except Exception as e:
                    logger.warning(f"[VisionStream] Frame {frame_num} analysis error: {e}")
                    yield _sse("analysis", {"frame_num": frame_num, "text": "Could not analyze frame", "safe": True})
                    continue

                # ── Stream analysis ────────────────────────────────────────────
                yield _sse("analysis", {
                    "frame_num": frame_num,
                    "text": result.get("analysis_text", ""),
                    "safe": bool(result.get("safe", True)),
                })

                # ── If violation — deduplicate, annotate frame, save, stream ──
                if result.get("violation_detected") and result.get("violation_type"):
                    # Deduplication: use the mapped HazardCategory as the key so that
                    # "Missing Machine Guarding", "Machine Guarding Hazard", etc.
                    # all collapse into the same category bucket (e.g. "ppe" or "equipment")
                    # and don't generate duplicate violation cards for the same issue.
                    category_key = _map_hazard_category(result.get("violation_type", "")).value
                    last_frame = recent_detections.get(category_key, -999)
                    if frame_num - last_frame <= DEDUPE_WINDOW:
                        continue  # same hazard category seen recently — skip duplicate
                    recent_detections[category_key] = frame_num

                    violations_found += 1

                    try:
                        annotated_bytes = processor.annotate_frame(
                            frame_bytes=frame_bytes,
                            label=result.get("violation_type", "Violation"),
                            bbox=result.get("bbox"),
                        )
                        annotated_b64 = base64.b64encode(annotated_bytes).decode()
                    except Exception:
                        annotated_b64 = frame_b64

                    sev_str = (result.get("severity") or "medium").lower()
                    try:
                        severity = Severity(sev_str)
                    except ValueError:
                        severity = Severity.MEDIUM

                    violation_id = str(uuid.uuid4())
                    try:
                        violation = Violation(
                            id=violation_id,
                            session_id=_session_id,
                            camera_id=camera_id,
                            site_id=site_id,
                            timestamp=datetime.utcnow(),
                            violation_type=_map_hazard_category(result.get("violation_type", "")),
                            description=result.get("description", ""),
                            osha_code=result.get("osha_code", ""),
                            severity=severity,
                            remediation="Immediate corrective action required per OSHA guidelines.",
                            confidence=float(result.get("confidence", 0.9)),
                            frame_number=frame_num,
                            annotated_image_url=f"data:image/jpeg;base64,{annotated_b64}",
                        )
                        await firestore.save_violation(violation)
                        logger.info(f"[VisionStream] Saved: {result.get('violation_type')} (frame {frame_num})")
                    except Exception as e:
                        logger.warning(f"[VisionStream] Failed to save violation: {e}")

                    yield _sse("violation", {
                        "frame_num": frame_num,
                        "violation_id": violation_id,
                        "violation_type": result.get("violation_type", ""),
                        "description": result.get("description", ""),
                        "osha_code": result.get("osha_code", ""),
                        "severity": sev_str,
                        "confidence": float(result.get("confidence", 0.9)),
                        "analysis_text": result.get("analysis_text", ""),
                        "annotated_b64": annotated_b64,
                        "site_id": site_id,
                        "session_id": _session_id,
                        "timestamp": datetime.utcnow().isoformat(),
                    })

        except Exception as e:
            logger.error(f"[VisionStream] Stream error: {e}", exc_info=True)
            yield _sse("error", {"message": str(e)})

        yield _sse("done", {
            "total_frames": frame_num,
            "total_violations": violations_found,
            "session_id": _session_id,
        })

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
