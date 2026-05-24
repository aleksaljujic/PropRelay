"""
Anthropic Claude service — isolated reasoning tasks only.

LangGraph controls all workflow routing. Claude never decides which node
runs next; it only returns validated Pydantic JSON for nodes to consume.
"""
from __future__ import annotations

import json
import re

import structlog
from anthropic import AsyncAnthropic
from pydantic import ValidationError

from app.config import settings
from app.schemas.llm_outputs import DiagnosisResult, IntentClassification, IssueCategory

logger = structlog.get_logger(__name__)

_JSON_BLOCK = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)


class ClaudeService:
    """Thin async wrapper around Anthropic with strict schema validation."""

    def __init__(self) -> None:
        self._client: AsyncAnthropic | None = None
        if settings.anthropic_api_key:
            self._client = AsyncAnthropic(api_key=settings.anthropic_api_key)

    @property
    def available(self) -> bool:
        return self._client is not None

    async def _complete_json(
        self,
        system: str,
        user_content: str | list[dict],
        schema_hint: str,
    ) -> dict:
        """
        Call Claude and parse a JSON object from the response.

        Retries up to claude_max_retries on parse/validation failures.
        Falls back to deterministic heuristics when API key is absent.
        """
        if not self._client:
            raise RuntimeError("Anthropic API key not configured")

        last_error: Exception | None = None
        for attempt in range(1, settings.claude_max_retries + 1):
            try:
                response = await self._client.messages.create(
                    model=settings.claude_model,
                    max_tokens=1024,
                    system=(
                        f"{system}\n\n"
                        "Respond with ONLY a valid JSON object matching this schema:\n"
                        f"{schema_hint}\n"
                        "No markdown, no explanation — JSON only."
                    ),
                    messages=[{"role": "user", "content": user_content}],
                )
                raw = response.content[0].text if response.content else "{}"
                parsed = self._extract_json(raw)
                return parsed
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "Claude call failed",
                    attempt=attempt,
                    error=str(exc),
                )
        raise RuntimeError(f"Claude failed after {settings.claude_max_retries} retries") from last_error

    @staticmethod
    def _extract_json(text: str) -> dict:
        match = _JSON_BLOCK.search(text)
        payload = match.group(1) if match else text
        return json.loads(payload.strip())

    async def classify_intent(self, message: str, language: str = "de") -> IntentClassification:
        """Classify tenant message intent — maintenance, complaint, or admin."""
        if not self.available:
            return self._fallback_intent(message)

        schema = IntentClassification.model_json_schema()
        data = await self._complete_json(
            system=(
                "You classify tenant WhatsApp messages for a property manager. "
                f"Reply language context: {language}."
            ),
            user_content=f"Classify this tenant message:\n\n{message}",
            schema_hint=json.dumps(schema),
        )
        return IntentClassification.model_validate(data)

    async def diagnose_image(
        self,
        image_bytes: bytes,
        mime_type: str,
        description: str,
        language: str = "de",
    ) -> DiagnosisResult:
        """Vision analysis — category, severity, urgency, self-help steps."""
        if not self.available:
            return self._fallback_diagnosis(description)

        schema = DiagnosisResult.model_json_schema()
        content: list[dict] = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": mime_type,
                    "data": __import__("base64").b64encode(image_bytes).decode(),
                },
            },
            {
                "type": "text",
                "text": (
                    f"Tenant description: {description}\n"
                    f"Language context: {language}\n"
                    "Analyze the maintenance issue in the image."
                ),
            },
        ]
        data = await self._complete_json(
            system=(
                "You are a property maintenance diagnostician. "
                "Use severity=minor if tenant can fix; serious if professional required."
            ),
            user_content=content,
            schema_hint=json.dumps(schema),
        )
        try:
            return DiagnosisResult.model_validate(data)
        except ValidationError:
            return self._fallback_diagnosis(description)

    # ── Deterministic fallbacks (demo / tests without API key) ────────────

    @staticmethod
    def _fallback_intent(message: str) -> IntentClassification:
        lower = message.lower()
        if any(w in lower for w in ("leak", "broken", "repair", "fix", "not working", "kaputt")):
            intent = "maintenance"
            urgency = "high" if "leak" in lower or "emergency" in lower else "medium"
        elif any(w in lower for w in ("noise", "neighbor", "complaint", "loud")):
            intent = "complaint"
            urgency = "low"
        else:
            intent = "admin"
            urgency = "low"

        from app.schemas.llm_outputs import TenantIntent

        return IntentClassification(
            intent=TenantIntent(intent),
            confidence=0.6,
            summary=message[:200],
            urgency=urgency,  # type: ignore[arg-type]
        )

    @staticmethod
    def _fallback_diagnosis(description: str) -> DiagnosisResult:
        lower = description.lower()
        serious = any(w in lower for w in ("leak", "flood", "gas", "fire", "spark"))
        category = IssueCategory.plumbing if "water" in lower or "leak" in lower else IssueCategory.general
        return DiagnosisResult(
            category=category,
            severity="serious" if serious else "minor",
            urgency="high" if serious else "medium",
            diagnosis=f"Automated assessment: {description[:300]}",
            estimated_cost_min=50 if serious else None,
            estimated_cost_max=200 if serious else None,
            self_help_steps=["Turn off local water supply", "Place a bucket under the leak"]
            if not serious
            else [],
            requires_professional=serious,
        )


# Module singleton — replaceable in tests
claude_service = ClaudeService()
