"""
Episodic memory read/delete helpers for Remi voice conversations.

Writes happen from the LiveKit agent process (agent/executive_agent.py via
agent/supabase_helpers.py) — the backend only needs delete support, since
history reads go straight from the frontend to Supabase via RLS.
"""

from __future__ import annotations

from app.core.supabase import supabase_admin

CONVERSATIONS_TABLE = "remi_conversations"


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
