"""
PropFlow AI Service — single wrapper for all Claude API calls.
All agents use this service. Never call anthropic directly from agents.
"""
from __future__ import annotations

import base64
import json
import re
import structlog

import anthropic

from app.config import settings

logger = structlog.get_logger(__name__)


def _parse_json(text: str, fallback: dict) -> dict:
    """
    Parse JSON from Claude response.
    Handles: empty string, markdown code fences, extra prose around the JSON block.
    """
    if not text:
        logger.warning("Claude returned empty response, using fallback")
        return fallback
    # Strip ```json ... ``` or ``` ... ``` fences
    clean = re.sub(r"^```(?:json)?\s*", "", text, flags=re.MULTILINE)
    clean = re.sub(r"\s*```$", "", clean, flags=re.MULTILINE).strip()
    # Extract first {...} block if Claude added prose around it
    match = re.search(r"\{.*\}", clean, re.DOTALL)
    if match:
        clean = match.group(0)
    try:
        return json.loads(clean)
    except json.JSONDecodeError as exc:
        logger.warning("JSON parse failed, using fallback", raw=text[:200], error=str(exc))
        return fallback

client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)


async def classify_intent(message: str, language: str = "de") -> dict:
    """
    Classify incoming tenant message into intent + urgency.
    Uses fast Haiku model — cheap and quick.

    Returns:
    {
        "intent": "maintenance" | "complaint" | "admin" | "unknown",
        "category": "plumbing" | "electrical" | "hvac" |
                    "structural" | "appliance" | "general" | "unknown",
        "urgency": "low" | "medium" | "high" | "emergency",
        "confidence": 0.0-1.0,
        "reasoning": "brief explanation"
    }
    """
    response = await client.messages.create(
        model=settings.anthropic_model_fast,
        max_tokens=512,
        system="""You are a property maintenance triage assistant.
Classify the tenant message and return ONLY valid JSON, no markdown, no explanation.

JSON schema:
{
  "intent": "maintenance|complaint|rent_query|admin",
  "category": "plumbing|electrical|hvac|structural|appliance|general",
  "severity": "minor|serious",
  "urgency": "low|medium|high|emergency",
  "diagnosis": "brief description of the specific problem observed (1-2 sentences)",
  "confidence": 0.0-1.0,
  "reasoning": "one sentence"
}

RULES — always pick the best matching intent, never leave intent empty:
- maintenance: ANY physical problem with the apartment or its systems — broken, leaking, not working, damaged, smells, no heat/water/power. When in doubt, choose maintenance.
- complaint: noise, neighbor disputes, non-physical issues
- rent_query: rent payment, amount owed, due date, payment status
- admin: documents, contracts, keys, other non-physical administrative requests

Severity guide (for maintenance):
- minor: cosmetic or low-impact — dripping tap, paint peeling, squeaky door, small stain
- serious: significant impact on habitability — broken boiler, no hot water, leaking pipe, broken lock, no electricity, flooding, gas smell

Urgency guide:
- emergency: gas leak, flooding, no heating in winter, fire risk, no electricity
- high: no hot water, broken lock, toilet not working, burst pipe
- medium: dripping tap, broken appliance, heating issue, damaged door
- low: cosmetic damage, minor inconvenience, paint, squeaks

Diagnosis: 1-2 sentence professional description suitable for a contractor. Write null for non-maintenance intents.""",
        messages=[{
            "role": "user",
            "content": f"Tenant message (language: {language}):\n{message}"
        }]
    )

    text = response.content[0].text.strip()
    return _parse_json(text, fallback={
        "intent": "maintenance",   # safer: never silently discard a repair request
        "category": "general",
        "severity": "serious",
        "urgency": "medium",
        "diagnosis": None,
        "confidence": 0.3,
        "reasoning": "parse error — defaulting to maintenance triage",
    })


