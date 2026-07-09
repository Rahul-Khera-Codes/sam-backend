# Voice Agents — Cost Breakdown: One AI Model vs. Three Separate Tools

**Prepared by:** Rahul Khera
**Date:** July 2, 2026
**For:** Sam Maisuria, Charles, Yuvraj Singh

---

## What This Doc Answers

Both of our voice products — the **Customer Service phone agent** and the **Executive Assistant (Remi)** — run the same way today. This doc lays out the two ways we *could* build them, what each actually costs, and why switching adds delay to every response. Short version up front: **we tested this for real this week, and staying on our current setup is the right call — switching would not save meaningful money, and it would make both agents feel slower to talk to.**

---

## Option A — What We Have Today: One AI Model Does Everything

Both agents use a single AI model (OpenAI's "Realtime" model) that listens to the caller's voice, understands it, thinks of a reply, and speaks the reply back — all in one continuous system. Nothing is handed off between separate tools.

**Why this is good:** it's fast (the AI starts responding in well under half a second) and it sounds natural, because the same "brain" that understands what was said is also the one speaking the reply — it doesn't lose any nuance in translation between steps.

**The cost:** this model charges more per minute than a plain text-based AI would, because it's doing more (understanding raw audio, not just text). BUT — OpenAI has a "memory" feature that reuses parts of the conversation instead of re-processing everything from scratch every single time, which cuts the cost significantly once a conversation gets going.

**We actually measured this, live, this week (not just estimated it):** in a real test call with Remi, the memory-reuse feature kicked in and stabilized at roughly **70% reuse** by the end of the call. That means our real running cost is already close to the *cheap* end of what this model can cost — not the expensive end.

---

## Option B — Three Separate Specialist Tools Stitched Together

Instead of one model doing everything, this approach uses three separate tools handed off in sequence:
1. **Speech-to-Text** — a tool that just converts the caller's voice into written words.
2. **A text AI "brain"** — a plain text-based AI (like the ones behind ChatGPT) that reads those written words and decides what to say back.
3. **Text-to-Speech** — a tool that converts the AI's written reply back into a spoken voice.

**Why someone would want this:** each of the three pieces is individually cheaper, and you can mix-and-match — swap in a different voice, a different AI brain, or a cheaper transcription tool independently, without touching the other two.

**The real cost, put together:** roughly **$0.05 to $0.15 per minute** all-in, using a well-chosen combination of tools.

**The catch — and this is the part I flagged to Sam already: it adds delay to every single reply.** Because the audio has to be fully transcribed, THEN the AI brain has to finish thinking, THEN the reply has to be converted back into speech — one after another, not all at once — every single exchange takes noticeably longer to come back. Our current one-model setup responds in well under half a second; this three-tool setup typically takes **550 milliseconds to almost a full second (and sometimes more)** per reply. In a live phone call or voice conversation, that's a noticeable, felt delay — the kind that makes an AI feel like it's "thinking" before every sentence instead of responding naturally.

---

## The Side-by-Side Comparison

| | **Option A: One Model (current)** | **Option B: Three Separate Tools** |
|---|---|---|
| **Speed of reply** | Under half a second | 550ms–950ms+ per reply |
| **Cost, if the "memory reuse" isn't kicking in** | $0.18–$0.46 per minute | $0.05–$0.15 per minute (**cheaper here**) |
| **Cost, with memory reuse working (what we actually measured)** | $0.05–$0.10 per minute | $0.05–$0.15 per minute (**roughly the same, or Option A is cheaper**) |
| **Flexibility to swap pieces** | Locked into one provider | Can swap the voice, the AI brain, or the transcription tool independently |
| **Natural-sounding conversation** | Better — same system understands and speaks | Slightly more robotic-feeling handoffs between steps |

---

## The Decision

Since we actually measured our real memory-reuse rate this week (about 70%, and rising the longer a conversation runs) — **we're already in the cheap column for Option A.** Switching to three separate tools would mean giving up the instant-feeling responses we have now, in exchange for a cost savings that, based on real measured data, is close to zero — or could even go the other way.

**We're staying on Option A (the current one-model setup) for both voice agents.** We'll keep trimming smaller costs around the edges instead (turning off optional add-ons like the avatar by default, automatically ending sessions nobody's using, etc.) — those add up without touching how the core conversation feels.

If our real usage patterns change significantly down the road (much longer calls, very different conversation styles), it's worth re-measuring rather than assuming — but for now, the numbers say stay put.

---

## Appendix — If We Ever Revisit Option B: Cost by Specific Provider

The decision above is settled for now, but Sam asked for a clearer view of what Option B would actually cost with real, named products (not just a range) — so here's every piece broken out, plus a warning about how NOT to use this table.

### Speech-to-Text options (converts the caller's voice to text)

| Provider | Cost |
|---|---|
| Deepgram Nova-3 | $0.0065–$0.0077/min |
| OpenAI Whisper / gpt-4o-transcribe | $0.006/min |
| OpenAI gpt-4o-mini-transcribe | ~$0.003/min |

### AI "brain" options (reads the text, decides what to say)

| Provider | Cost per million words of text* | What this means per minute of conversation |
|---|---|---|
| GPT-4o-mini | $0.15 in / $0.60 out | Cheapest — a rounding error next to the audio costs above and below |
| GPT-4.1-mini | $0.40 in / $1.60 out | Still cheap, noticeably pricier than 4o-mini for the same job |
| Claude Haiku 4.5 | $1.00 in / $5.00 out | The most expensive of the three here — about 6–7x GPT-4o-mini |

*Loosely, "tokens" — AI providers charge per chunk of text, not literally per word, but it's close enough for comparing options.

### Text-to-Speech options (converts the AI's reply back into a voice)

| Provider | Cost |
|---|---|
| OpenAI tts-1 / gpt-4o-mini-tts | ~$0.011–$0.015/min |
| Deepgram Aura-2 | ~$0.020–$0.023/min |
| Cartesia Sonic | $0.02–$0.06/min |
| ElevenLabs | $0.10–$0.50/min (priciest, but generally considered the most natural-sounding voices) |

### Three example full stacks, put together

| Stack | STT | Brain | Voice | Total per minute |
|---|---|---|---|---|
| **Cheapest possible** | gpt-4o-mini-transcribe (~$0.003) | GPT-4o-mini (~$0.01) | OpenAI tts-1 (~$0.012) | **~$0.025/min** |
| **Balanced (what a "well-chosen stack" usually means)** | Deepgram Nova-3 (~$0.007) | GPT-4o-mini (~$0.01) | Cartesia Sonic (~$0.04) | **~$0.06/min** |
| **Premium voice quality** | Deepgram Nova-3 (~$0.007) | Claude Haiku 4.5 (~$0.03) | ElevenLabs (~$0.25) | **~$0.29/min** |

For comparison: our current one-model setup (Option A) is running at roughly **$0.05–$0.10/min** with the memory-reuse we measured. So even the "cheapest possible" three-tool stack above ($0.025/min) only wins by a small margin once you account for the delay it adds — and the "premium" stack is dramatically more expensive than what we have now.

### The important caveat — don't just pick the cheapest number and swap

**This table is for comparing sticker prices, not for making a decision on its own.** A cheaper number on paper doesn't tell you:
- Whether that specific voice actually sounds good for our use case, or robotic.
- Whether that specific transcription tool handles accents, background noise, or interruptions as well as what we have now.
- Whether the AI "brain" gives replies that are as accurate and on-topic as what we have now.

**Before switching anything, we test it for real** — run real conversations through the candidate combination, listen to it, and measure how it actually performs, not just what it costs. Cost is one input into that decision, not the whole decision. This applies to any future provider swap, not just a full architecture change.

---

## Questions?

If anything above isn't clear, or you want the underlying numbers/sources this is based on, just ask — happy to walk through it.

---

## Sources (appendix pricing, researched 2026-07-02)

- [Deepgram Pricing](https://deepgram.com/pricing)
- [Deepgram Pricing 2026 breakdown](https://diyai.io/ai-tools/speech-to-text/deepgram-pricing-2026/)
- [Whisper API Pricing 2026](https://tokenmix.ai/blog/whisper-api-pricing)
- [GPT-4o mini API Pricing 2026](https://pricepertoken.com/pricing-page/model/openai-gpt-4o-mini)
- [Claude Haiku 4.5 API Pricing 2026](https://pricepertoken.com/pricing-page/model/anthropic-claude-haiku-4.5)
- [Anthropic API Pricing 2026](https://pecollective.com/tools/anthropic-api-pricing/)
- [OpenAI TTS Pricing 2026 comparison](https://texttolab.com/blog/openai-tts-pricing)
- [OpenAI TTS Cost breakdown](https://www.s-anand.net/blog/openai-tts-cost/)
- [Cartesia vs ElevenLabs for Voice AI 2026](https://burki.dev/blog/41-cartesia-vs-elevenlabs-tts)
- [ElevenLabs Pricing 2026](https://www.cekura.ai/blogs/elevenlabs-pricing)
