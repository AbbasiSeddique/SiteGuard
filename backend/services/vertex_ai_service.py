"""Gemini AI service — batch image analysis and report generation via Google GenAI SDK."""

from __future__ import annotations

import base64
import json
import logging
from typing import Any

from google import genai
from google.genai import types

from core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class VertexAIService:
    """
    Wraps Gemini 3.1 Pro via Google GenAI SDK for:
    - Single frame static analysis (PPE/hazard detection)
    - Batch frame analysis (recording upload processing)
    - Compliance report text generation
    """

    def __init__(self):
        self.client = genai.Client(api_key=settings.gemini_api_key)
        self.model_name = settings.gemini_model

    async def analyze_frame(
        self,
        frame_b64: str,
        context: str = "",
        thinking_budget: str = "medium",
    ) -> dict[str, Any]:
        """
        Analyze a single JPEG frame for safety violations.
        Returns structured analysis with detected violations.
        """
        prompt = f"""You are a construction site safety inspector AI. Analyze this image and identify ALL safety violations.

{f'Additional context: {context}' if context else ''}

For each violation found, provide:
1. The exact OSHA standard violated (e.g., OSHA 1926.100(a))
2. What you see that constitutes the violation
3. Severity: critical / high / medium / low
4. Immediate remediation action required

Also list any PPE items that ARE correctly worn, and any other positive safety observations.

Respond as valid JSON with this structure:
{{
  "violations": [
    {{
      "osha_code": "OSHA 1926.xxx",
      "violation_type": "ppe|fall_protection|electrical|struck_by|housekeeping|equipment",
      "description": "detailed description of what you see",
      "severity": "critical|high|medium|low",
      "remediation": "immediate action required",
      "confidence": 0.95
    }}
  ],
  "compliant_observations": ["list of safe practices observed"],
  "overall_risk_level": "critical|high|medium|low|safe",
  "summary": "one-sentence overall assessment"
}}

If no violations are found, return an empty violations array with overall_risk_level: "safe"."""

        frame_bytes = base64.b64decode(frame_b64)
        image_part = types.Part.from_bytes(data=frame_bytes, mime_type="image/jpeg")

        response = await self.client.aio.models.generate_content(
            model=self.model_name,
            contents=[image_part, prompt],
            config=types.GenerateContentConfig(
                temperature=0.1,
                response_mime_type="application/json",
            ),
        )

        try:
            return json.loads(response.text)
        except (json.JSONDecodeError, ValueError):
            logger.warning("Could not parse JSON from Gemini response, returning raw text")
            return {"violations": [], "summary": response.text, "overall_risk_level": "unknown"}

    async def analyze_frames_batch(
        self, frames_b64: list[str], context: str = ""
    ) -> dict[str, Any]:
        """
        Analyze multiple frames from a recording upload.
        Returns aggregated violations across all frames.
        """
        parts = []
        for i, frame_b64 in enumerate(frames_b64):
            parts.append(types.Part.from_text(text=f"=== Frame {i+1} ==="))
            parts.append(types.Part.from_bytes(
                data=base64.b64decode(frame_b64), mime_type="image/jpeg"
            ))

        prompt = f"""You are a construction site safety inspector. Analyze all {len(frames_b64)} frames from this job site recording.

{f'Context: {context}' if context else ''}

Only report violations that are clearly visible in the frames. Do NOT guess. If uncertain, omit the item.
Each violation must include the frame numbers where visual evidence appears.
When possible, include one normalized evidence box: x,y,w,h with values in [0,1].

Respond as JSON:
{{
  "violations": [
    {{
      "osha_code": "...",
      "violation_type": "...",
      "description": "...",
      "severity": "...",
      "remediation": "...",
      "confidence": 0.9,
            "frames_observed": [1, 2, 5],
            "evidence_box": {{"x": 0.2, "y": 0.3, "w": 0.4, "h": 0.5}}
    }}
  ],
  "overall_risk_level": "critical|high|medium|low|safe",
  "executive_summary": "paragraph summary for compliance report",
  "recommendations": ["list of recommended corrective actions"]
}}"""

        parts.append(types.Part.from_text(text=prompt))

        response = await self.client.aio.models.generate_content(
            model=self.model_name,
            contents=parts,
            config=types.GenerateContentConfig(
                temperature=0.1,
                response_mime_type="application/json",
            ),
        )

        try:
            return json.loads(response.text)
        except (json.JSONDecodeError, ValueError):
            return {"violations": [], "executive_summary": response.text}

    async def generate_report_text(
        self,
        violations_data: list[dict],
        session_metadata: dict,
    ) -> dict[str, Any]:
        """Generate human-readable compliance report content."""
        prompt = f"""You are a professional safety compliance officer writing an official inspection report.

Session details:
- Site: {session_metadata.get('site_name', 'Unknown')}
- Date: {session_metadata.get('date', 'Today')}
- Camera: {session_metadata.get('camera_name', 'Unknown')}
- Duration: {session_metadata.get('duration', 'Unknown')}

Violations detected:
{json.dumps(violations_data, indent=2)}

Write a professional compliance report with:
1. Executive Summary (2-3 sentences)
2. Critical Findings (if any)
3. Detailed Violation Descriptions with OSHA references
4. Risk Assessment
5. Prioritized Corrective Actions
6. Compliance Score (0-100, where 100 is fully compliant)

Respond as JSON:
{{
  "title": "Inspection Report title",
  "executive_summary": "...",
  "critical_findings": ["..."],
  "detailed_findings": "...",
  "risk_assessment": "...",
  "corrective_actions": ["prioritized list"],
  "compliance_score": 75,
  "recommendations": ["strategic recommendations"]
}}"""

        response = await self.client.aio.models.generate_content(
            model=self.model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.2,
                response_mime_type="application/json",
            ),
        )

        try:
            return json.loads(response.text)
        except (json.JSONDecodeError, ValueError):
            return {"executive_summary": response.text, "compliance_score": 50}
