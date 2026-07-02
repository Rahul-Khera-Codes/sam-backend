# Executive Agent (Remi) — Cost Analysis

**Date:** 2026-07-01
**Trigger:** Sam pushed back on running cost ("what is the cheapest way to run the executive assistant. People will not pay to use this when they can use ChatGPT for free") — see `CLIENT_COMMS_LOG.md`, 2026-07-01 evening.
**Status:** Research complete. **Cache audit is now live** — `agent/executive_agent.py` logs a running cumulative cache-hit % on every turn (`docs/superpowers/specs/2026-07-01-exec-agent-prompt-cache-audit.md`, commit `9ca7475`). Run a real test session, then check: `docker compose logs sam-executive-agent | grep "Cache audit"`. Last line's `%` decides Option A vs Option B below.

All pricing below was web-searched on 2026-07-01 rather than pulled from memory, per CLAUDE.md Rule 2 ("web search before configuring / adding anything — stale knowledge causes silent bugs," extended here to cost decisions for the same reason).

---

## 1. Verified current architecture (this repo)

- **Every interaction — typed or spoken — runs through OpenAI's Realtime API** (`voice="marin"`, `agent/executive_agent.py:1061`). No branching by modality: a user who never touches the mic still pays Realtime audio-model rates for a pure text exchange.
- **LiveKit is Cloud-hosted**, not self-hosted — no `livekit-server` container in `docker-compose.yml`.
- **HeyGen avatar** is toggle-able (shipped session 55) but not yet default-off.
- **No idle-session timeout anywhere** in `executive_agent.py` — confirmed via grep. An abandoned open tab keeps the LiveKit room (and Realtime session) billing indefinitely.
- **No boundary on general Q&A** in `EXECUTIVE_INSTRUCTIONS` — every "ChatGPT-like" exchange adds unbounded tokens. Same root cause as Sam's "why pay vs. free ChatGPT" complaint, from two angles (cost + differentiation).

---

## 2. Option A — Stay on OpenAI Realtime (current), optimize it

| Lever | Current cost | Alternative | Effort |
|---|---|---|---|
| **Text/voice split** — route typed messages through a cheap text model, reserve Realtime for actual mic use | Realtime audio: $32/1M in, $64/1M out tokens → **$0.18–0.46/min real-world uncached** | GPT-4o-mini text: **$0.15/1M in, $0.60/1M out** — >100x cheaper per token for a text turn | Real architecture change — branch the model/session by modality |
| **Prompt caching audit** — OpenAI caches automatically for prompts ≥1024 tokens with an exact static prefix | — | Up to **90% off input cost**, no fee. Real-world Realtime cost **drops to $0.05–0.10/min with caching working** | Near-free — verify `session.truncation.retention_ratio` isn't resetting the cache every turn |
| **Cheaper Realtime model** — swap `voice="marin"` to `gpt-realtime-mini`/`gpt-4o-mini-realtime` | Full Realtime rates above | Meaningfully cheaper per-token, same architecture | One-line model swap to test; voice/personality needs re-verification |
| **Avatar default-off** | HeyGen LiveAvatar: LITE $0.10/min, Full $0.20/min | Toggle already built — just flip the default | Trivial |
| **Idle-session timeout** | Unbounded — abandoned tab keeps billing | Auto-disconnect after N minutes of no input | Small, isolated |
| **Scope down general Q&A** | Unbounded token growth per exchange | Bound what Remi will chat about vs. Gmail/Calendar/Appointments | Not code — the Sam conversation itself |
| **Self-host LiveKit** (ruled out) | Cloud: $0.01/min agent-session + ~$0.0004–0.0005/min WebRTC | Self-hosted server, no per-minute fee | Trades a small predictable cost for real ops burden — not worth it at current volume |

---

## 3. Option B — Switch to a separate STT + LLM + TTS pipeline (new research, this pass)

Instead of one model doing everything (speech-in → speech-out), split into three swappable stages: Speech-to-Text → text LLM → Text-to-Speech. This is the classic "cascaded pipeline" pattern, and LiveKit Agents supports it natively as an alternative to `RealtimeModel`.

### Component pricing (researched 2026-07-01)

| Stage | Provider | Price |
|---|---|---|
| **STT** | Deepgram Nova-3 (streaming) | **$0.0077/min** pay-as-you-go, $0.0065/min on Growth plan |
| **STT (alt)** | OpenAI Whisper / gpt-4o-transcribe | $0.006/min; gpt-4o-mini-transcribe ~$0.003/min |
| **LLM** | GPT-4o-mini (text) | $0.15/1M in, $0.60/1M out — same as Option A's text lever |
| **TTS** | Cartesia Sonic | **$0.02–0.06/min** depending on talkiness (cheapest well-known option) |
| **TTS (alt)** | ElevenLabs | $0.10–0.50/min depending on plan/model — 2–8x pricier than Cartesia |
| **TTS (alt)** | OpenAI TTS | **Not confirmed in this search** — check `platform.openai.com/pricing` directly before using a number here |

### All-in pipeline cost

Industry benchmark for a well-chosen stack (Deepgram Nova-3 + a cheap text LLM + Cartesia Sonic): **$0.05–0.15/min all-in**, roughly matching (STT $0.007 + TTS $0.02–0.06 + LLM token cost, which is small for typical turn lengths).

