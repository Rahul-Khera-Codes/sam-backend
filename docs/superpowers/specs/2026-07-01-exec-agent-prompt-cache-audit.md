# Exec Agent — Prompt Cache Audit (Observability)
**Date:** 2026-07-01
**Branch:** `feature/exec-agent-improvements`
**Status:** Spec approved — pending implementation

---

## Why

`docs/executive-agent-cost-analysis.md` identified prompt caching as the single check that determines the rest of the cost strategy: if OpenAI's Realtime API is actually hitting cache on our system prompt, real-world cost is **$0.05–0.10/min**; if not, it's **$0.18–0.46/min**, and a separate STT+LLM+TTS pipeline becomes a clear 3–9x win instead of a wash. We don't currently log anything that would tell us which one we're in — this adds that observability, nothing else.

---

## Phase 1 — Verified (installed package, this container)

- `agent/requirements.txt` pins `livekit-agents[openai,liveavatar]~=1.4`, but the container has **1.6.4** installed — worth a separate look later (out of scope here, flagging only).
- `agent/executive_agent.py:1061` constructs `RealtimeModel(voice="marin", temperature=0.9)` — `truncation` is never passed, so it defaults to `None` (OpenAI's server-side default), confirmed by reading `realtime_model.py` in the installed package.
- OpenAI's Realtime API reports cached-token counts per response on `RealtimeResponseUsage.input_token_details.cached_tokens` (confirmed via `openai` SDK 2.44.0 type definitions installed in the container).
- LiveKit's `AgentSession` already aggregates this into a running cumulative total via `ModelUsageCollector`, exposed as `session.usage` (a property, `AgentSessionUsage.model_usage: list[ModelUsage]`) and re-emitted after every turn as the `session_usage_updated` event (confirmed in `agent_activity.py:1640-1645`). `metrics_collected` is the older event for this — deprecated in favor of `session_usage_updated`, per a warning in `agent_session.py:518-521`.
- No existing hook in either `agent.py` or `executive_agent.py` listens to either event today — zero cache-hit visibility currently exists.

---

## Phase 2 — Spec

### File changed
Only `agent/executive_agent.py`. Pure observability — no behavior change, no other file touched.

### Change
After `session = AgentSession(...)` (L1060), add a `session_usage_updated` listener that logs the cumulative input-token / cached-token counts for the LLM usage bucket (which is where `RealtimeModelMetrics` land, per `ModelUsageCollector.collect`):

```python
def _log_cache_audit(ev):
    for u in ev.usage.model_usage:
        if u.type == "llm_usage" and u.input_tokens:
            hit_pct = u.input_cached_tokens / u.input_tokens * 100
            logger.info(
                "Cache audit — provider=%s model=%s input_tokens=%d cached=%d (%.0f%%) "
                "audio_in=%d cached_audio=%d",
                u.provider, u.model, u.input_tokens, u.input_cached_tokens, hit_pct,
                u.input_audio_tokens, u.input_cached_audio_tokens,
            )

session.on("session_usage_updated", _log_cache_audit)
```

This fires after every model turn with a running cumulative total — by the end of a live test call, the last "Cache audit" log line gives the real session-wide cache-hit percentage.

### How to read the result
- **`hit_pct` trending up toward 50–90% as the conversation continues** → caching is working, real cost is in the $0.05–0.10/min range, stick with Realtime and take the smaller Pass-1 wins (avatar default-off, idle timeout, `gpt-realtime-mini`).
- **`hit_pct` staying near 0% throughout** → caching isn't hitting, real cost is $0.18–0.46/min, and the separate STT+LLM+TTS pipeline (Option B in the cost-analysis doc) becomes a clear win worth the latency tradeoff.

### Impact
Log lines only — no billing, latency, or behavior change. Safe to ship immediately and remove later once the audit answer is known.

### Risk
None identified.

---

## Commit Plan

| # | Commit | Files |
|---|---|---|
| 1 | `feat(exec-agent): log prompt-cache hit rate to answer the cost-analysis audit` | `executive_agent.py` (`_log_cache_audit` + `session.on`) |
