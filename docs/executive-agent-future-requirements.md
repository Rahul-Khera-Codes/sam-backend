# Executive Agent & Roadmap — Future Requirements (Google scopes, verification, infra)

**Date:** 2026-06-24 (session 52) · Planning reference. The slow/expensive gate is **Google restricted-scope verification (CASA)** — decide the full scope set before submitting.

## Google scope tiers
- **Non-sensitive** — free (e.g. `userinfo.email`, `openid`).
- **Sensitive** — verification + justification, **no** audit (e.g. `calendar.events`, `calendar.readonly`, `gmail.send`, `drive.file`).
- **Restricted** — verification **+ annual paid CASA third-party security assessment** (e.g. `gmail.readonly`, `gmail.modify`, `gmail.compose`, broad Drive, Contacts).

## Feature → scope map
| Feature | Scope | Tier |
|---|---|---|
| Read/list emails (done) | `gmail.readonly` | Restricted (CASA) |
| Inbox management (mark read/archive/label) | `gmail.modify` | Restricted — **if ever needed, request NOW instead of readonly: one audit, one reconnect** |
| Save real Gmail drafts | `gmail.compose`/`modify` | Restricted |
| Send email (have) | `gmail.send` | Sensitive |
| Calendar read/create/reschedule + **two-way sync** | `calendar.events`/`calendar.readonly` | Sensitive (no CASA) |
| Read attachments / find a doc | `drive.file` (preferred) or `drive.readonly` | Sensitive vs Restricted — **prefer `drive.file` to stay out of restricted** |
| Client-history lookup | none (own `appointments` DB) | — (Restricted only if Google Contacts) |

## Other integrations
- **Microsoft 365 / Outlook** (there's a "Connect" card): separate Microsoft Graph OAuth + Microsoft publisher verification + admin consent. Parallel track.
- **CRM (Phase 2 "Push to CRM")**: per-provider OAuth + each provider's app review (HubSpot, Salesforce). Sam: not yet.
- **Sales Employee data (Apify)**: usage-priced API + CASL legal. Note: Apify scraping LinkedIn still risks LinkedIn ToS.

## Product/infra (non-scope)
- **HeyGen talking avatar (Phase 2)** — confirmed via `Executive Assistant.pdf` (avatar-picker gallery). HeyGen streaming-avatar API: real $ + engineering. Phase-1 avatar is frontend-only abstract.
- **Cards (WS3)** — frontend only.
- **Personality settings / multi-agent handoff (Phase 2)** — config/architecture only.
- **Billing add-on** — Stripe line item + session/minute metering.

## Cross-cutting
1. **CASA assessment** — biggest gate for Gmail reading at launch. Decide final Gmail scope set first (readonly vs modify).
2. **Privacy/compliance** — restricted scopes require published privacy policy + Google Limited-Use disclosure; possibly a DPA.
3. **Scope-migration UX** — every scope change forces all businesses to reconnect; build a "granted vs required scopes" check that prompts reconnect + degrades gracefully (no blank 403s).
4. **Keep core verification clean** — don't drag the Executive-Agent restricted scope into the core product's (sensitive-only) pending verification, or you escalate the whole app to CASA and delay launch.
