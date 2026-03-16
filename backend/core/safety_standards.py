"""OSHA and ISO 45001 safety standards knowledge base for the compliance agent."""

from dataclasses import dataclass, field
from enum import Enum


class Severity(str, Enum):
    CRITICAL = "critical"      # Immediate threat to life — stop work order
    HIGH = "high"              # Serious injury risk — immediate correction required
    MEDIUM = "medium"          # Significant risk — correct within 24 hours
    LOW = "low"                # General non-compliance — correct within 7 days


class HazardCategory(str, Enum):
    PPE = "ppe"
    FALL_PROTECTION = "fall_protection"
    ELECTRICAL = "electrical"
    STRUCK_BY = "struck_by"
    CAUGHT_IN = "caught_in"
    FIRE_EXPLOSION = "fire_explosion"
    CHEMICAL = "chemical"
    ERGONOMIC = "ergonomic"
    HOUSEKEEPING = "housekeeping"
    EQUIPMENT = "equipment"


@dataclass
class SafetyStandard:
    code: str                        # e.g., "OSHA 1926.100(a)"
    title: str
    description: str
    hazard_category: HazardCategory
    severity: Severity
    remediation: str
    keywords: list[str] = field(default_factory=list)


# ───────────────────────────────────────────────────────────
# OSHA 1926 — Construction Safety Standards
# ───────────────────────────────────────────────────────────
OSHA_STANDARDS: list[SafetyStandard] = [
    # PPE
    SafetyStandard(
        code="OSHA 1926.100(a)",
        title="Head Protection — Hard Hat Required",
        description="Employees working in areas where there is a possible danger of head injury from impact, or from falling or flying objects, or from electrical hazards, shall be protected by protective helmets.",
        hazard_category=HazardCategory.PPE,
        severity=Severity.HIGH,
        remediation="Worker must immediately put on a hard hat before continuing work. Stop work if no hard hat is available.",
        keywords=["hard hat", "helmet", "head protection", "no helmet", "missing hard hat"],
    ),
    SafetyStandard(
        code="OSHA 1926.102(a)",
        title="Eye and Face Protection",
        description="Eye and face protection shall be required where there is reasonable probability of injury that can be prevented by such equipment. Safety glasses, goggles, or face shields must be worn.",
        hazard_category=HazardCategory.PPE,
        severity=Severity.MEDIUM,
        remediation="Worker must wear appropriate eye/face protection. Safety glasses for general work, goggles for chemical/grinding, face shield for splash hazards.",
        keywords=["safety glasses", "goggles", "eye protection", "face shield", "no glasses"],
    ),
    SafetyStandard(
        code="OSHA 1926.95(a)",
        title="Personal Protective Equipment — High-Visibility Vest",
        description="Workers exposed to vehicular or equipment traffic must wear high-visibility safety apparel meeting ANSI/ISEA standards.",
        hazard_category=HazardCategory.PPE,
        severity=Severity.HIGH,
        remediation="Worker must wear a high-visibility vest or jacket before re-entering traffic/equipment zones.",
        keywords=["safety vest", "hi-vis", "high visibility", "reflective vest", "no vest"],
    ),
    SafetyStandard(
        code="OSHA 1926.96",
        title="Occupational Foot Protection",
        description="Employees working in areas where there is danger of foot injuries due to falling or rolling objects, or objects piercing the sole, shall be protected by safety-toed footwear.",
        hazard_category=HazardCategory.PPE,
        severity=Severity.MEDIUM,
        remediation="Worker must wear steel-toed or composite-toed safety boots. Regular footwear is not acceptable.",
        keywords=["safety boots", "steel toe", "foot protection", "no boots", "sandals", "sneakers on site"],
    ),

    # Fall Protection
    SafetyStandard(
        code="OSHA 1926.501(b)(1)",
        title="Fall Protection — Unprotected Sides and Edges",
        description="Each employee on a walking/working surface with an unprotected side or edge which is 6 feet (1.8 m) or more above a lower level shall be protected from falling by guardrail systems, safety net systems, or personal fall arrest systems.",
        hazard_category=HazardCategory.FALL_PROTECTION,
        severity=Severity.CRITICAL,
        remediation="STOP WORK. Install guardrails, safety netting, or ensure all workers have and are wearing fall arrest harnesses before resuming work at height.",
        keywords=["open edge", "unprotected edge", "no guardrail", "fall hazard", "elevated work", "scaffolding edge", "rooftop edge"],
    ),
    SafetyStandard(
        code="OSHA 1926.502(d)",
        title="Personal Fall Arrest Systems — Harness Required",
        description="Personal fall arrest systems shall be used when working at heights ≥6 ft. The harness must be properly worn and attached to an anchor point capable of supporting 5,000 lbs.",
        hazard_category=HazardCategory.FALL_PROTECTION,
        severity=Severity.CRITICAL,
        remediation="STOP WORK. Worker must put on and properly connect a fall arrest harness before resuming elevated work.",
        keywords=["harness", "fall arrest", "no harness", "lifeline", "lanyard", "anchor point"],
    ),
    SafetyStandard(
        code="OSHA 1926.451(g)(1)",
        title="Scaffolding — Fall Protection",
        description="Each employee on a scaffold more than 10 feet above a lower level shall be protected from falling.",
        hazard_category=HazardCategory.FALL_PROTECTION,
        severity=Severity.CRITICAL,
        remediation="Install guardrails on all open sides of scaffolding OR provide and enforce personal fall protection for all workers.",
        keywords=["scaffold", "scaffolding", "no guardrail on scaffold", "open scaffold"],
    ),

    # Electrical
    SafetyStandard(
        code="OSHA 1926.416(a)(1)",
        title="Electrical — Exposed Wiring",
        description="No employer shall permit an employee to work in such proximity to any part of an electric power circuit that the employee could contact the electric power circuit in the course of work unless the employee is protected against electric shock.",
        hazard_category=HazardCategory.ELECTRICAL,
        severity=Severity.CRITICAL,
        remediation="STOP WORK. De-energize the circuit, apply LOTO (Lock-Out Tag-Out), or establish a safe clearance distance before continuing.",
        keywords=["exposed wire", "bare wire", "electrical hazard", "live wire", "open electrical panel", "uninsulated"],
    ),

    # Struck By
    SafetyStandard(
        code="OSHA 1926.601(b)(14)",
        title="Struck-By — Overhead Work Zone",
        description="Employees shall not work or pass under suspended loads and shall not remain in the area below overhead work where objects may fall.",
        hazard_category=HazardCategory.STRUCK_BY,
        severity=Severity.HIGH,
        remediation="Establish exclusion zones below overhead work. Use toe boards, nets, or screens on elevated work surfaces. Post warning signs and barricades.",
        keywords=["overhead work", "suspended load", "falling object", "below crane", "drop zone"],
    ),

    # Housekeeping
    SafetyStandard(
        code="OSHA 1926.25",
        title="Housekeeping — Work Area Safety",
        description="During the course of construction, alteration, or repairs, form and scrap lumber with protruding nails, and all other debris, shall be kept cleared from work areas, passageways, and stairs.",
        hazard_category=HazardCategory.HOUSEKEEPING,
        severity=Severity.LOW,
        remediation="Clear debris, materials, and obstructions from walkways and work areas. Dispose of scrap materials properly.",
        keywords=["debris", "clutter", "blocked walkway", "scrap material", "messy site", "tripping hazard"],
    ),
]

