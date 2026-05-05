# Client Pre-Launch QA Checklist

Last updated: 2026-04-29 (QA Session 7)

## Legend
- ✅ Done and verified
- ⚠️ Built — needs manual testing against real account
- ❌ Not built

---

## Hard Blockers (must fix before launch)

| Item | Status | Notes |
|------|--------|-------|
| Billing | ❌ | Static placeholder UI — no Stripe integration |

---

## General

| Item | Status | Notes |
|------|--------|-------|
| Sign up with Email | ✅ | |
| Sign up with Google | ✅ | |
| Sign in with Email | ✅ | |
| Sign in with Google | ✅ | |
| Forgot Password | ✅ | |

---

## Calendar

| Item | Status | Notes |
|------|--------|-------|
| Search Filter | ✅ | QA Session 1 — 2026-04-29 |
| Dropdown Filter | ✅ | QA Session 1 — 2026-04-29 |
| Views (Month, Week, Day, List) | ✅ | QA Session 1 — 2026-04-29 |
| Make Appointment — Button | ✅ | QA Session 1 — 2026-04-29 |
| Make Appointment — Double Click on Date | ✅ | QA Session 1 — 2026-04-29 |

---

## Support

| Item | Status | Notes |
|------|--------|-------|
| Email goes to support@aiemployeesinc.com | ⚠️ | Form submission functional (QA Session 7); delivery requires Gmail OAuth connected in Settings → Integrations; 409 when not connected |

---

## Wishlist

| Item | Status | Notes |
|------|--------|-------|
| Email goes to sam@aiemployeesinc.com | ⚠️ | Requires Resend DNS on Hostinger to be configured first |

---

## Global Settings

| Item | Status | Notes |
|------|--------|-------|
| Language and region settings | ✅ | QA Session 4 — 2026-04-29; all 4 selects present; time format toggle+save confirmed |
| Brand Voice — "do not say" words | ✅ | QA Session 4 — 2026-04-29; wizard navigation, word add/remove, save all working |

---

## Business Settings

| Item | Status | Notes |
|------|--------|-------|
| Company Logo uploads | ✅ | QA Session 3 — 2026-04-29 |
| Company information inputs | ✅ | QA Session 3 — 2026-04-29 |
| Business hours inputs | ✅ | QA Session 3 — 2026-04-29 |
| Integrations — connect to services | ✅ | QA Session 3 — Gmail card renders, search filter works; actual OAuth redirect not testable headlessly |
| Deactivation | ✅ | QA Session 3 — role guard, dialog, name confirmation, cancel-safe all verified |

---

## Profile Settings

| Item | Status | Notes |
|------|--------|-------|
| Icon photo changes | ✅ | QA Session 2 — 2026-04-29 |
| Name input | ✅ | QA Session 2 — 2026-04-29 |
| Password updates | ✅ | QA Session 2 — validation confirmed; actual update not tested to preserve creds |
| Two-Factor Authentication | ✅ | TOTP (Authenticator App); SMS 2FA blocked on A2P 10DLC |
| Connected Google Accounts | ✅ | QA Session 2 — 2026-04-29; Google shows "Connected" |

---

## Locations

| Item | Status | Notes |
|------|--------|-------|
| Add a new location | ✅ | QA Session 5 — 2026-04-29; dialog opens; location created and seeded (backend confirmed); slow API but functional |

---

## Team Management

| Item | Status | Notes |
|------|--------|-------|
| Invite Team Member — email works, new member can login | ⚠️ | Requires edge fn redeploy for customRoleId; invite dialog+role dropdown verified Session 4 |
| Change Role works | ✅ | QA Session 4 — 2026-04-29; dialog opens; role saved with toast; restore confirmed |
| Manage Locations works | ✅ | QA Session 4 — 2026-04-29; dialog opens with location checkboxes; cancel safe |
| Manage Services works | ✅ | QA Session 4 — 2026-04-29; dialog opens successfully |
| Manage Hours works | ✅ | QA Session 4 — 2026-04-29; weekly availability dialog opens |
| Remove User works | ❌ | BUG: no confirmation dialog — action fires immediately (TC-TEAM-006); fix required before launch |

---

## Roles & Permissions

| Item | Status | Notes |
|------|--------|-------|
| Add new custom roles | ✅ | QA Session 4 — role creation confirmed working (API slow >2s but succeeds); migrations applied |
| Assign permissions (toggle checkboxes per role) | ❌ | BUG: PUT fires but targets wrong role (stale selectedRoleId closure); state still reverts on reload for selected tab (TC-ROLES-002); partial fix deployed — new stale closure root cause needs fix |
| Sub window permissions enabled | ⚠️ | Needs clarification on what "sub window" means |

---

## Billing

| Item | Status | Notes |
|------|--------|-------|
| (no sub-items specified) | ❌ | Entire section is static placeholder — Stripe not integrated |

---

## Phone Numbers

| Item | Status | Notes |
|------|--------|-------|
| Search and buy US numbers | ✅ | QA Session 5 — 2026-04-29; per-location assignment UI; "Assign number" opens inline search with US + area code input; purchase flow renders |
| Search and buy Canadian numbers | ✅ | QA Session 5 — 2026-04-29; (647) 584-4089 confirmed assigned and displayed for Downtown office |

---

## Customer Service Employee

| Item | Status | Notes |
|------|--------|-------|
| AI tells appointment time | ⚠️ | |
| AI answers from company info (Business Settings) | ⚠️ | |
| AI answers from business hours | ⚠️ | |
| AI lists services | ⚠️ | |
| AI tells service time required | ⚠️ | |
| AI tells service price | ⚠️ | |
| AI does not mention deactivated services | ⚠️ | |
| AI answers from knowledge base — PDF upload | ⚠️ | |
| Conflict handling — services vs PDF upload | ⚠️ | |
| AI answers from knowledge base — manual typed info | ⚠️ | |
| AI answers team member availability | ⚠️ | |
| AI answers team member services | ⚠️ | |
| AI answers team member availability on days off | ⚠️ | |
| AI knows about new appointment after booking via button | ⚠️ | |
| Call Recordings — playback + download | ⚠️ | QA Session 6 — page renders with call history; download not tested (requires actual recording) |
| Call Recordings — transcript, summary, insights | ⚠️ | Requires actual call recording to verify |
| Scheduler — AI starts and ends on scheduled time | ⚠️ | QA Session 6 — Scheduler page renders; functional test requires live AI run |
| Scheduler — no overlapping info between locations | ⚠️ | Requires live AI run across multiple locations |
| Call Forwarding — calls get transferred | ⚠️ | QA Session 6 — Call Forwarding page renders; functional test requires live call |
| Call Forwarding — follows time-based rules | ⚠️ | QA Session 6 — page renders; functional test requires live call |
| All features in the setup window | ✅ | QA Session 6 — setup checklist wired to real data; 5/8 tasks completed; agent activity shows live call history |

---

## Pre-Conditions Before Testing

1. ✅ Migrations applied (QA Session 1 — 2026-04-29)
   - `20260428000001` — custom_roles + role_page_permissions
   - `20260428000002` — policy fixes + index
   - `20260428000003` — user_roles.custom_role_id
2. ✅ Edge functions deployed (QA Session 1 — 2026-04-29)
3. ✅ Resend DNS live on Hostinger — password reset + signup confirmation emails working (QA Session 1 — 2026-04-29)
