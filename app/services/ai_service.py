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
  "intent": "maintenance|complaint|rent_query|admin|unknown",
  "category": "plumbing|electrical|hvac|structural|appliance|general|unknown",
  "severity": "minor|serious",
  "urgency": "low|medium|high|emergency",
  "diagnosis": "brief description of the specific problem observed (1-2 sentences)",
  "confidence": 0.0-1.0,
  "reasoning": "one sentence"
}

Intent guide:
- maintenance: any physical problem with the apartment (broken, leaking, not working)
- complaint: noise, neighbors, non-physical issues
- rent_query: asking about rent payment, how much they owe, if they paid, due date
- admin: general questions, documents, other

Severity guide (for maintenance only):
- minor: small cosmetic or low-impact issues — dripping tap, paint peeling, squeaky door
- serious: significant impact on habitability — broken boiler, no hot water, leaking pipe, broken lock

Urgency guide:
- emergency: gas leak, flooding, no heating in winter, fire risk
- high: no hot water, broken lock, toilet not working
- medium: dripping tap, broken appliance, heating issue
- low: cosmetic damage, minor inconvenience

Diagnosis: write a clear, professional 1-2 sentence description of what the problem likely is, suitable for a contractor. For non-maintenance intents write null.""",
        messages=[{
            "role": "user",
            "content": f"Tenant message (language: {language}):\n{message}"
        }]
    )

    text = response.content[0].text.strip()
    return _parse_json(text, fallback={
        "intent": "admin",
        "category": "unknown",
        "severity": "minor",
        "urgency": "medium",
        "diagnosis": None,
        "confidence": 0.5,
        "reasoning": "parse error — treated as admin",
    })


async def diagnose_from_image(
    image_bytes: bytes,
    mime_type: str,
    tenant_description: str,
    language: str = "de",
) -> dict:
    """
    Analyze maintenance issue from image using Claude Vision.
    Uses Sonnet — needed for vision capability.

    Returns:
    {
        "diagnosis": "detailed description of the problem",
        "severity": "minor|moderate|serious|critical",
        "recommended_action": "self_fix|contractor_needed|emergency",
        "self_fix_instructions": "step by step if applicable, else null",
        "estimated_cost_eur": {"min": 0, "max": 0},
        "contractor_specialty": "plumbing|electrical|etc or null"
    }
    """
    image_data = base64.standard_b64encode(image_bytes).decode("utf-8")

    response = await client.messages.create(
        model=settings.anthropic_model_smart,
        max_tokens=512,
        system="""You are an expert property maintenance diagnostician.
Analyze the image and return ONLY valid JSON, no markdown.

JSON schema:
{
  "diagnosis": "clear description of what you see",
  "severity": "minor|moderate|serious|critical",
  "recommended_action": "self_fix|contractor_needed|emergency",
  "self_fix_instructions": "step by step instructions or null",
  "estimated_cost_eur": {"min": 0, "max": 0},
  "contractor_specialty": "plumbing|electrical|hvac|structural|appliance|general|null"
}

Severity guide:
- critical: immediate risk to health/safety (gas, flood, electrical danger)
- serious: significant damage, urgent repair needed
- moderate: needs repair soon but not emergency
- minor: cosmetic or low priority""",
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
                        "Please diagnose this maintenance issue."
                    ),
                },
            ],
        }]
    )

    text = response.content[0].text.strip()
    return _parse_json(text, fallback={
        "diagnosis": "Could not analyse image — please describe the problem in text.",
        "severity": "minor",
        "recommended_action": "contractor_needed",
        "self_fix_instructions": None,
        "estimated_cost_eur": None,
        "contractor_specialty": "general",
    })


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