# ───────────────────────────────────────────────────────────
# ISO 45001 Alignment
# ───────────────────────────────────────────────────────────
ISO_45001_CLAUSES = {
    "6.1.2": "Hazard identification and assessment of OH&S risks",
    "8.1.2": "Eliminating hazards and reducing OH&S risks",
    "8.6": "Procurement (ensuring safe equipment/materials)",
}

PPE_ITEMS = [
    "hard hat", "safety helmet",
    "safety vest", "high-visibility vest", "hi-vis jacket",
    "safety glasses", "safety goggles",
    "safety boots", "steel-toed boots",
    "fall harness", "safety harness",
    "gloves", "work gloves",
    "ear protection", "ear muffs", "ear plugs",
    "respirator", "dust mask", "face mask",
    "face shield",
]

CRITICAL_HAZARDS = [
    "open floor edge without guardrail",
    "worker without harness at height",
    "exposed live electrical wiring",
    "suspended load over workers",
    "worker in struck-by zone",
]


def get_system_prompt() -> str:
    """Return the safety-focused system prompt for the Orchestrator."""
    ppe_list = "\n".join(f"  - {item}" for item in PPE_ITEMS)
    standards_summary = "\n".join(
        f"  - [{s.code}] ({s.severity.value.upper()}) {s.title}"
        for s in OSHA_STANDARDS
    )

    return f"""You are SiteGuard AI, an enterprise field safety and compliance agent for construction and industrial sites.

Your mission is to SAVE LIVES by identifying safety violations in real-time from camera feeds and voice conversations.

## Your Core Responsibilities
1. **Analyze every video frame** for safety hazards — PPE violations, fall risks, electrical dangers, housekeeping issues
2. **Speak clearly and urgently** when a violation is spotted — identify the hazard, cite the OSHA standard, give the remediation step
3. **Prioritize CRITICAL hazards** (fall protection, electrical, struck-by) — issue an immediate STOP WORK for these
4. **Track everything** — every identified violation gets logged with severity, OSHA code, and recommended action
5. **Be conversational** — workers can ask questions, you can be interrupted (barge-in), and you respond in the worker's language

## PPE Items to Monitor
{ppe_list}

## Key OSHA Standards You Enforce
{standards_summary}

## Communication Style
- Be direct and urgent for critical hazards: "⚠️ CRITICAL: Worker at scaffold edge without harness — OSHA 1926.502(d) violation. STOP WORK IMMEDIATELY."
- Be clear for medium violations: "Warning: Worker missing safety glasses near grinding equipment — OSHA 1926.102. Please put on eye protection before continuing."
- Be helpful when asked questions: Answer safety questions thoroughly, citing standards.
- Match the language of the worker if they speak in a different language.
- Keep responses concise when workers are actively working — save the detail for reports.

## When You See No Violations
Say: "Site looks compliant in view. Continue monitoring. Stay safe."

## Output Format for Violations (JSON in tool calls)
Always log violations via the log_violation tool with:
- violation_type: category of violation
- description: what you saw
- osha_code: applicable OSHA standard
- severity: critical/high/medium/low
- remediation: immediate action required

Remember: A safety agent that misses a hazard has failed. Be thorough, be accurate, and always err on the side of caution.
"""
