"""
Episodic memory (persisted history) for John's HR onboarding text widget.

Voice sessions (Remi, John) persist their own transcripts directly from the
LiveKit agent process (see agent/supabase_helpers.py's
_create_voice_conversation / _finalize_voice_conversation). This module is the
text-widget equivalent, called from hr_onboarding_chat_service.py on every
request since the widget is otherwise stateless.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.core.supabase import supabase_admin
from app.services.token_budget_service import ConversationTurn

logger = logging.getLogger(__name__)

CONVERSATIONS_TABLE = "hr_onboarding_conversations"
MESSAGES_TABLE = "hr_onboarding_messages"


def get_or_create_conversation(
    *,
    conversation_id: str | None,
    business_id: str,
    user_id: str,
) -> str | None:
    """Return conversation_id unchanged if given, otherwise create a new text
    conversation row. Returns None only if creation fails — callers should
    treat that as "answer the question, just skip persistence for this turn"."""
    if conversation_id:
        return conversation_id
    try:
        row = (
            supabase_admin.table(CONVERSATIONS_TABLE)
            .insert({
                "business_id": business_id,
                "user_id": user_id,
                "channel": "text",
            })
            .execute()
        )
        data = getattr(row, "data", None) or []
        return data[0]["id"] if data else None
    except Exception as e:
        logger.warning("Failed to create HR onboarding text conversation: %s", e)
        return None


def fetch_conversation_history(*, conversation_id: str, business_id: str) -> list[ConversationTurn]:
    """Prior turns for this conversation, oldest first. Empty on any failure —
    a working-memory miss just means the model answers without prior context,
    not a broken response."""
    try:
        rows = (
            supabase_admin.table(MESSAGES_TABLE)
            .select("role,content")
            .eq("conversation_id", conversation_id)
            .eq("business_id", business_id)
            .order("sequence_order")
            .execute()
        )
        data = getattr(rows, "data", None) or []
        return [{"role": r["role"], "content": r["content"]} for r in data]
    except Exception as e:
        logger.warning("Failed to load HR onboarding conversation history %s: %s", conversation_id, e)
        return []


def append_turn(
    *,
    conversation_id: str,
    business_id: str,
    prior_turn_count: int,
    question: str,
    answer: str,
) -> None:
    """Persist the just-completed user question + assistant answer. Fire-and-forget
    from the caller's perspective — never raises, a persistence failure must not
    affect the response already sent to the user."""
    try:
        supabase_admin.table(MESSAGES_TABLE).insert([
            {
                "conversation_id": conversation_id,
                "business_id": business_id,
                "role": "user",
                "content": question,
                "sequence_order": prior_turn_count,
            },
            {
                "conversation_id": conversation_id,
                "business_id": business_id,
                "role": "assistant",
                "content": answer,
                "sequence_order": prior_turn_count + 1,
            },
        ]).execute()
        supabase_admin.table(CONVERSATIONS_TABLE).update({
            "last_message_at": datetime.now(timezone.utc).isoformat(),
            "message_count": prior_turn_count + 2,
        }).eq("id", conversation_id).execute()
    except Exception as e:
        logger.warning("Failed to persist HR onboarding text turn for %s: %s", conversation_id, e)


def delete_conversation(*, conversation_id: str, business_id: str) -> bool:
    """Hard-delete one conversation (messages cascade via FK). Returns False
    if no matching row existed for this business — callers should 404."""
    result = (
        supabase_admin.table(CONVERSATIONS_TABLE)
        .delete()
        .eq("id", conversation_id)
        .eq("business_id", business_id)
        .execute()
    )
    return bool(getattr(result, "data", None))


def delete_all_conversations(*, business_id: str) -> int:
    """Hard-delete every conversation for this business (messages cascade via
    FK). Returns the number of conversations removed."""
    result = (
        supabase_admin.table(CONVERSATIONS_TABLE)
        .delete()
        .eq("business_id", business_id)
        .execute()
    )
    return len(getattr(result, "data", None) or [])