### Latency and quality tradeoff — this is the real cost, not just $/min

- **Realtime (S2S), current:** sub-500ms latency, natural prosody (the model operates directly on audio).
- **Cascaded pipeline:** 550–950ms typical, up to 1.4–1.7s in production median for some stacks — because audio has to fully transcribe, then the LLM has to finish generating, then TTS has to synthesize, sequentially. Noticeably less snappy in a live conversation.
- **What you gain in exchange:** full flexibility to swap any component independently (cheaper/vertical STT, a different LLM if a better one ships, brand-cloned TTS voice), and per-stage observability/debugging. Not locked to one vendor.

### The actual comparison that matters for us

| Scenario | Realtime (Option A) | Pipeline (Option B) |
|---|---|---|
| Realtime **uncached** (if prompt caching isn't working) | $0.18–0.46/min | $0.05–0.15/min → **pipeline wins clearly, 3–9x cheaper** |
| Realtime **cached** (if prompt caching is working) | $0.05–0.10/min | $0.05–0.15/min → **roughly a wash, pipeline may even lose** |

**This is the key finding: whether switching to a pipeline is worth it depends entirely on whether our prompt caching is actually working today.** If it's not, Option B is a big, clear win. If it already is, the pipeline mainly buys flexibility and vendor independence — not much cost savings — while giving up 100–900ms of latency and adding real integration work (3–4 separate providers to wire, monitor, and keep in sync with LiveKit Agents' pipeline mode instead of `RealtimeModel`).

---

## 4. Recommendation

1. **Audit prompt caching first** (Option A, near-free, already recommended). This single check tells us which row of the table above we're actually in, and therefore whether Option B is a 3–9x win or a rough wash.
2. **If caching is broken/low-hit-rate:** strongly consider Option B (or first just fix caching, which is free and might get us most of the way there without a rearchitecture).
3. **If caching is working well:** stick with Realtime, take the small wins (avatar default-off, idle timeout, cheaper Realtime-mini model, scope narrowing) — a pipeline isn't worth the latency hit and integration effort for marginal savings.
4. **Either way**, the general-Q&A scope conversation with Sam matters regardless of architecture — it shrinks the token volume everything else is a percentage of.

---

## Sources

**Realtime / text model pricing (first pass):**
- [OpenAI Realtime API Cost Per Minute — 2026 math](https://callsphere.ai/blog/vw2c-openai-realtime-cost-per-minute-math-2026)
- [Managing costs — OpenAI API docs](https://platform.openai.com/docs/guides/realtime-costs)
- [OpenAI Realtime API Pricing 2026 — real-world session data](https://hackernoon.com/openai-realtime-api-pricing-in-2026-real-world-data-from-4000-measured-sessions)
- [GPT-4o mini API Pricing 2026](https://pricepertoken.com/pricing-page/model/openai-gpt-4o-mini)
- [OpenAI API Pricing 2026 overview](https://pecollective.com/tools/openai-api-pricing/)
- [LiveKit Pricing](https://livekit.com/pricing)
- [Understanding LiveKit Cloud Pricing — Knowledge Base](https://kb.livekit.io/articles/3947254704-understanding-livekit-cloud-pricing)
- [HeyGen API Pricing Explained](https://help.heygen.com/en/articles/10060327-heygen-api-pricing-explained)
- [Introducing LiveAvatar — HeyGen Help Center](https://help.heygen.com/en/articles/12758516-introducing-liveavatar)
- [GPT Realtime mini pricing 2026](https://www.eesel.ai/blog/gpt-realtime-mini-pricing)
- [Prompt caching — OpenAI API docs](https://developers.openai.com/api/docs/guides/prompt-caching)

**STT/TTS pipeline pricing (this pass):**
- [Deepgram Pricing 2026: Nova-3 breakdown](https://brasstranscripts.com/blog/deepgram-pricing-per-minute-2025-real-time-vs-batch)
- [Deepgram Pricing](https://deepgram.com/pricing)
- [Speech-to-Text API Pricing (June 2026)](https://www.buildmvpfast.com/api-costs/transcription)
- [ElevenLabs Pricing in 2026](https://www.cekura.ai/blogs/elevenlabs-pricing)
- [Cartesia vs ElevenLabs for Voice AI: Latency, Quality, and Cost in 2026](https://burki.dev/blog/41-cartesia-vs-elevenlabs-tts)
- [OpenAI Whisper API Pricing 2026](https://diyai.io/ai-tools/speech-to-text/openai-whisper-api-pricing-2026/)
- [Whisper API Pricing 2026: $0.006/min](https://tokenmix.ai/blog/whisper-api-pricing)
- [Voice Agent Architecture: STT, LLM, and TTS Pipelines Explained — LiveKit](https://livekit.com/blog/voice-agent-architecture-stt-llm-tts-pipelines-explained)
- [Real-Time vs Turn-Based Voice Agents in 2026](https://softcery.com/lab/ai-voice-agents-real-time-vs-turn-based-tts-stt-architecture)
- [Sequential Pipeline Architecture for Voice Agents — LiveKit](https://livekit.com/blog/sequential-pipeline-architecture-voice-agents)
- [Understand and Improve Voice Agent Latency — LiveKit](https://livekit.com/blog/understand-and-improve-agent-latency)
