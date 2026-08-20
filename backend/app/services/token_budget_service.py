"""
Token-budget utilities for chat working memory.

Seed of the cross-component token-budget governor planned for Phase 2 of the
chat-memory-architecture feature (see docs/features/chat-memory-architecture.md).
For now this only backs the HR onboarding text widget's sliding-window history —
Realtime voice sessions (Remi, John) manage their own context internally and
aren't governed by this module.
"""

from __future__ import annotations

import logging
from typing import TypedDict

import tiktoken

logger = logging.getLogger("hr-onboarding")

# gpt-4o-mini / gpt-4o share the o200k_base encoding. Falls back to a
# conservative estimate if tiktoken can't load it (e.g. no network on cold start).
_ENCODING_NAME = "o200k_base"


class ConversationTurn(TypedDict):
    role: str  # "user" | "assistant"
    content: str


def count_tokens(text: str) -> int:
    """Best-effort token count for a single string."""
    if not text:
        return 0
    try:
        encoding = tiktoken.get_encoding(_ENCODING_NAME)
        return len(encoding.encode(text))
    except Exception as e:
        logger.warning("tiktoken encoding failed, falling back to char/4 estimate: %s", e)
        return max(1, len(text) // 4)


def window_to_budget(turns: list[ConversationTurn], max_tokens: int) -> list[ConversationTurn]:
    """Return the most recent turns that fit within max_tokens, dropping the
    oldest user/assistant pair at a time when over budget — the sliding-window
    behavior for working memory. Turns are expected oldest-first; the return
    value preserves that order."""
    if not turns:
        return []

    kept: list[ConversationTurn] = list(turns)
    total = sum(count_tokens(t["content"]) for t in kept)

    while total > max_tokens and len(kept) > 2:
        # Drop the oldest pair together so history never gets left mid-turn
        # (a lone assistant reply with no preceding question).
        dropped = kept[:2]
        kept = kept[2:]
        total -= sum(count_tokens(t["content"]) for t in dropped)

    # If a single remaining pair still exceeds budget, keep it anyway —
    # truncating mid-message would corrupt context worse than going over.
    return kept
