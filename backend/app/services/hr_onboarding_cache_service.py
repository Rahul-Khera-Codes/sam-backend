from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from typing import Any

import redis.asyncio as redis

from app.core.config import settings
from app.core.supabase import supabase_admin

logger = logging.getLogger(__name__)

CACHE_SCHEMA_VERSION = "v1"
_QUERY_WHITESPACE_PATTERN = re.compile(r"\s+")
_redis_client: redis.Redis | None = None


def normalize_cache_query(question: str) -> str:
    return _QUERY_WHITESPACE_PATTERN.sub(" ", question.strip().lower())


def _get_redis_client() -> redis.Redis | None:
    global _redis_client
    if not settings.hr_onboarding_cache_enabled or not settings.valkey_url:
        return None
    if _redis_client is None:
        _redis_client = redis.from_url(
            settings.valkey_url,
            encoding="utf-8",
            decode_responses=True,
            client_name=settings.hr_onboarding_cache_client_name,
        )
    return _redis_client


async def get_hr_policy_document_fingerprint(business_id: str) -> str | None:
    try:
        result = await asyncio.to_thread(
            lambda: supabase_admin.table("business_documents")
            .select("id,name,category,status,embedding_status,embedded_at,created_at")
            .eq("business_id", business_id)
            .eq("document_scope", "hr_onboarding")
            .eq("status", "published")
            .eq("embedding_status", "ready")
            .order("id")
            .execute()
        )
    except Exception as exc:
        logger.warning("Unable to build HR onboarding cache fingerprint: %s", exc)
        return None

    documents = getattr(result, "data", None) or []
    fingerprint_payload = json.dumps(documents, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(fingerprint_payload.encode("utf-8")).hexdigest()


def build_hr_onboarding_cache_key(
    *,
    business_id: str,
    question: str,
    document_id: str | None,
    category: str | None,
    document_fingerprint: str,
    channel: str,
) -> str:
    key_payload = {
        "business_id": business_id,
        "category": category or "",
        "channel": channel,
        "document_fingerprint": document_fingerprint,
        "document_id": document_id or "",
        "question": normalize_cache_query(question),
        "schema": CACHE_SCHEMA_VERSION,
    }
    digest = hashlib.sha256(
        json.dumps(key_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return f"hr:onboarding:{channel}:{business_id}:{digest}"


async def get_cached_hr_onboarding_response(cache_key: str) -> dict[str, Any] | None:
    client = _get_redis_client()
    if client is None:
        return None

    try:
        cached = await client.get(cache_key)
    except Exception as exc:
        logger.warning("Valkey HR onboarding cache read failed: %s", exc)
        return None

    if not cached:
        return None
    try:
        payload = json.loads(cached)
    except json.JSONDecodeError:
        logger.warning("Valkey HR onboarding cache contained invalid JSON for key %s", cache_key)
        return None
    if not isinstance(payload, dict):
        return None
    return payload


async def set_cached_hr_onboarding_response(
    cache_key: str,
    *,
    answer: str,
    sources: list[dict[str, Any]],
) -> None:
    client = _get_redis_client()
    if client is None or not answer.strip():
        return

    payload = {
        "answer": answer,
        "sources": sources,
        "schema": CACHE_SCHEMA_VERSION,
    }
    try:
        await client.setex(
            cache_key,
            settings.hr_onboarding_cache_ttl_seconds,
            json.dumps(payload, ensure_ascii=True, separators=(",", ":")),
        )
    except Exception as exc:
        logger.warning("Valkey HR onboarding cache write failed: %s", exc)
