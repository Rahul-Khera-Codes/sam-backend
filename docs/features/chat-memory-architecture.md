# Chat memory architecture (Remi & John)

Tracked as Linear AIE-11 ("access previous chats"), which grew into a request
for a full memory architecture across Remi (Executive Assistant) and John (HR
Onboarding Assistant, internally still named "Ava" in some code/table
comments — the user-facing persona name is John).

## The four memory types, as scoped with the user

- **Procedural memory** — the system prompt. Lives in `EXECUTIVE_INSTRUCTIONS`
  (`agent/executive_agent.py`) and `JOHN_INSTRUCTIONS` (`agent/hr_onboarding_agent.py`),
  assembled fresh per session. No separate abstraction layer exists yet — see
  Phase 2 backlog.
- **Semantic memory** — durable facts about a user/business. Today this only
  exists as document-chunk RAG (`remi_document_chunks`, `hr_document_chunks` —
  pgvector, `text-embedding-3-small`, tenant-scoped). A distinct "facts
  distilled from conversations" table is Phase 2, not yet built.
- **Episodic memory** — persisted conversation history, browsable by the user.
  **This is what Phase 1 (below) actually ships.**
- **Working memory** — the active context window. OpenAI Realtime API sessions
  (used by both Remi and John's voice mode) manage this internally; there is
  no app-level turn array to intercept there. John's text widget is a
  stateless request/response API, so a token-bounded sliding window was built
  there instead (Phase 1).

## Why phased delivery

The ticket's literal scope is "access previous chats." `TODO.md` had already
flagged persistent chat history as zero-built and its own workstream, separate
from other polish items. The user agreed to phase: Phase 1 ships episodic
persistence + a history UI; semantic-memory distillation, a cross-component
token-budget governor, and a procedural-memory refactor are Phase 2.

## Identity model

Both Remi and John's chat UI are **staff-facing and authenticated** — a real
Supabase `auth.uid()`, same as everywhere else in the app. There is no
separate new-hire/candidate-facing chat surface; HR staff use John's page to
manage onboarding docs and preview what John would tell a new hire. So
episodic memory keys off `business_id` + `location_id` (nullable) + `user_id`,
exactly like every other tenant-scoped table in this codebase.

## Cost/latency constraint

The client has previously and explicitly pushed back on adding latency/cost to
the voice path ("people will not pay to use this when they can use ChatGPT for
free" — see `TODO.md` cost-analysis thread; the resulting audit concluded stay
on Realtime API, don't add a separate pipeline). Consequences for this
feature:
- Voice persistence only writes to Supabase — it never adds an LLM/embedding
  call to the live call.
- Any future summarization step (Phase 2) must run async, post-session, not
  mid-call.

## Phase 1 — what's implemented

### Data model
New migration `ai-employees-app/supabase/migrations/20260820000000_chat_memory_conversations.sql`:
`remi_conversations` / `remi_messages` and `hr_onboarding_conversations` /
`hr_onboarding_messages` — kept as separate table pairs per bot (matching how
`remi_document_chunks` / `hr_document_chunks` are already separate), rather
than one shared schema. RLS: any member of the business can read
(`user_roles` join), service role has full write access. The frontend reads
history directly via `supabase-js`, same convention as other direct-read
tables — no new backend read endpoints were added.

### Voice persistence (Remi, John)
`agent/supabase_helpers.py` gained two reusable helpers:
`_create_voice_conversation` (called once at session start) and
`_finalize_voice_conversation` (bulk-inserts the in-memory turn log + closes
out the conversation row). Both `agent/executive_agent.py` and
`agent/hr_onboarding_agent.py` wire these up around a `conversation_item_added`
listener (same shape as the phone agent's transcript capture in
`agent/agent.py:1727-1772`) and a `participant_disconnected` handler that
triggers finalization. Persistence failures are caught and logged — they never
affect the live call.

### Text persistence + working memory (John's text widget)
- `backend/app/services/token_budget_service.py` — `tiktoken`-based
  `count_tokens` / `window_to_budget`. Drops the oldest user/assistant pair at
  a time once a conversation's history exceeds `HISTORY_TOKEN_BUDGET` (2,500
  tokens, set in `hr_onboarding_chat_service.py`). This is the literal
  "shrink by removing the oldest human+AI pair" behavior, applied where it's
  actually actionable — a stateless request we control — rather than inside
  the Realtime session.
- `backend/app/services/hr_onboarding_conversation_memory_service.py` —
  `get_or_create_conversation`, `fetch_conversation_history`, `append_turn`
  against `hr_onboarding_conversations` / `hr_onboarding_messages`.
- `answer_onboarding_question` and `stream_onboarding_question` in
  `hr_onboarding_chat_service.py` both now accept `user_id` and
  `conversation_id`, resolve/create the conversation, inject the windowed
  history as real chat messages between the system prompt and the
  RAG-grounded question, and persist the turn after answering.
- **Cache tradeoff**: the service's existing exact-match and semantic response
  caches are skipped entirely (both read and write) whenever a conversation
  already has history — a cached answer computed without conversation context
  isn't safe to reuse for a follow-up. First messages in a new conversation
  still hit the cache as before, so the FAQ cost-saving behavior is preserved
  for the common case.
- `OnboardingChatRequest`/`OnboardingChatResponse` (`backend/app/schemas/documents.py`)
  and the `/hr/onboarding/chat` + `/hr/onboarding/chat/stream` routes
  (`backend/app/routers/hr.py`) thread `conversation_id` through; the stream's
  `done` SSE event carries it back so the client can keep threading the same
  conversation.

### Frontend
- `src/hooks/useChatHistory.ts` — direct Supabase reads (RLS-scoped) for
  either bot's conversations/messages.
- `src/components/chat/ChatHistoryPanel.tsx` — shared slide-out `Sheet`
  panel: conversation list (date, voice/text icon, message count) → read-only
  transcript view. No "continue this conversation" action in Phase 1.
- Wired into `src/pages/dashboard/ExecutiveAgent.tsx` (History button next to
  End session) and `src/pages/dashboard/hr/HrOnboarding.tsx` (History icon
  button in John's chat card header). John's text widget now threads
  `conversation_id` through `askQuestion` via `streamHrOnboardingAgent`'s new
  `onDone`/`conversationId` params.

## Phase 1 follow-up fixes & additions

After initial delivery, user testing surfaced three issues, all fixed within Phase 1 (not deferred):

1. **Remi's history panel went stale until a page reload.** `useChatHistory`'s
   fetch only ran once on mount, but `ChatHistoryPanel` is mounted once and
   toggled via the `open` prop — so a session that just ended never showed up
   until a full reload. Fixed by refetching in `ChatHistoryPanel` every time
   `open` becomes `true` (`src/components/chat/ChatHistoryPanel.tsx`).
2. **John's history trigger was an unlabeled 28px icon button** — functional,
   but easy to miss. Restyled to a labeled pill ("History" + icon) matching
   Remi's affordance (`src/pages/dashboard/hr/HrOnboarding.tsx`).
3. **John's text widget only persisted the final LLM-answered turn** — casual
   chit-chat ("Hi"), cache hits, "couldn't find that" answers, and
   rate-limited/guardrail-blocked responses all short-circuited before the
   original `append_turn` call. Fixed by resolving `conversation_id` and
   fetching `history` at the top of both `answer_onboarding_question` and
   `stream_onboarding_question`, defining a local `_persist(answer_text)`
   closure, and calling it at every return/yield point that produces a
   user-visible answer (`backend/app/services/hr_onboarding_chat_service.py`).
   The one exception, by design: the outermost catch-all `except Exception`
   (unexpected server errors) is not persisted — it's an infrastructure
   failure, not a conversational exchange.
   - Side effect flagged at the time, since fixed (see "Cache bypass was too
     broad" below): this made the cache-bypass condition (`has_history`) true
     after *any* prior turn, not just a real contextual follow-up.

## Delete history (both bots)

Per-conversation delete and "clear all" for a business, hard delete (no
retention/soft-delete requirement — matches the earlier decision that there's
no compliance need to keep records around).

- **Backend**: `backend/app/services/remi_conversation_memory_service.py`
  (new) and `hr_onboarding_conversation_memory_service.py`'s added
  `delete_conversation` / `delete_all_conversations` — both delete rows from
  `*_conversations` via `supabase_admin` (service role, bypasses RLS);
  `*_messages` cascade-delete automatically via the `ON DELETE CASCADE` FK.
  New routes: `DELETE /executive/conversations/{id}`,
  `DELETE /executive/conversations` (query param `business_id`), and the
  equivalent `DELETE /hr/onboarding/conversations/{id}` /
  `DELETE /hr/onboarding/conversations`, all behind `verify_business_access`.
- **Frontend**: `deleteRemiConversation` / `deleteAllRemiConversations` /
  `deleteHrOnboardingConversation` / `deleteAllHrOnboardingConversations` in
  `voiceAgentApi.ts`. `ChatHistoryPanel` gained a per-row delete (`Trash2`,
  visible on hover) and a "Clear all" header action, both behind an
  `AlertDialog` confirmation (matching the existing bulk-document-delete
  pattern in `HrOnboarding.tsx`) — no direct supabase-js deletes, consistent
  with this repo's convention that mutations go through the backend API while
  only reads go direct.

## Phase 2 — session 1: procedural memory & guardrails efficiency (John only)

User report: sending "Hey John" was slow, and inconsistently returned either a
guardrails "safety violated" block or a "couldn't find it in the HR policy
documents" answer — for a plain greeting.

**Root cause, confirmed by tracing both fast-path layers John already had:**
`_answer_casual_message`'s `_GREETING_PATTERN` is fully anchored
(`^(hi|hello|hey|...)[.!?\s]*$`), so it only matches a *bare* greeting —
"Hey John" fails to match because of the trailing name. That sends it through
full RAG retrieval (grabbing policy chunks unrelated to a greeting), a real
LLM generation call grounded on those irrelevant chunks, and the full output
guardrails stack including a 7B-parameter LlamaGuard model run against
whatever nonsense got generated — slow, and non-deterministic about whether
that nonsense trips the safety check.

**Fixes (both in `hr_onboarding_chat_service.py` /
`hr_onboarding_guardrails_service.py`, John only — Remi is voice-only via
OpenAI Realtime and has no equivalent text guardrails pipeline):**

1. **Procedural memory (instant-response fast path).** Added `_strip_address()`,
   which removes a leading/trailing direct address to "John" before matching
   the existing casual-message patterns (greeting/thanks/goodbye/capability).
   "Hey John", "Hi John!", "John, thanks", and bare "John" now all hit the
   canned-reply path — zero RAG, zero LLM call, zero guardrails, response is
   instant. Real questions that happen to name John ("Hey John, what's the
   PTO policy?") are unaffected and still go through full retrieval, verified
   with a case-by-case check against both greeting-style and real-question
   inputs.
2. **Guardrails efficiency for real (non-greeting) questions.** John already
   had a second, independent fast path: `_is_fast_safe_hr_question` /
   `_is_safe_grounded_policy_exchange` skip the heavy ML validators (DetectPII,
   LlamaGuard7B) for input/output when the question matches
   `_SAFE_HR_POLICY_QUESTION_PATTERN` — but that keyword list was narrow
   (missing badge, direct deposit, dress code, remote work, layoffs, parking,
   background checks, overtime, 401k, and more), so many legitimate onboarding
   questions were still needlessly hitting the slow path. Widened the pattern
   with a much broader, categorized keyword list (time off, benefits, pay,
   employment lifecycle, schedule/logistics, compliance/conduct, IT/equipment).
   This doesn't weaken safety: the fast-path bypass only applies *after* the
   existing PII/profanity/abuse/jailbreak heuristic checks already pass, and
   for output specifically only after RAG genuinely retrieved grounding
   `reference` text — widening the keyword list only changes which
   *legitimately-grounded* exchanges skip the expensive ML re-check on top of
   those cheaper checks.
   - Not done (documented as a further idea, not implemented): a
     confidence-based alternative to the keyword allowlist — using the
     retrieval step's own `similarity`/`reranker_score` as the "is this
     genuinely grounded" signal instead of/alongside keyword matching, since
     an allowlist is inherently incomplete no matter how wide. Would need
     plumbing match scores into `validate_onboarding_assistant_output`, which
     doesn't currently receive them.
3. **Cache bypass was too broad.** User report: repeated identical questions
   within the same John chat weren't hitting the response cache. Root cause:
   the Phase 1 follow-up fix (item 3 above) made `skip_cache` (previously
   named `has_history`) true whenever a conversation had *any* prior turn at
   all, including a bare "Hi" — so caching effectively turned off for the rest
   of any multi-turn conversation, not just for genuinely context-dependent
   follow-ups. Fixed with `_looks_context_dependent(question)`: a
   referentially-started question ("what about", "and", "that", "it", ...)
   is treated as context-dependent and still bypasses the cache; a
   well-formed, self-contained question — even an exact repeat, even deep
   into a long conversation — now correctly hits the cache regardless of how
   much history exists, since the cache key is already an exact hash of the
   question text and doesn't need conversation context to serve it correctly.
   Verified with a direct simulation (non-empty history + repeated question →
   cache used; non-empty history + "What about dental?" → cache still
   bypassed).
   - **Follow-up fix**: the heuristic initially also auto-flagged any
     question ≤3 words as context-dependent (to catch bare "It?"/"That one").
     That caught the UI's own quick-prompt suggestion "Summarize Policy
     policies" (exactly 3 words) as a false positive, permanently bypassing
     its cache once a conversation had any history — the *opposite* of what
     the cache is for, since quick-prompt buttons are exactly the case of a
     genuinely repeated, self-contained question. Word count doesn't actually
     distinguish "What about dental?" from "Summarize Policy policies" (both
     3 words) — only the referential-start pattern does. Removed the
     length-based fallback entirely per the user's call; a bare single word
     like "Dental?" with nothing else is now a small accepted residual risk
     (falls through to a fresh, uncached answer rather than being
     auto-flagged) rather than penalizing every short legitimate command.
   - Separately confirmed the *input-validation* cache
     (`get_cached_hr_onboarding_validation_pass` /
     `set_cached_hr_onboarding_validation_pass` in
     `hr_onboarding_cache_service.py`, used by `_validate_user_input_traced`)
     already existed and worked correctly before this session — timed
     directly: 13ms cold, 1ms on a cache hit for the same text. No change
     needed there; this was already "skip validation for a query that's
     already been validated" for the exact-repeat case.

## Phase 2 — semantic memory (implemented, both bots)

Scoped down from the full backlog by user decision: build semantic memory +
summarization + injection only; defer the token-budget governor, the
procedural-memory module refactor, and resumable-conversation UX (see
trimmed backlog below).

### Data model
New migration `20260821000000_chat_memory_semantic_facts.sql`:
`remi_semantic_facts` / `hr_onboarding_semantic_facts` — separate per bot,
same convention as episodic memory. Columns: `business_id`, `location_id`
(nullable), `source_conversation_id` (nullable, `ON DELETE SET NULL` — a fact
survives even if its source conversation is later deleted via the history
delete feature), `created_by_user_id`, `fact_text`, `created_at`. **No
embedding column** — per product decision, retrieval is a plain recency
query, not vector similarity search, since fact counts per business are
expected to stay small. Also added `hr_onboarding_conversations.facts_summarized_through`
(integer watermark, default 0) — text-only; voice conversations don't use it.
RLS mirrors the episodic tables (members read, service role full access) for
consistency, though nothing reads these from the frontend in this phase — no
UI was built for facts.

### Voice (Remi + John) — `agent/supabase_helpers.py`
Four new shared functions, parameterized by facts table name (same pattern as
`_create_voice_conversation`/`_finalize_voice_conversation`):
- `_summarize_conversation_to_facts(messages, business_name)` — mirrors
  `agent/agent.py`'s existing `_generate_summary` pattern exactly (lazy
  `AsyncOpenAI` import, `gpt-4o-mini`, JSON response format). Skips sessions
  under `MIN_MESSAGES_FOR_SEMANTIC_SUMMARY` (4) before even calling out.
- `_fetch_recent_semantic_facts` — plain recency `SELECT`, no embeddings.
- `_format_semantic_context(facts)` — renders facts as a bulleted block,
  self-omitting (empty string) when there's nothing recalled, matching
  `prompt_builder.py`'s block-concatenation convention.
- `_store_semantic_facts` — dedupes against the business's most recent 50
  facts (case/whitespace-insensitive exact match) before inserting.

Wiring: `EXECUTIVE_INSTRUCTIONS` already had a real, unused `{context}`
placeholder at the end of its template (`agent/executive_agent.py:223`,
previously always called with `context=""`) — this was clearly meant for
exactly this. `JOHN_INSTRUCTIONS` had no equivalent slot; added one. Both
agents now fetch recent facts synchronously at session start (same cost as
the existing `_fetch_business` call right next to it — no embedding call, so
negligible added latency) and fill `{context}` with them. Both agents'
finalize functions (`_finalize_remi_conversation` / `_finalize_john_conversation`)
now also distill and store facts *after* persisting the transcript — async,
fire-and-forget, only after the session has already ended, so **zero added
latency on the live call**, matching the cost/latency constraint from Phase 1.

### Text (John only) — `backend/app/services/hr_onboarding_semantic_memory_service.py`
The text widget has no "session end" signal (stateless request/response), so
it can't reuse the voice bots' end-of-session trigger. Instead it summarizes
*incrementally*: `maybe_summarize_conversation` runs (fire-and-forget, via
`asyncio.ensure_future` inside the existing `_persist` closure — so every
call site that already persists a turn automatically gets this check for
free) after every turn, and actually does work only when the conversation's
total message count crosses a multiple of `SUMMARIZE_EVERY_N_MESSAGES` (6,
i.e. every 3 exchanges) — this is the literal "after a certain number of
turns, condense into semantic memory" behavior from the original spec. It
reads only the *new* messages since `facts_summarized_through`, extracts
facts via the same `gpt-4o-mini` prompt as the voice path, stores them, and
advances the watermark — verified idempotent (re-running at the same
watermark doesn't reprocess or duplicate).

Recalled facts are fetched fresh on every request (same as `history`) and
injected as an extra system message — `_facts_message(facts_context)` —
placed right after the existing system prompt and before working-memory
history in both `_json_answer_messages` and `_stream_answer_messages`. The
original system prompt text is unchanged.

### Verification
All of the above was tested directly against the real (not mocked) Supabase
project and OpenAI API inside the running containers, with cleanup after:
- Fact store → fetch → format round-trip, plus dedupe (storing the same fact
  twice produced one row, not two).
- Full incremental-summarization run against a real conversation + messages:
  correct fact extracted, watermark advanced to the right value, and a
  second call at the same watermark did not reprocess or duplicate.
- The agent-side `_summarize_conversation_to_facts` correctly extracted a
  stated preference from a synthetic transcript and correctly ignored an
  unrelated one-off question in the same transcript.
- Both voice agent workers (`sam-executive-agent`, `sam-hr-onboarding-agent`)
  and the backend registered/started cleanly with the new code (no
  import/syntax errors); existing test suite still passes.

## Phase 2 backlog (trimmed — still not built)

- Cross-component token-budget governor: today's budget only covers John's
  text-widget history window; a real governor would also account for the
  system prompt, RAG context, and now the recalled semantic facts against the
  active model's context window.
- Procedural-memory module refactor: pull `EXECUTIVE_INSTRUCTIONS`/`JOHN_INSTRUCTIONS`
  into a shared, explicitly-named "procedural memory" module rather than
  inline constants. (Separately noted: John's voice handles casual chit-chat
  via an LLM-instruction section in its prompt, not a deterministic fast path
  like the text widget's `_answer_casual_message` — a behavioral asymmetry
  worth fixing if this refactor happens.)
- "Continue this conversation" UX for John's text widget — now more useful
  than before since semantic memory carries context across conversations
  automatically, but still not built.
- Voice session rehydration beyond what's already shipped — today's
  `{context}` injection *is* a form of rehydration (recalled facts at session
  start); anything beyond that (e.g. resuming mid-transcript) is still
  unbuilt.

## Known pre-existing infra fragility (discovered, not fixed — out of scope)

Two unrelated startup-reliability issues surfaced while rebuilding
`sam-backend` during this work, neither caused by any change in this feature:
- `guardrails-ai`'s import chain triggers a runtime NLTK download (`punkt`)
  with no apparent timeout — a stalled connection can hang the entire API
  server indefinitely at "Waiting for application startup." Worked around
  once by manually seeding `/root/nltk_data`, but that fix doesn't survive a
  full image rebuild. Should be baked into the Docker image at build time.
- On a later restart, two Guardrails Hub validators (`ProfanityFree`,
  `UnusualPrompt`) failed to load ("validators missing from runtime"),
  leaving only `DetectPII`/`LlamaGuard7B` active for John — looks like the
  same class of network-dependent initialization issue. Not investigated
  further; worth a look if guardrails coverage seems reduced after a restart.