async def diagnose_from_image(
    image_bytes: bytes,
    mime_type: str,
    tenant_description: str,
    language: str = "de",
) -> dict:
    """
    Analyze maintenance issue from image using Claude Vision.
    Returns a STRUCTURED inspection report — see schema in system prompt.
    """
    image_data = base64.standard_b64encode(image_bytes).decode("utf-8")

    response = await client.messages.create(
        model=settings.anthropic_model_smart,
        max_tokens=1024,
        system="""You are an expert property maintenance diagnostician with 20 years of field experience.
Inspect the photo carefully and return ONLY valid JSON, no markdown, no prose.

JSON schema (every field required):
{
  "diagnosis": "1–2 sentence description of what is visibly wrong",
  "root_cause": "the underlying cause, not just the symptom (1 sentence)",
  "severity": "minor|moderate|serious|critical",
  "urgency": "low|medium|high|emergency",
  "safety_risk": "none|low|medium|high",
  "safety_notes": "1 sentence — what could go wrong if left, or null",
  "recommended_action": "self_fix|contractor_needed|emergency",
  "self_fix_instructions": "step-by-step if recommended_action=self_fix, else null",
  "parts_needed": ["array of specific parts/materials, e.g. 'compression fitting 15mm'", "..."],
  "tools_needed": ["array of professional tools required"],
  "estimated_duration_minutes": 60,
  "estimated_cost_eur": {"min": 80, "max": 140, "labor_min": 50, "labor_max": 90, "parts_min": 30, "parts_max": 50},
  "contractor_specialty": "plumbing|electrical|hvac|structural|appliance|general"
}

Severity guide:
- critical: immediate risk to health/safety (gas, flood, electrical danger, fire)
- serious: significant damage, urgent repair needed
- moderate: needs repair within days
- minor: cosmetic or low priority

Be specific. List actual parts with sizes/specs when you can infer them from the photo.
Cost estimates should be realistic for Western/Central Europe in EUR.""",
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": mime_type,
                        "data": image_data,
                    },
                },
                {
                    "type": "text",
                    "text": (
                        f"Tenant description: {tenant_description}\n"
                        "Inspect and produce the full structured diagnostic report."
                    ),
                },
            ],
        }]
    )

    text = response.content[0].text.strip()
    return _parse_json(text, fallback={
        "diagnosis": "Could not analyse image — please describe the problem in text.",
        "root_cause": "unknown — image analysis failed",
        "severity": "minor",
        "urgency": "medium",
        "safety_risk": "none",
        "safety_notes": None,
        "recommended_action": "contractor_needed",
        "self_fix_instructions": None,
        "parts_needed": [],
        "tools_needed": [],
        "estimated_duration_minutes": 60,
        "estimated_cost_eur": None,
        "contractor_specialty": "general",
    })


async def translate_message(text: str, target_language: str, context: str = "professional WhatsApp message") -> str:
    """
    Translate a message to the target language while preserving emojis, line breaks, and markdown.
    Returns the original text unchanged if translation fails or target is English.
    """
    if not text or not target_language or target_language.lower() in {"en", "eng", "english"}:
        return text
    try:
        response = await client.messages.create(
            model=settings.anthropic_model_fast,
            max_tokens=1500,
            system=(
                f"You are a professional translator. Translate the user's text into {target_language}.\n"
                f"Context: {context}.\n"
                "RULES:\n"
                "- Preserve ALL emojis, line breaks, and WhatsApp markdown (*bold*, _italic_, dashes).\n"
                "- Preserve numbers, currency symbols, addresses, and proper nouns (names, building names).\n"
                "- Keep the tone professional but warm.\n"
                "- Output ONLY the translated text — no explanation, no quotation marks."
            ),
            messages=[{"role": "user", "content": text}],
        )
        translated = response.content[0].text.strip()
        return translated or text
    except Exception as exc:
        logger.warning("Translation failed, using original", error=str(exc), target=target_language)
        return text


async def generate_tenant_reply(
    context: dict,
    language: str = "de",
) -> str:
    """
    Generate a natural, empathetic reply to send to tenant.
    Uses Haiku — just text generation.

    context = {
        "situation": "what is happening",
        "tenant_name": "Milan",
        "next_step": "what happens next",
        "tone": "professional|friendly|urgent"
    }
    """
    response = await client.messages.create(
        model=settings.anthropic_model_fast,
        max_tokens=256,
        system=(
            f"You are a professional property management assistant.\n"
            f"Write a SHORT WhatsApp message in {language}.\n"
            "Be warm but professional. Maximum 3 sentences.\n"
            "No markdown, no formatting — plain text only.\n"
            "Do not start with 'Hallo' or 'Hi' — the greeting is already in the system."
        ),
        messages=[{
            "role": "user",
            "content": str(context),
        }]
    )
    return response.content[0].text.strip()


async def generate_landlord_approval_message(
    tenant_name: str,
    unit: str,
    category: str,
    urgency: str,
    diagnosis: str,
    estimated_cost: dict,
) -> str:
    """
    Generate the approval request message sent to landlord.
    Structured, concise, actionable.
    """
    urgency_emoji = {
        "emergency": "🚨",
        "high": "🔴",
        "medium": "🟡",
        "low": "🟢",
    }.get(urgency, "🟡")

    cost_str = (
        f"€{estimated_cost['min']}–{estimated_cost['max']}"
        if estimated_cost
        else "Kosten unbekannt"
    )

    return (
        f"{urgency_emoji} Neues Ticket — {tenant_name}, Wohnung {unit}\n"
        f"Kategorie: {category.upper()} / {urgency.upper()}\n"
        f"Diagnose: {diagnosis}\n"
        f"Geschätzte Kosten: {cost_str}\n\n"
        f"Genehmigen? Antworten Sie mit JA oder NEIN"
    )
