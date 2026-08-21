"""
Semantic memory for John (HR onboarding): durable facts distilled from past
conversations, distinct from the document-chunk RAG in
hr_document_embedding_service.py (which holds uploaded HR policy content, not
learned conversational facts).

Design, per product decision: no embeddings/similarity search — facts are
retrieved by plain recency. Voice sessions summarize once at session end
(agent/supabase_helpers.py, mirrored here only for the text-widget path).
The text widget has no "session end" signal (stateless request/response), so
it summarizes incrementally: every SUMMARIZE_EVERY_N_MESSAGES new messages,
distill just the new slice since the last checkpoint (tracked by
hr_onboarding_conversations.facts_summarized_through) into facts.
"""

from __future__ import annotations

import json
import logging
import os

from app.core.supabase import supabase_admin

logger = logging.getLogger(__name__)

FACTS_TABLE = "hr_onboarding_semantic_facts"
CONVERSATIONS_TABLE = "hr_onboarding_conversations"
MESSAGES_TABLE = "hr_onboarding_messages"
SUMMARIZATION_MODEL = "gpt-4o-mini"

# Skip summarizing trivial exchanges, and only re-check every few turns —
# matches the "after a certain number of turns, condense into semantic
# memory" behavior this was originally scoped for.
MIN_MESSAGES_FOR_SUMMARY = 4
SUMMARIZE_EVERY_N_MESSAGES = 6


def fetch_recent_facts(*, business_id: str, limit: int = 12) -> list[str]:
    """Most recently remembered facts for this business — plain recency
    fetch, no embeddings. Empty on any failure."""
    try:
        rows = (
            supabase_admin.table(FACTS_TABLE)
            .select("fact_text")
            .eq("business_id", business_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        data = getattr(rows, "data", None) or []
        return [r["fact_text"] for r in data if r.get("fact_text")]
    except Exception as e:
        logger.warning("Failed to fetch HR onboarding semantic facts: %s", e)
        return []


def format_semantic_context(facts: list[str]) -> str:
    """Render recalled facts as a message block. Empty string when there's
    nothing to recall — self-omitting, same convention as the voice agents'
    procedural-memory {context} slot."""
    if not facts:
        return ""
    bullets = "\n".join(f"- {f}" for f in facts)
    return f"What you remember from past conversations with this business:\n{bullets}"


async def _summarize_messages(messages: list[dict], *, business_name: str) -> list[str]:
    """Extract durable facts from a slice of conversation via a cheap model.
    Never raises — returns [] on any failure."""
    openai_key = os.getenv("OPENAI_API_KEY")
    if not openai_key:
        logger.warning("OPENAI_API_KEY not set — skipping semantic memory summarization")
        return []
    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=openai_key)
        transcript_text = "\n".join(f"{m['role'].upper()}: {m['content']}" for m in messages)
        response = await client.chat.completions.create(
            model=SUMMARIZATION_MODEL,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": (
                        f"You extract durable facts worth remembering from a conversation with {business_name}. "
                        "Only extract genuinely reusable preferences, decisions, or repeatedly-relevant "
                        "information (a stated preference, a policy detail, a contact, a recurring need). "
                        "Do not extract one-off questions, small talk, or anything unlikely to matter again. "
                        "Each fact must be a short, standalone sentence understandable without the transcript. "
                        "Return JSON: {\"facts\": [\"...\", ...]} — empty array if nothing durable."
                    ),
                },
                {"role": "user", "content": transcript_text},
            ],
        )
        result = json.loads(response.choices[0].message.content or "{}")
        facts = result.get("facts") or []
        return [str(f).strip() for f in facts if str(f).strip()]
    except Exception as e:
        logger.warning("HR onboarding semantic memory summarization failed: %s", e)
        return []


def _store_facts(
    *,
    business_id: str,
    source_conversation_id: str | None,
    created_by_user_id: str | None,
    facts: list[str],
) -> None:
    """Persist newly extracted facts, skipping verbatim duplicates of
    existing facts for this business. Never raises."""
    if not facts:
        return
    try:
        existing_rows = (
            supabase_admin.table(FACTS_TABLE)
            .select("fact_text")
            .eq("business_id", business_id)
            .order("created_at", desc=True)
            .limit(50)
            .execute()
        )
        existing = {
            (r.get("fact_text") or "").strip().lower()
            for r in (getattr(existing_rows, "data", None) or [])
        }
        new_rows = [
            {
                "business_id": business_id,
                "source_conversation_id": source_conversation_id,
                "created_by_user_id": created_by_user_id,
                "fact_text": fact,
            }
            for fact in facts
            if fact.strip().lower() not in existing
        ]
        if new_rows:
            supabase_admin.table(FACTS_TABLE).insert(new_rows).execute()
            logger.info(
                "Stored %d new HR onboarding semantic fact(s) for business %s",
                len(new_rows), business_id,
            )
    except Exception as e:
        logger.warning("Failed to store HR onboarding semantic facts: %s", e)


async def maybe_summarize_conversation(
    *,
    conversation_id: str,
    business_id: str,
    new_total_message_count: int,
) -> None:
    """Fire-and-forget: if this text conversation just crossed another
    SUMMARIZE_EVERY_N_MESSAGES checkpoint, distill only the messages since
    the last checkpoint into durable facts. Call after persisting a turn;
    never raises and never blocks the response already sent to the user."""
    if new_total_message_count < MIN_MESSAGES_FOR_SUMMARY:
        return
    if new_total_message_count % SUMMARIZE_EVERY_N_MESSAGES != 0:
        return
    try:
        convo_rows = (
            supabase_admin.table(CONVERSATIONS_TABLE)
            .select("facts_summarized_through,user_id")
            .eq("id", conversation_id)
            .limit(1)
            .execute()
        )
        convo_data = getattr(convo_rows, "data", None) or []
        if not convo_data:
            return
        watermark = convo_data[0].get("facts_summarized_through") or 0
        if watermark >= new_total_message_count:
            return

        new_message_rows = (
            supabase_admin.table(MESSAGES_TABLE)
            .select("role,content")
            .eq("conversation_id", conversation_id)
            .gte("sequence_order", watermark)
            .order("sequence_order")
            .execute()
        )
        messages = [
            {"role": m["role"], "content": m["content"]}
            for m in (getattr(new_message_rows, "data", None) or [])
        ]
        if not messages:
            return

        business_rows = (
            supabase_admin.table("businesses").select("name").eq("id", business_id).limit(1).execute()
        )
        business_data = getattr(business_rows, "data", None) or []
        business_name = (business_data[0].get("name") if business_data else None) or "your company"

        facts = await _summarize_messages(messages, business_name=business_name)
        _store_facts(
            business_id=business_id,
            source_conversation_id=conversation_id,
            created_by_user_id=convo_data[0].get("user_id"),
            facts=facts,
        )

        supabase_admin.table(CONVERSATIONS_TABLE).update({
            "facts_summarized_through": new_total_message_count,
        }).eq("id", conversation_id).execute()
    except Exception as e:
        logger.warning(
            "Failed to run incremental semantic-memory summarization for conversation %s: %s",
            conversation_id, e,
        )
