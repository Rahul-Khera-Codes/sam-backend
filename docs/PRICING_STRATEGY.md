# Pricing Strategy Research — AI Employees Platform

**Prepared:** 2026-04-22  
**Status:** Draft — for internal discussion before customer pricing is set  
**Purpose:** Establish a data-driven pricing floor and strategy by analyzing actual infrastructure costs before deciding on customer-facing plans.

---

## Table of Contents

1. [Platform Overview](#1-platform-overview)
2. [Infrastructure Cost Research](#2-infrastructure-cost-research)
   - 2.1 Twilio
   - 2.2 LiveKit
   - 2.3 OpenAI Realtime API
   - 2.4 Supabase
3. [Cost Per Call Model](#3-cost-per-call-model)
4. [Monthly COGS Per Customer](#4-monthly-cogs-per-customer)
5. [Pricing Floor Analysis](#5-pricing-floor-analysis)
6. [Pricing Options & Recommendations](#6-pricing-options--recommendations)
7. [Competitive Landscape](#7-competitive-landscape)
8. [Decision Framework](#8-decision-framework)

---

## 1. Platform Overview

### What This Platform Is

**AI Employees** (codename: SAM) is a **B2B SaaS AI voice receptionist** for service businesses. Businesses get a dedicated phone number — when customers call, an AI agent answers, handles bookings, answers questions, and forwards calls to humans when needed. The business owner manages everything through a web dashboard.

### Target Customer

Multi-location service businesses — barbershops, salons, spas, dental/medical offices, auto shops — that:
- Receive frequent inbound calls (bookings, inquiries, rescheduling)
- Have one or more physical locations with different staff and services
- Want 24/7 phone coverage without a full-time receptionist ($35,000–55,000/year salary)

### Full Feature Inventory

**Core AI Agent Capabilities**
- Inbound call answering — AI greets, understands intent, collects booking info
- Outbound calls — agent dials customers for reminders and follow-ups
- Live call forwarding — SIP REFER transfer to a real human (Option C implementation)
- Missed call text-back — automatic SMS when a call is not answered
- Multi-language support (configurable feature flag)
- Custom business hours + holiday/special schedule overrides per location

**Communications**
- SMS confirmations, reminders via Twilio
- Email: booking confirmation, reschedule notification, cancellation notice — to customer and staff — via Gmail OAuth per location
- Google Calendar sync per staff member (creates/updates/deletes events)

**Agent Configuration & Personalization**
- Brand Voice wizard — set tone, style, vocabulary, do-not-say phrases, and sample responses
- Agent Settings — 10 feature flag toggles (inbound, outbound, SMS, forwarding, callback scheduling, reschedule/cancel, confirmation calls, multi-language, feedback)
- Business hours schedule per location (Mon–Sun, open/close times)
- Call forwarding contacts + rules with full CRUD
- Custom Schedules — one-time date-range overrides (holidays) or recurring day-of-week schedules

**Multi-Location Architecture**
- Fully location-scoped agent — each phone number is bound to one specific location
- Location-specific staff, services, hours, and integrations
- Agent knows which location was called and refuses cross-location bookings
- Can provide other branch phone number to caller verbally
- Agent Settings, hours, forwarding rules, Gmail OAuth, and custom schedules are all per-location

**Dashboard & Analytics**
- Call recordings stored in Supabase Storage with signed URL access
- Full transcripts (per utterance, ordered)
- AI-generated call summaries
- Analytics: total calls, avg duration, success rate, missed calls, forwarded calls — with period-over-period % change
- Call volume trends chart (daily/weekly/monthly)
- Call status distribution (donut chart by completed/missed/forwarded/failed)
- Real-time "recent activity" feed on dashboard home

**Business & Team Management**
- Team Management — invite by email, role assignment (super_admin / admin / user), location assignment
- Roles & Permissions matrix page
- Phone Numbers page — search, provision, release Twilio numbers per location; test web call per location
- Business soft delete — super_admin only, name confirmation, 90-day data grace period
- Support form — wired to backend endpoint

**Third-Party Integrations**
- Gmail OAuth (per location) — send automated emails on bookings, reschedules, cancellations
- Google Calendar (per staff) — creates, updates, and deletes calendar events
- SMS via Twilio A2P (confirmations + missed call text-back)

### Technology Stack

| Layer | Technology | Cost Driver |
|---|---|---|
| AI Voice | OpenAI GPT-4o Realtime API | Per-audio-token (main variable cost) |
| Real-time infra | LiveKit Cloud | Per-agent-session-minute |
| Telephony | Twilio Elastic SIP Trunking | Per-minute + per-number |
| Database / Auth / Storage | Supabase (PostgreSQL) | Flat monthly + storage/egress overage |
| Backend API | FastAPI on Docker | Hosting (VPS/cloud) |
| Frontend | React + TypeScript (Vite) | Hosting (static CDN) |

---

## 2. Infrastructure Cost Research

*All pricing current as of April 2026. Sources linked per section.*

---

### 2.1 Twilio

**Source:** https://www.twilio.com/en-us/voice/pricing/us | https://www.twilio.com/en-us/sip-trunking/pricing/us | https://www.twilio.com/en-us/sms/pricing/us

#### Phone Numbers (Monthly Rental)

| Number Type | Monthly Cost |
|---|---|
| US Local number | **$1.15/month** |
| US Toll-Free number | $2.15/month |

Each location needs one dedicated phone number. This is provisioned and managed through the platform's Phone Numbers page.

#### Voice Calls — Standard Programmable Voice API

| Direction | Rate |
|---|---|
| Inbound (local number → caller receives) | $0.0085/min |
| Inbound (toll-free number) | $0.0220/min |
| Outbound (platform dials out to PSTN) | $0.0140/min |

#### Voice Calls — Elastic SIP Trunking (what this platform uses)

The platform uses **Elastic SIP Trunking**, not the standard Programmable Voice API. SIP trunking is significantly cheaper for volume.

| Direction | Rate |
|---|---|
| Inbound SIP termination (PSTN → SIP) | **$0.0011/min** |
| Outbound SIP origination (SIP → PSTN) | **$0.0034/min** |
| Toll-free inbound SIP | $0.0130/min |

> Key insight: Elastic SIP trunking inbound is ~$0.0011/min vs $0.0085/min on the standard API — **8x cheaper** for inbound calls. This platform correctly uses SIP trunking.

#### SIP REFER / Call Transfer

No additional charge for initiating a SIP REFER transfer. You continue paying per-minute for the transferred call legs. So a forwarded call costs:
- The original inbound leg (minutes before transfer) × $0.0011/min
- The outbound leg to the forwarding contact × $0.0034/min

#### SMS (US)

| Type | Base Rate | Carrier Fee (AT&T/T-Mobile) | Total |
|---|---|---|---|
| Long code / A2P (outbound) | $0.0083/message | $0.0035–$0.0045 | **~$0.012/message** |
| Inbound SMS | $0.0083/message | — | $0.0083 |

#### Volume Discounts

- Automatic volume discounts apply as monthly spend scales — approximately 5% discount at $500–$10,000/month spend
- Committed-use pricing available (8–20% discount) for 1–3 year commitments
- Enterprise custom pricing available

---

### 2.2 LiveKit

**Source:** https://livekit.com/pricing | https://docs.livekit.io/deploy/admin/billing/

LiveKit is the real-time audio infrastructure. Every phone call = one LiveKit room with the caller (WebRTC or SIP participant) and the AI agent (agent session).

#### How LiveKit Billing Works

LiveKit does **not** charge per room created. It charges based on what happens inside rooms:

| Billable Unit | Rate | Notes |
|---|---|---|
| **Agent Session Minutes** | **$0.01/min** | Billed while agent is connected — the dominant cost |
| WebRTC Participant Minutes | $0.0004–$0.0005/min | Caller connected via browser/WebRTC |
| SIP Participant Minutes | See plan allocation | Third-party SIP trunk participants |
| Egress (audio recording) | $0.004–$0.005/min | Only if recording enabled in LiveKit |
| Bandwidth/data | $0.10–$0.12/GB | Outbound data egress |

> Key insight: **Agent session minutes at $0.01/min are 20x more expensive than WebRTC participant minutes.** For a 3-minute call, the agent session costs $0.03 vs $0.0015 for the caller. Always account for this in cost modeling.

#### Minimum Billing Increment

**1 minute** — a 10-second connection is billed as 1 full minute. For very short calls (hang-ups, robocalls), this is a floor.

#### Cloud Plans

| Plan | Monthly Price | Agent Minutes | WebRTC Minutes | Concurrent Sessions | SIP Minutes |
|---|---|---|---|---|---|
| **Build** (Free) | $0 | 1,000 | 5,000 | 100 | 50 US local |
| **Ship** | **$50/month** | 5,000 | 150,000 | 1,000 | 100 US local |
| **Scale** | $500/month | 50,000 | 1,500,000 | 600 | 1,000 US local |
| **Enterprise** | Custom | Unlimited | Unlimited | Unlimited | Unlimited |

#### Overage Rates

After plan inclusions are exhausted:
- Agent session minutes overage: **$0.01/min**
- WebRTC minutes overage: ~$0.0005/min
- SIP minutes overage: ~$0.003–$0.004/min

#### LiveKit Plan Cost Per Customer (At Scale)

On the **Ship plan ($50/month):**
- 5,000 agent minutes included = ~1,667 3-minute calls
- If the platform has 20 customers at 200 calls/month each: 20 × 600 agent min = 12,000 agent min total
- Overage: (12,000 − 5,000) × $0.01 = $70 overage
- Total LiveKit cost: $50 + $70 = **$120/month for 20 customers = $6/customer/month**

At 50 customers, 200 calls/month each:
- 50 × 600 = 30,000 agent minutes
- Overage: 25,000 × $0.01 = $250
- Total LiveKit: $300/month for 50 customers = **$6/customer/month** (stable unit economics)

#### Self-Hosting Option

LiveKit is open-source. You can self-host the LiveKit server and eliminate all per-minute charges, paying only server hosting costs. This becomes viable at scale (typically >$500/month in LiveKit bills). For early-stage, the managed cloud is recommended.

---

### 2.3 OpenAI Realtime API

**Source:** https://openai.com/api/pricing/ | https://platform.openai.com/docs/guides/realtime

This is **the largest variable cost** on the platform. Every second of conversation consumes audio tokens.

#### How Audio Tokens Work

- **Input audio**: 1 token per 100ms of audio (= 600 tokens/minute of speech)
- **Output audio**: 1 token per 50ms of audio (= 1,200 tokens/minute of agent speech)
- System prompt is charged as text tokens (but with caching, almost free after first call)

#### GPT-4o Realtime (Full Model)

| Token Type | Rate per 1M tokens | Per-token rate |
|---|---|---|
| Audio input | **$32.00** | $0.000032 |
| Audio output | **$64.00** | $0.000064 |
| Text input | $4.00 | $0.000004 |
| Text output | $16.00 | $0.000016 |
| **Cached text input** | **$0.40** | $0.0000004 (98.75% discount) |

#### GPT-4o mini Realtime (Budget Model)

| Token Type | Rate per 1M tokens |
|---|---|
| Audio input | **$10.00** |
| Audio output | **$20.00** |
| Text input | $0.60 |
| Text output | $2.40 |

> The mini model is **68% cheaper** than full GPT-4o Realtime for audio. For a voice receptionist use case (where voice quality is important but not cutting-edge nuance), the mini model is usually sufficient and dramatically changes unit economics.

#### Cost Per Call Breakdown (3-Minute Average Call)

Assumptions:
- 3 minutes total call duration
- ~50% of time is user speaking, 50% is agent speaking (interleaved)
- System prompt: ~1,000 words ≈ 1,500 text tokens (cached after first call)

**User audio input:** 3 min × 60,000ms/min ÷ 100ms/token = **1,800 audio input tokens**  
**Agent audio output:** 3 min × 60,000ms/min ÷ 50ms/token = **3,600 audio output tokens**

| Model | Audio Input Cost | Audio Output Cost | System Prompt (cached) | Total/call |
|---|---|---|---|---|
| GPT-4o Realtime | 1,800 × $0.000032 = $0.0576 | 3,600 × $0.000064 = $0.2304 | ~$0.0006 | **~$0.29/call** |
| GPT-4o mini Realtime | 1,800 × $0.000010 = $0.0180 | 3,600 × $0.000020 = $0.0720 | ~$0.0001 | **~$0.09/call** |

#### Cost Scaling by Call Length

| Call Duration | GPT-4o Full | GPT-4o Mini |
|---|---|---|
| 1 minute | ~$0.10 | ~$0.03 |
| 3 minutes | ~$0.29 | ~$0.09 |
| 5 minutes | ~$0.48 | ~$0.15 |
| 10 minutes | ~$0.96 | ~$0.30 |

#### Prompt Caching Impact

The system prompt (built from business/location/brand voice/schedule data) is typically 800–1,500 words. After the first call in a session, this is cached at a 98.75% discount. The uncached cost of 1,500 text tokens at $4/M = $0.006 — already trivial, and near-zero after caching.

#### Volume Discounts

OpenAI does not publish tier-based volume discounts for the Realtime API. All customers pay the same per-token rate. Enterprise contracts may include custom pricing.

---

### 2.4 Supabase

**Source:** https://supabase.com/pricing | https://supabase.com/docs/guides/platform/billing-on-supabase

Supabase is a **shared infrastructure cost** — one Supabase project serves all customers. Unlike the other three services, this does not scale linearly per call; it scales with number of business tenants, total data stored, and egress for serving call recordings.

#### Free Tier Limits

| Resource | Limit |
|---|---|
| Database size | 500 MB |
| File storage | 1 GB |
| Auth MAUs | 50,000 |
| Database egress | 5 GB/month |
| Storage egress | 5 GB/month |
| Projects | 2 per org |
| Critical limitation | **Projects auto-pause after 7 days inactivity** (kills production use) |

The free tier is not suitable for production use due to auto-pause behavior.

#### Pro Plan — $25/month per project

| Resource | Included |
|---|---|
| Database size | 8 GB |
| File storage | 100 GB |
| Auth MAUs | 100,000 |
| Database egress | 50 GB/month |
| Storage egress (cached) | 250 GB/month |
| Edge Function invocations | 2,000,000/month |
| Auto-pause | **Disabled** |

#### Team Plan — $599/month

Covers the entire organization (all projects). Includes team collaboration, RBAC, and priority support. Not needed until significant scale.

#### Compute Add-ons (on top of Pro)

The default compute for Pro is a `micro` instance. For a production multi-tenant platform:

| Compute Tier | Monthly Cost | RAM | Notes |
|---|---|---|---|
| Micro (default) | $0 (included) | 1 GB | Not suitable for production |
| Small | $10/month | 2 GB | Minimal production |
| Medium | $50/month | 4 GB | Recommended for early production |
| Large | $100/month | 8 GB | Comfortable for 50–200 tenants |
| XL | $200/month | 16 GB | 200–500 tenants |

**Realistic baseline for production:** Pro ($25) + Large compute add-on ($100) = **$125/month** regardless of customer count.

#### Storage Costs (Call Recordings)

A 3-minute call recording in compressed audio (MP3/Opus at ~32kbps):
- File size: ~720 KB ≈ 0.7 MB

| Calls stored | Total storage | Monthly cost |
|---|---|---|
| 1,000 calls | ~700 MB | ~$0.015 (within Pro 100 GB) |
| 10,000 calls | ~7 GB | $0.15 overage |
| 100,000 calls | ~70 GB | ~$1.47 overage (after Pro 100 GB) |

Storage overage rate: **$0.021/GB/month**

#### Egress Costs (Serving Recordings to Dashboard)

When a user plays back a recording in the dashboard, audio is served via a signed URL from Supabase Storage.

| Egress type | Rate |
|---|---|
| Cached (CDN) egress | $0.03/GB |
| Uncached egress | $0.09/GB |

Estimate: if 10% of stored recordings are replayed per month:
- 100 customers × 200 calls × 0.7 MB × 10% = ~1.4 GB/month replay → $0.04–$0.13/month (negligible at this scale)
- At 1,000 customers × 200 calls: ~14 GB/month replay → $0.42–$1.26/month (still negligible)

#### Auth (MAU) Pricing at Scale

| MAUs | Cost |
|---|---|
| ≤100,000 (Pro plan) | Included |
| Per MAU over 100,000 | $0.00325/MAU |

For context: this platform's auth users are **business owners and staff** (not end customers/callers). A platform with 500 businesses × avg 5 staff = 2,500 MAUs — well within the Pro tier for a very long time.

#### Summary: Supabase as Shared Platform Cost

| Scale | Monthly Supabase Cost | Per-Customer Share |
|---|---|---|
| 10 customers | ~$125 | $12.50 |
| 50 customers | ~$125–150 | $2.50–3.00 |
| 100 customers | ~$150–175 | $1.50–1.75 |
| 500 customers | ~$200–300 | $0.40–0.60 |

Supabase is **not a meaningful per-customer cost** beyond the early stage (10–20 customers). It amortizes quickly.

---

## 3. Cost Per Call Model

### Assumptions for Modeling

- **Average call duration:** 3 minutes (industry average for AI receptionist interactions)
- **Call mix:** 80% inbound, 20% outbound (outbound = reminders, follow-ups)
- **SMS trigger rate:** 50% of calls send 1 SMS (booking confirmation or missed call text-back)
- **AI model:** GPT-4o mini Realtime (recommended; full model analyzed separately)
- **Telephony:** Twilio Elastic SIP Trunking (current platform implementation)

### Per-Call Cost Breakdown

#### Inbound Call (3 minutes, GPT-4o mini)

| Cost Component | Calculation | Cost |
|---|---|---|
| OpenAI audio input | 1,800 tokens × $0.000010 | $0.018 |
| OpenAI audio output | 3,600 tokens × $0.000020 | $0.072 |
| LiveKit agent session | 3 min × $0.010 | $0.030 |
| LiveKit WebRTC caller | 3 min × $0.0005 | $0.002 |
| Twilio SIP inbound | 3 min × $0.0011 | $0.003 |
| **Subtotal (no SMS)** | | **$0.125** |
| SMS (50% trigger) | 0.5 × $0.012 | $0.006 |
| **Total per inbound call** | | **~$0.131** |

#### Outbound Call (3 minutes, GPT-4o mini)

| Cost Component | Calculation | Cost |
|---|---|---|
| OpenAI audio input | 1,800 tokens × $0.000010 | $0.018 |
| OpenAI audio output | 3,600 tokens × $0.000020 | $0.072 |
| LiveKit agent session | 3 min × $0.010 | $0.030 |
| Twilio SIP outbound | 3 min × $0.0034 | $0.010 |
| **Total per outbound call** | | **~$0.130** |

#### Inbound Call (3 minutes, GPT-4o Full Model)

| Cost Component | Calculation | Cost |
|---|---|---|
| OpenAI audio input | 1,800 tokens × $0.000032 | $0.058 |
| OpenAI audio output | 3,600 tokens × $0.000064 | $0.230 |
| LiveKit agent session | 3 min × $0.010 | $0.030 |
| Twilio SIP inbound | 3 min × $0.0011 | $0.003 |
| SMS (50% trigger) | 0.5 × $0.012 | $0.006 |
| **Total per inbound call (full model)** | | **~$0.327** |

### Summary: Cost Per Call by Model

| Model | Per 3-min call | Per 5-min call | Per 1-min call (short hang-up) |
|---|---|---|---|
| GPT-4o mini Realtime | **~$0.13** | ~$0.21 | ~$0.05 |
| GPT-4o Realtime (full) | **~$0.33** | ~$0.53 | ~$0.14 |

> The model choice alone changes per-call cost by **2.5x**. This is the single most important infrastructure decision for pricing.

---

## 4. Monthly COGS Per Customer

### What "Per Customer" Means Here

One **customer** = one **business** with one or more **locations**. Each location has:
- Its own phone number ($1.15/month)
- Its own call volume
- Potentially its own LiveKit agent sessions

For modeling, we assume **one location per customer** at the starter tier, and multi-location upsell at higher tiers.

### COGS Table: GPT-4o mini (Recommended)

| Monthly Calls | OpenAI | LiveKit | Twilio SIP | Phone # | SMS | Supabase share | **Total COGS** |
|---|---|---|---|---|---|---|---|
| 50 calls | $6.50 | $1.50 | $0.17 | $1.15 | $0.30 | $2.50 | **~$12** |
| 100 calls | $13.00 | $3.00 | $0.33 | $1.15 | $0.60 | $2.50 | **~$21** |
| 150 calls | $19.50 | $4.50 | $0.50 | $1.15 | $0.90 | $2.50 | **~$29** |
| 200 calls | $26.00 | $6.00 | $0.66 | $1.15 | $1.20 | $2.50 | **~$38** |
| 300 calls | $39.00 | $9.00 | $0.99 | $1.15 | $1.80 | $2.50 | **~$54** |
| 400 calls | $52.00 | $12.00 | $1.32 | $1.15 | $2.40 | $2.50 | **~$71** |
| 500 calls | $65.00 | $15.00 | $1.65 | $1.15 | $3.00 | $2.50 | **~$88** |

### COGS Table: GPT-4o Full Model

| Monthly Calls | OpenAI | LiveKit | Twilio | Supabase | **Total COGS** |
|---|---|---|---|---|---|
| 100 calls | $33.00 | $3.00 | $1.98 | $2.50 | **~$40** |
| 200 calls | $66.00 | $6.00 | $3.96 | $2.50 | **~$78** |
| 300 calls | $99.00 | $9.00 | $5.94 | $2.50 | **~$116** |
| 500 calls | $165.00 | $15.00 | $9.90 | $2.50 | **~$192** |

> With the full GPT-4o model, you **lose money** at $100/month if any customer makes more than ~300 calls.

---

## 5. Pricing Floor Analysis

### The $100/Month Scenario

The client's initial proposal of $100/month flat was the starting point for this analysis.

| Call Volume | Model | COGS | Revenue | Gross Margin | Viable? |
|---|---|---|---|---|---|
| 100 calls | GPT-4o mini | $21 | $100 | **79%** | Yes |
| 150 calls | GPT-4o mini | $29 | $100 | **71%** | Yes |
| 200 calls | GPT-4o mini | $38 | $100 | **62%** | Yes |
| 300 calls | GPT-4o mini | $54 | $100 | **46%** | Acceptable |
| 400 calls | GPT-4o mini | $71 | $100 | **29%** | Very thin |
| 500 calls | GPT-4o mini | $88 | $100 | **12%** | Dangerous |
| 200 calls | GPT-4o full | $78 | $100 | **22%** | Poor |
| 300 calls | GPT-4o full | $116 | $100 | **−16%** | **Loss** |
| 400 calls | GPT-4o full | $155 | $100 | **−55%** | **Major loss** |

### Key Conclusions

1. **$100/month flat works ONLY with GPT-4o mini AND a call cap of ~200–250 calls/month.** Without a cap, one busy customer (500 calls/month) drops margin to 12% — one infrastructure price increase and you're underwater.

2. **GPT-4o full model makes $100/month pricing completely unviable above 250 calls.** If you want to offer the full model, minimum safe pricing is ~$200–250/month.

3. **OpenAI is 70–85% of total COGS.** It is the dominant cost by far. Every pricing decision starts here.

4. **Twilio and LiveKit are secondary costs** (~15–20% of COGS combined). They matter at scale but don't change the fundamental model selection decision.

5. **Supabase is negligible per-customer** once you have more than 20–30 customers.

### What Happens If Calls Are Longer Than 3 Minutes?

A busy barbershop or dental office may have complex calls (new patient intake, multi-service booking) that run 5–8 minutes.

| Avg Call Duration | COGS at 200 calls/mo (mini) | COGS at 200 calls/mo (full) |
|---|---|---|
| 2 minutes | ~$27 | ~$55 |
| 3 minutes | ~$38 | ~$78 |
| 5 minutes | ~$60 | ~$127 |
| 7 minutes | ~$82 | ~$175 |

At 5-minute average calls + full GPT-4o model, $100/month is a **loss at any volume above 150 calls**.

---

## 6. Pricing Options & Recommendations

### Option A — Tiered Plans with Included Call Buckets (Recommended)

This is the most common SaaS pricing model for usage-heavy products. It gives customers predictability while protecting margins via caps.

| Plan | Price/month | Included calls | Locations | Users | Overage |
|---|---|---|---|---|---|
| **Starter** | **$99/month** | 150 calls | 1 | 5 | $0.35/call |
| **Growth** | **$199/month** | 400 calls | 3 | 15 | $0.30/call |
| **Pro** | **$349/month** | 800 calls | 5 | 30 | $0.25/call |
| **Enterprise** | Custom | Unlimited | Unlimited | Unlimited | Negotiated |

**Margin analysis (Starter, GPT-4o mini, 150 calls):**
- COGS: ~$29
- Revenue: $99
- Gross margin: **71%** — healthy SaaS margin

**Margin analysis (Starter, GPT-4o mini, at cap 150 calls):**
- COGS: ~$29
- Revenue: $99
- Gross margin: 71%

**Margin analysis (Starter, customer uses 200 calls with overage):**
- COGS: ~$38
- Revenue: $99 + 50 × $0.35 = $116.50
- Gross margin: **67%** — overage actually improves margin

**Why "AI Credits" framing (from billing mock) also works:**
- Market AI Credits at 1 credit = 1 call
- Starter = 150 credits/month
- Overage credits at $0.35/credit
- Psychologically, customers understand "credits" as a consumable resource

---

### Option B — Base Fee + Per-Call Usage (Transparent Usage Billing)

More honest, harder to sell to SMBs. Better for high-volume or enterprise customers.

| Component | Price |
|---|---|
| Platform base fee | $49/month/location |
| Per call (inbound, ≤3 min) | $0.25 |
| Per additional minute (>3 min) | $0.08/min |
| Outbound call | $0.25 |
| SMS | $0.05 |

**Example: 200 calls at 3 min avg:**
- Base: $49
- Calls: 200 × $0.25 = $50
- Total: **$99** (same as Starter above)

**Pros:** Customers with low call volume pay less. Very fair.  
**Cons:** SMBs dislike variable bills. Hard to sell. Finance teams want fixed costs.

---

### Option C — Flat Rate Unlimited (Not Recommended)

| Plan | Price | Risk |
|---|---|---|
| Flat unlimited | $199/month | One customer with 700 calls/month = break-even |

Not recommended without sophisticated fraud/abuse detection and ability to terminate high-usage accounts. Even at $199/month, a customer making 600 calls at 3 minutes each with GPT-4o mini = $78 COGS, leaving $121 margin — that's workable. But with full GPT-4o model, same customer = $234 COGS, already a loss.

---

### Option D — Per-Location Pricing (Scales With Business Growth)

Charge per location rather than per tier. Natural upsell as customers grow.

| Configuration | Price |
|---|---|
| Base platform | $49/month (dashboard, team, settings) |
| Per location | $59/month/location (includes 200 calls/mo) |
| Overage | $0.30/call above 200 |

**Example: 1-location customer:**
- $49 + $59 = **$108/month**
- COGS (200 calls, mini): ~$38
- Margin: **65%**

**Example: 3-location customer:**
- $49 + 3 × $59 = **$226/month**
- COGS (3 × 200 calls): ~$114
- Margin: **50%**

**Pros:** Very natural upsell path. Price grows with value delivered.  
**Cons:** Single-location businesses pay higher base than competitors.

---

### Recommended Approach

**Start with Option A (tiered plans with call buckets)**, because:

1. SMBs budget monthly — they need a predictable number
2. Overage per-call adds protection without shocking customers if they go slightly over
3. The existing billing UI mock already shows this structure (Locations, Users, AI Credits)
4. It maps cleanly to the multi-location architecture already built

**Critical implementation requirements:**
1. Track call count per billing period in the database
2. Enforce soft limits (warn at 80%, 100%) via dashboard
3. Implement hard limit or auto-overage billing (not blocking — keep answering calls, charge overage)
4. Use **GPT-4o mini by default** — offer full GPT-4o as an "Enhanced AI" add-on at $50/month premium

---

## 7. Competitive Landscape

### Direct Competitors & Their Pricing

| Competitor | Type | Pricing | Notes |
|---|---|---|---|
| **Numa** | AI receptionist for SMBs | ~$200–400/month | SMS-first, voice secondary |
| **Signpost** | AI + human receptionist | ~$300–500/month | Includes human backup |
| **Smith.ai** | Human-backed virtual receptionist | $285–755/month | Human agents, premium quality |
| **Ruby Receptionists** | Human receptionists | $235–1,085/month | Humans only |
| **Bland.ai** | Developer AI calling platform | ~$0.09/min | Dev tool, not turnkey |
| **Retell AI** | Developer AI calling | ~$0.07–0.11/min | Dev tool, not turnkey |
| **GoHighLevel** | Agency platform with AI | $97–497/month | AI calling as add-on |
| **Air.ai** | AI receptionist | ~$0.11/min | No setup fee |

### Positioning Insight

- **Human receptionist services** charge $200–1,000/month. Your platform replaces them at 1/3 to 1/10 the cost.
- **Developer AI calling platforms** are cheap per-minute but require technical setup — not turnkey for SMBs.
- **SMB-focused turnkey AI receptionists** (Numa, Signpost) price $200–500/month.

**Conclusion:** $99–199/month is **below market for SMB-focused AI receptionists** while still being highly profitable with the cost structure above. This is a strong position to launch from — especially with the multi-location architecture that competitors often lack.

---

## 8. Decision Framework

### Before Finalizing Pricing, Answer These Questions

1. **Which OpenAI model will be default?**
   - GPT-4o mini: safe economics, good quality for receptionist use
   - GPT-4o full: 3x the cost, meaningfully better for complex conversations
   - Recommendation: mini as default, offer full as paid add-on

2. **Will you enforce call caps or go unlimited?**
   - Caps required if starting at $99–100/month
   - Overage billing required at the platform level (currently not implemented)

3. **Will pricing be per-location or per-business?**
   - Per-location is more natural for the multi-location architecture
   - Per-business with location limits is simpler to explain

4. **When will Stripe/billing be wired up?**
   - The Billing page currently shows mock data only
   - Need: Stripe integration, subscription management, usage tracking

5. **What is the sales motion: self-serve or sales-assisted?**
   - Self-serve → tier names and prices must be instantly understandable
   - Sales-assisted → more flexibility for custom pricing per deal

### Recommended First Launch Pricing

| Plan | Price | Included | Who It's For |
|---|---|---|---|
| **Starter** | $99/month | 1 location, 150 calls/mo, 5 users | Single-location small business |
| **Growth** | $199/month | 3 locations, 400 calls/mo, 15 users | Growing multi-location business |
| **Pro** | $349/month | 5 locations, 800 calls/mo, 30 users | Established multi-location chain |

All plans include: inbound + outbound calling, SMS, email (Gmail OAuth), Google Calendar, call recordings, transcripts, analytics, brand voice, custom schedules, team management.

Overage: $0.35/call on Starter, $0.30 on Growth, $0.25 on Pro.

### Gross Margin Summary at Launch Prices

| Plan | Calls at cap | COGS (mini) | Revenue | Gross Margin |
|---|---|---|---|---|
| Starter | 150 | $29 | $99 | **71%** |
| Growth | 400 | $71 | $199 | **64%** |
| Pro | 800 | $136 | $349 | **61%** |

These are **SaaS-grade gross margins** (60–70%+). As OpenAI prices continue to fall (they have dropped 20–40% in recent product cycles), margins will improve automatically without changing list prices.

---

*Document last updated: 2026-04-22. Review and update cost figures quarterly as vendor pricing changes.*
