# Client Communications Log

Ongoing log of decisions, requests, and issues raised by the client (Sam Maisuria).
Most recent entry at top.

---

## 2026-05-05

**From:** Sam Maisuria
**Context:** Follow-up on Resend DNS recurring failure

- Resend domain `aiemployeesinc.com` verification failing again
- Root cause: Sam sets up Google Workspace MX records for `sam@aiemployeesinc.com` and inadvertently wipes Resend TXT records (DKIM/SPF/DMARC)
- These two sets of records do NOT conflict — MX (Google) and TXT (Resend) can coexist
- SPF record must include both: `v=spf1 include:_spf.google.com include:amazonses.com ~all`
- **Action:** Sam needs to keep both sets of records in Hostinger at all times. When adding Google MX, do not delete existing TXT records.
- **Status:** Recurring — needs permanent DNS checklist for Sam

---

## 2026-05-01 (late night)

**From:** Sam Maisuria
**Context:** Billing architecture discussion

**Decision: Per-Agent Billing confirmed**
- Future agents (Sales, HR, Marketing, Executive) will be billed as monthly subscription add-ons
- Example: Growth plan ($149/mo) + Sales Agent (+$X/mo)
- Stripe handles as subscription line items; DB tracks `active_agents` per business
- Token-based billing ruled out — too complex to build and explain to customers

---

## 2026-04-30 (late night)

**From:** Sam Maisuria
**Context:** Billing page UI + pricing table update

**New pricing table shared (screenshots):**

| Plan | Price | AI Minutes | Est. Calls | Phone Numbers | Users | Google Cal | Multi-Location |
|---|---|---|---|---|---|---|---|
| Free Trial | Free | ~75 min | 25 calls | 1 | 2 | — | — |
| Starter | $99/mo | 200 min | ~65 calls | 1 | 5 | — | — |
| Growth | $149/mo | 600 min | ~200 calls | 1 | 15 | ✓ | Up to 3 |
| Professional | $299/mo | 1,500 min | ~500 calls | 2 | 30 | ✓ | Up to 5 |
| Enterprise | $599/mo | 4,000 min | ~1,300 calls | 5 | Unlimited | ✓ | Unlimited |

**Overage & Add-Ons:**
- Additional AI minutes: $0.30/minute
- Extra phone numbers: $25/month
- Extra locations: $49/month

**Clarifications from Sam:**
- Free/Starter tiers: limited to 1 location; extra locations require upgrade to Growth+
- Billing UI should be updated to reflect this table
- **Status:** ⏳ Pending — billing UI update not yet implemented

**DNS issue (same session):**
- Sam deleted MX records to add Google Workspace → broke Resend domain verification
- Sam re-added Resend DNS records manually
- **Status:** Fixed by Sam, but recurring (see 2026-05-05 entry)

---

## 2026-04-30 (evening)

**From:** Sam Maisuria
**Context:** Pre-launch check

**Asked about:**
- SMS 2FA status → still waiting on Sam to complete A2P 10DLC registration with Twilio
- Billing section status → Stripe integration now complete (built same day)

---
