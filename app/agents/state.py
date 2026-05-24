"""
Typed state for the PropFlow agent graph.

Kept intentionally flat — nodes read what they need and return partial updates.
Redis persists state between WhatsApp messages (phone number = session key).
"""
from __future__ import annotations

from typing import Optional, TypedDict


class PropFlowState(TypedDict, total=False):
    # ── Conversation context ───────────────────────────────────────────────
    phone_number: str
    tenant_id: str
    building_id: str
    landlord_id: str
    language: str

    # ── Current message ────────────────────────────────────────────────────
    message_text: Optional[str]
    message_type: str           # text | image | audio
    media_id: Optional[str]

    # ── Ticket data ────────────────────────────────────────────────────────
    ticket_id: Optional[str]
    intent: Optional[str]       # maintenance | complaint | admin | unknown
    category: Optional[str]     # plumbing | electrical | hvac | structural | appliance | general
    urgency: Optional[str]      # low | medium | high | emergency
    diagnosis: Optional[dict]   # full DiagnosisResult from Claude Vision

    # ── Flow control ───────────────────────────────────────────────────────
    current_node: str
    error: Optional[str]
    retry_count: int
