# QA Findings — AI Employees Platform
> Append-only log. Written by Claude during QA sessions only.
> **Claude never modifies source code. All entries are observational findings.**
> Screenshots: `docs/qa-screenshots/TC-[id].png`

---

## Summary Dashboard
> Claude updates after every session.

| Metric | Count |
|---|---|
| Total Tests Run | 76 |
| Total Passed | 56 |
| Total Failed | 8 |
| Total Blocked | 13 |
| Open Failures | 5 (TC-TEAM-006, TC-ROLES-002 — real bugs; TC-SALES-LR-003, TC-SALES-CA-004, TC-SALES-MA-001 — real bugs, Sales Employee session 58) |
| Resolved Failures | 0 |
| Hard Blockers (pre-existing) | 1 (Billing — Stripe not integrated) |
| Last Updated | 2026-07-08 (Session 58 — Sales Employee full E2E, real browser via Canary/Playwright) |

---

## Status Legend
| Symbol | Meaning |
|---|---|
| ❌ FAIL | Test ran, assertion failed |
| ✅ PASS | Test ran, all assertions passed |
| 🔲 BLOCKED | Cannot run — missing dependency |
| ⏭️ SKIPPED | Already verified, intentionally skipped |
| 🔁 REGRESSION | Was passing, now failing |
| ⛔ HARD BLOCKER | Pre-existing — not built yet |

---

## Pre-Existing Hard Blockers (Not Claude-Found — From Checklist)

### ⛔ HB-001 — Billing Section Not Implemented
- **Area**: Billing
- **Status**: ⛔ Hard Blocker (pre-launch)
- **Detail**: Entire billing section is a static UI placeholder. Stripe is not integrated.
- **Impact**: Platform cannot process payments before launch.
- **Resolves When**: Stripe integration is built and wired.

---

## Active Failures
> Claude appends new failures here chronologically.
> Move entry to Resolved section once developer fixes and Claude re-verifies.

---
**ID**: TC-SALES-MA-001
**Session**: 58 (Sales Employee full E2E QA)
**Date**: 2026-07-08
**Area**: Sales Employee — Market Agent
**Description**: "What's Changing" banner never shows on page load, even though a valid summary exists from a prior completed run — only appears after triggering a brand-new refresh in the current browser session

**Preconditions**:
- Logged in as rahul.excel2011@gmail.com, business "Woyce Tech"
- A completed Market Agent run already exists from a prior session (it does — 7 cards with real data, confirmed in DB with `whats_changing_summary` populated on that run)

**Steps**:
1. Navigate to /dashboard/sales/market-agent (fresh page load, no refresh triggered in this session)
2. Look for the "What's Changing" banner above/among the analyst cards

**Expected**: Per the API contract (`docs/market-agent-api-contract.md`): "For the 'What's Changing' top-of-page summary, use the whats_changing_summary from the most recent run." All 7 cards render correctly with real data, so a completed run clearly exists — the summary should be derivable and shown.
**Actual**: Banner text "What's Changing" does not appear anywhere on the page (confirmed via full page text search). All 7 analyst cards render correctly.
**Status**: ❌ FAIL

**Cause (Claude's Analysis)**:
> `MarketAgent.tsx` — the `whatsChanging` state is ONLY ever set inside the `useEffect` watching `polledRun` (line ~50-56), which is only populated after the user actively triggers a new refresh via the "Refresh" button in the current session. The initial-mount `fetchCards()` call only hits `GET /cards` and never fetches a run's summary, so on a fresh page load `whatsChanging` stays `null` and `MarketWhatsChangingBanner` correctly renders nothing (`if (!summary) return null`) — the component itself is fine, it's just never fed data on load.
>
> **This is fixable without any backend change**: `listMarketCards`'s response already includes `run_id` on every card (confirmed directly against the DB — all 7 cards from the same refresh share one `run_id`). The frontend could take `cards[0]?.run_id` after the initial fetch and call the existing `GET /sales/market-agent/runs/{run_id}` endpoint to populate `whatsChanging` on mount, instead of waiting for an actively-triggered refresh.

**Evidence**:
- Full-page text search for "What's Changing" returned no match on a freshly-loaded page with 7 real, populated cards
- DB confirms `market_analysis_cards` rows all share `run_id: fc330b92-83fd-426a-b565-7adc1c9c1226`, and that run's `whats_changing_summary` is populated (verified in an earlier backend session)
- Source: `ai-employees-app/src/pages/dashboard/sales/MarketAgent.tsx:47-56` (state logic), `src/components/sales/MarketWhatsChangingBanner.tsx:9` (correctly returns `null` when unfed)

**Severity**: Medium — not a crash, but a real user-facing feature (the "what changed" summary explicitly called for in the mockup/contract) is silently absent on every normal page visit, only appearing right after the user personally triggers a refresh
**Reproducible**: Always, on any page load/navigation that isn't immediately preceded by a refresh triggered in that same session
**Workaround**: No — would need a source change (not made — QA session, findings only)
---

---
**ID**: TC-SALES-LR-003
**Session**: 58 (Sales Employee full E2E QA)
**Date**: 2026-07-08
**Area**: Sales Employee — Lead Researcher
**Description**: No URL format validation anywhere (frontend or backend) — a real, paid Apify run is started for any string at all, even obvious garbage

**Preconditions**:
- Logged in as rahul.excel2011@gmail.com, business "Woyce Tech"
- On the Lead Researcher "New Analysis" tab

**Steps**:
1. Enter `not-a-real-url` (not even URL-shaped, let alone a LinkedIn URL) into the profile URL field
2. Click "Generate Report"

**Expected**: A validation error should be shown immediately (client-side, or at minimum a fast 4xx from the backend) rejecting non-LinkedIn-URL input before any external API call is made.
**Actual**: The frontend accepted the input with no validation, disabled the form (loading state), and the backend (`POST /sales/lead-researcher/lookup`, `LeadLookupRequest.linkedin_url: str` — no format constraint) accepted it and started a real Apify actor run (`lnVTmjsFDAq2eZrru`). The run eventually "succeeded" on Apify's side (cost: $0.00005 — negligible but non-zero) with zero results, and our own webhook correctly detected the empty dataset and marked the lookup `failed` with a clear message ("Apify run finished but returned no profile data."). So the end state is graceful (no crash, no stuck job, clear error), but a real external API call and real (if tiny) cost is spent on input that's trivially rejectable in under a millisecond client-side.

**Status**: ❌ FAIL

**Cause (Claude's Analysis)**:
> Two independent gaps, either of which alone would fix this: (1) Frontend — `NewAnalysisTab.tsx`'s input has no pattern/format validation before calling `startLeadLookup`. (2) Backend — `backend/app/schemas/sales.py`'s `LeadLookupRequest.linkedin_url` is a bare `str`, no regex/format validator (unlike the recipient-email validator added to `report_scheduler.py`'s schema in the same session, which shows the pattern already exists elsewhere in this codebase and could be reused here).

**Evidence**:
- Backend logs: `POST /sales/lead-researcher/lookup` returned 200 for `linkedin_url: "not-a-real-url"`, followed by a real Apify run start
- Apify run `lnVTmjsFDAq2eZrru`: status SUCCEEDED, usageTotalUsd 0.00005
- DB: `lead_lookups` row `3110faa5-2ab6-43f0-a42c-70dcf17cc0d1` — status `failed`, error "Apify run finished but returned no profile data."
- Source: `ai-employees-app/src/components/sales/NewAnalysisTab.tsx`, `backend/app/schemas/sales.py`

**Severity**: Low-Medium — no crash or data corruption, cost per bad submission is negligible today, but this scales linearly with how many bad submissions happen (typos, copy-paste errors, or repeated misuse) and burns real Apify quota/time (2-3 min wait, one Apify run) for something a regex could reject instantly
**Reproducible**: Always
**Workaround**: No — would need a source change (not made — QA session, findings only)
---

---
**ID**: TC-SALES-CA-004
**Session**: 58 (Sales Employee full E2E QA)
**Date**: 2026-07-08
**Area**: Sales Employee — Competitor Agent
**Description**: Sparse-data detection regex never matches real backend output — "Limited data available for this platform" note never renders, even when data genuinely is sparse

**Preconditions**:
- Logged in as rahul.excel2011@gmail.com, business "Woyce Tech"
- A competitor report exists with at least one platform having thin/no data (tested with HubSpot's Instagram section)

**Steps**:
1. Navigate to /dashboard/sales/competitor-agent
2. Click "View Report" on a competitor whose report includes a sparse platform (e.g. Instagram with little activity)
3. Read the platform's Summary, Pricing signals, Feature launches, and General activity text

**Expected**: Per the platform's own API contract (`docs/competitor-agent-api-contract.md`) and the frontend's own intent (`SPARSE_DATA_PATTERN` in `CompetitorReportDialog.tsx:28`), sparse/empty data should show "Limited data available for this platform." instead of being presented as confirmed fact.
**Actual**: Real report data for HubSpot's Instagram section reads: "There is no recent activity found on HubSpot's Instagram account, indicating a lack of engagement or content updates on this platform." — the regex `/no (activity|data|signal)s? found/i` requires "no" to be immediately followed by "activity/data/signal(s)" then "found", with nothing in between. The real LLM phrasing almost always inserts a qualifier ("no **recent** activity found"), so the pattern never matches. Verified in isolation with Node: the exact real-world string returns `false` against the regex, while only a highly literal "No activity found." (not real output) returns `true`. Also affects `pricing_signals`/`feature_launches`, which our own backend prompt (`competitor_agent.py` `SYNTHESIS_PROMPT`) explicitly instructs to output the literal string `"Nothing found."` for absent data — that string also does not match the regex at all (no "no X found" phrase present). Net effect: the sparse-data indicator has never actually fired against real production-shaped data in this test.
**Status**: ❌ FAIL

**Cause (Claude's Analysis)**:
> `ai-employees-app/src/components/sales/CompetitorReportDialog.tsx:28` — `SPARSE_DATA_PATTERN = /no (activity|data|signal)s? found/i` is too narrow for the actual phrasing GPT produces and for the backend's own literal `"Nothing found."` placeholder string. A broader pattern (e.g. matching "nothing found" OR "no [adjective]* (activity|data|signal)" with an optional word in between) would need to be verified against a larger sample of real outputs before considering it fixed — not just patched to match this one observed phrase.

**Evidence**:
- Screenshot: docs/qa-screenshots/TC-SALES-CA-004-sparse-data.png
- Node verification: `/no (activity|data|signal)s? found/i` tested `false` against the real Instagram summary text, `false` against literal `"Nothing found."`, `true` only against the contrived exact phrase `"No activity found."`
- Source: `ai-employees-app/src/components/sales/CompetitorReportDialog.tsx:28-35,166-185`

**Severity**: Medium — not a crash or data-loss bug, but it silently defeats a specific, deliberate honesty safeguard requested in the API contract (don't present sparse/unreliable scraped data as confirmed fact)
**Reproducible**: Always, for any report where a platform's data is genuinely sparse
**Workaround**: No — purely a frontend detection-logic issue, would need a source change (not made — QA session, findings only)
---

---
**ID**: TC-TEAM-006
**Session**: 4
**Date**: 2026-04-29
**Area**: Team Management
**Description**: Remove User fires immediately with no confirmation dialog

**Preconditions**:
- Logged in as super_admin
- At least one non-super-admin team member exists

**Steps**:
1. Navigate to /dashboard/team
2. Open the ⋮ dropdown for any non-super-admin member
3. Observe "Remove User" menu item

**Expected**: Clicking "Remove User" should open an AlertDialog asking the admin to confirm removal before calling the API
**Actual**: Source code review confirmed — `handleRemoveUser` is called directly from the `DropdownMenuItem` `onClick` with no AlertDialog, no `confirm()`, and no intermediate state. Removal fires immediately. Test safely escaped by pressing Escape before clicking.
**Status**: ❌ FAIL

**Cause (Claude's Analysis)**:
> `TeamManagement.tsx:373-381` — `DropdownMenuItem` with `onClick={() => handleRemoveUser(member)}` calls `removeUserFromBusiness` immediately. No AlertDialog is rendered anywhere in the component for this action.

**Evidence**:
- Screenshot: docs/qa-screenshots/TC-TEAM-006-dropdown-open.png
- Screenshot: docs/qa-screenshots/TC-TEAM-006-escaped-without-click.png
- Source: ai-employees-app/src/pages/dashboard/TeamManagement.tsx:373-381

**Severity**: High
**Reproducible**: Always
**Workaround**: No — admins can accidentally remove team members with a single click
---

---
**ID**: TC-ROLES-002
**Session**: 5 → retested Session 7
**Date**: 2026-04-29
**Area**: Roles & Permissions
**Description**: Permission toggle does not persist — PUT fires but targets wrong role_id (stale closure); state reverts on reload

**Preconditions**:
- Logged in as super_admin
- At least one role selected on Roles & Permissions page (tested with QA Test Role)

**Steps**:
1. Navigate to /dashboard/roles-permissions
2. Select any role tab (e.g. QA Test Role)
3. Click a permission checkbox to toggle it off
4. Wait 5s for API call
5. Reload page; re-select same role tab

**Expected**: PUT `/roles/{id}/permissions` is sent for the SELECTED role; state persists after reload
**Actual**: PUT IS sent and returns 200 OK — but for the role that was auto-selected when the page loaded (not the role the user clicked). On reload, the targeted role shows no change for that checkbox because the permissions saved were for a different role.
**Status**: ❌ FAIL (partial fix deployed — new root cause identified)

**Cause (Claude's Analysis)**:
> **Session 5 root cause (guard after optimistic update) was fixed in Session 7 deploy** — the guard `if (!selectedRoleId || !isAdminUser) return` is now correctly FIRST in `togglePermission`. This resolved the zero-PUT issue.
>
> **New root cause (Session 7)**: `selectedRoleId` in the `togglePermission` closure holds a stale value from the role that was auto-selected when the page initially loaded, not the role the user last clicked. Backend logs confirm: `PUT /roles/5dd0e06d.../permissions 200 OK` was the auto-loaded role; `GET /roles/fb9b7b29.../permissions` was QA Test Role (the clicked tab). The toggle saved to `5dd0e06d` but the UI displayed `fb9b7b29`'s permissions — a silent wrong-role save.
>
> The stale closure persists because `selectedRoleId` is not being captured correctly in the `onClick` handler of the checkbox at the time of the role-tab click. This is likely a React closure capture issue or a `useCallback` with stale dependency.

**Evidence**:
- Session 7 backend logs: `PUT /roles/5dd0e06d-3800-4bc1-86d6-678d352c6223/permissions HTTP/1.1" 200 OK` (auto-selected role)
- Session 7 backend logs: `GET /roles/fb9b7b29-aaf9-443f-a99a-275e325e12bd/permissions` (QA Test Role — tab clicked by test)
- Screenshot: docs/qa-screenshots/TC-ROLES-002-RETEST-before-toggle.png
- Screenshot: docs/qa-screenshots/TC-ROLES-002-RETEST-after-reload.png (state still "checked" for QA Test Role)
- Source: ai-employees-app/src/pages/dashboard/RolesPermissions.tsx — `togglePermission` stale closure on `selectedRoleId`

**Severity**: High — permission changes appear to save (PUT 200) but are silently applied to the wrong role; admins cannot reliably manage permissions
**Reproducible**: Always (confirmed Session 4, 5, 7)
**Workaround**: No — feature is non-functional for saving correctly
---

---
**ID**: TC-ROLES-001
**Session**: 4
**Date**: 2026-04-29
**Area**: Roles & Permissions
**Description**: Test false-fail — role creation API response exceeded 2s timeout; feature confirmed working

**Preconditions**:
- Migrations 20260428000001–000003 applied
- Logged in as super_admin

**Steps**:
1. Navigate to /dashboard/roles-permissions
2. Click "New Role"
3. Fill name "QA Test Role", base "Team Member", description
4. Click "Create Role"
5. Wait 2s for toast + tab to appear

**Expected**: Toast `Role "QA Test Role" created` + new role tab visible within 2s
**Actual**: After 2s — dialog still showing spinner, toast=false, tabVisible=false. However, TC-ROLES-002 screenshot confirms "QA Test Role" tab appeared when that test ran (seconds later), proving the role WAS created.
**Status**: ❌ FAIL (test false-fail — feature works)

**Cause (Claude's Analysis)**:
> API response time for `createCustomRole` exceeded the 2-second wait in the test script. The Supabase write completed after the test moved on. Toast appeared and dismissed before the test checked. Feature is functional — test script needs a longer `waitForTimeout` (suggest 5s) after clicking Create Role.

**Evidence**:
- Screenshot: docs/qa-screenshots/TC-ROLES-001-after-create.png (dialog still open, spinner on Create Role btn)
- Screenshot: docs/qa-screenshots/TC-ROLES-002-toggled.png (QA Test Role tab visible — confirms creation succeeded)

**Severity**: Low (test script issue, not a product bug)
**Reproducible**: Likely — API appears consistently slow for role creation
**Workaround**: N/A — feature works; test script fix needed
**Note**: "QA Test Role" was created in DB and remains. Manual cleanup required.
---

---
**ID**: TC-ROLES-002
**Session**: 4
**Date**: 2026-04-29
**Area**: Roles & Permissions
**Description**: Permission checkbox toggle — indeterminate result due to stale Playwright locator

**Preconditions**:
- QA Test Role exists (created in TC-ROLES-001)
- Logged in as super_admin

**Steps**:
1. Navigate to /dashboard/roles-permissions
2. Select "QA Test Role" tab
3. Click "Support" permission checkbox (was checked)
4. Wait 1s, read data-state attribute

**Expected**: data-state changes from "checked" to "unchecked"; "Saving…" indicator appears; save persists
**Actual**: data-state stayed "checked" after click. However, "Saving…" indicator WAS observed — confirming the API call was triggered.
**Status**: ❌ FAIL (test likely false-fail — indeterminate; manual re-test recommended)

**Cause (Claude's Analysis)**:
> "Saving…" indicator confirms `togglePermission` was called and the API was hit. The Playwright `data-state` read likely returned a stale value after React re-rendered the component following the optimistic state update. The save may have succeeded or failed (reverted) — cannot determine from test output alone. Manual verification of whether the Support permission actually unchecked+saved is required.

**Evidence**:
- Screenshot: docs/qa-screenshots/TC-ROLES-002-toggled.png (QA Test Role selected; Support checkbox shown; Saving… visible in header)
- Screenshot: docs/qa-screenshots/TC-ROLES-002-fail.png

**Severity**: Low (test script issue; feature status unclear)
**Reproducible**: Unknown
**Workaround**: Manual test — toggle Support permission for QA Test Role and reload page to verify persistence
---

---

---
**ID**: TC-SUPPORT-001
**Session**: 7
**Date**: 2026-04-29
**Area**: Support
**Description**: Support form submits successfully; backend returns 409 due to Gmail OAuth not connected in test environment

**Preconditions**:
- Logged in as super_admin
- Navigate to /dashboard/support

**Steps**:
1. Navigate to /dashboard/support
2. Observe Name + Email auto-filled from profile
3. Fill Subject: "QA Session 7 — automated support test"; Message: test content
4. Click Submit

**Expected**: POST `/support/submit` reaches backend; 200 on success (requires Gmail OAuth connected) or 409 if not connected
**Actual**: POST `/support/submit` reached backend → 409 Conflict. Error toast: "Gmail is not connected for this business. Connect Gmail before submitting support requests."
**Status**: ✅ PASS (environment constraint — not a product bug)

**Cause (Claude's Analysis)**:
> Form submission logic is fully functional. Name + Email auto-fill confirmed. Subject + Message fields present and fillable. POST `/support/submit` reaches backend correctly. The 409 response is expected behavior — the backend requires Gmail OAuth to be connected (`get_valid_access_token` + `has_gmail_send_scope` checks in `backend/app/routers/support.py`). In the test account, Gmail OAuth is not connected. This will work correctly for any business that has connected Gmail in Settings → Integrations.

**Evidence**:
- Backend log: `POST /support/submit HTTP/1.1" 409 Conflict`
- Error message in UI: "Gmail is not connected for this business. Connect Gmail before submitting support requests."
- Screenshot: docs/qa-screenshots/TC-SUPPORT-001-page-load.png
- Screenshot: docs/qa-screenshots/TC-SUPPORT-001-after-submit.png

**Severity**: N/A — not a bug; known dependency on Gmail OAuth
**Reproducible**: Always (when Gmail not connected)
**Workaround**: Connect Gmail OAuth in Settings → Integrations first
---

## Failure Entry Format
> Claude uses this exact block for every new failure found.

```
---
**ID**: TC-[number]
**Session**: [number]
**Date**: [YYYY-MM-DD]
**Area**: [Auth | Calendar | Settings | Team | Roles | AI Employee | Phone | Support]
**Description**: one-line summary

**Preconditions**:
- Servers running at localhost:3000 / 8000
- [other required state]

**Steps**:
1.
2.
3.

**Expected**: what should have happened
**Actual**: what actually happened
**Status**: ❌ FAIL

**Cause (Claude's Analysis)**:
> Specific technical reason — component, endpoint, HTTP status, console error, DOM state.

**Evidence**:
- Screenshot: docs/qa-screenshots/TC-[id].png
- Console error: ``
- Network call: ``

**Severity**: Critical | High | Medium | Low
**Reproducible**: Always | Sometimes | Once
**Workaround**: Yes / No
---
```

---

## Resolved Failures
> Move here after fix is deployed and Claude re-verifies with ✅.

*None yet.*

---

## Session Logs
> One block per session. Claude appends before closing.

### Session 0 — 2026-04-29 — Baseline
- Status: Pre-session setup only
- Tests Run: 0
- Notes: Files created, coverage map built from CLIENT_LAUNCH_CHECKLIST.md
- Pre-conditions confirmed: ❌ Not yet checked
- Next: Session 1 → Calendar + Profile + Business Settings

### Session 1 — 2026-04-29 — Calendar Flows
- Status: ✅ Complete
- Tests Run: 8 | Passed: 8 | Failed: 0 | Blocked: 0
- Pre-conditions: Migrations ✅ all applied | Edge functions ✅ redeployed | Resend DNS ✅ live
- Port corrections applied: frontend=8080, backend=8003
- Notes: Initial run had TC-CAL-005 false-fail — `has-text("day")` matched "today" button; fixed to exact regex `/^day$/`
- Next: Session 2 → Profile Settings + Business Settings + Global Settings

### Session 2 — 2026-04-29 — Profile Settings
- Status: ✅ Complete
- Tests Run: 4 | Passed: 4 | Failed: 0 | Blocked: 0
- Notes: `tripleClick` not a Playwright method — fixed to use `fill()` directly (already replaces input content)
- TC-PROF-001: Change Photo button + hidden file input present ✅
- TC-PROF-002: Name field edit + save → success toast + DB write confirmed ✅
- TC-PROF-003: Password validation — short (<8 chars) and mismatch both rejected correctly ✅
- TC-PROF-004: Connected Google Accounts section renders; Google status shows "Connected" ✅
- Next: Session 3 → Business Settings + Global Settings

### Session 3 — 2026-04-29 — Business Settings
- Status: ✅ Complete
- Tests Run: 5 | Passed: 5 | Failed: 0 | Blocked: 0
- TC-BIZ-001: Company info all field groups (Company Info, Contact, Operating, Consumer Protection) render and save ✅
- TC-BIZ-002: Business hours — 7 day rows, toggling closed→open shows time selects, "Used by AI Agent Scheduler" badge present ✅
- TC-BIZ-003: Logo upload — UPLOAD button, hidden file input, 500px size hint all present ✅
- TC-BIZ-004: Gmail card renders with Connect button; search filter correctly hides Twilio when "gmail" typed ✅
  - Note: location banner not shown (no location selected in headless session — expected; Gmail Connect correctly requires location)
  - Note: business name stored in DB as "Downtown" not "Downtown Barber Shop"
- TC-BIZ-005: Danger Zone tab visible (super_admin confirmed); dialog opens; confirm button stays disabled with empty/wrong name; Cancel closes safely ✅
- Next: Session 4 → Global Settings + Team Management

### Session 7 — 2026-04-29 — TC-ROLES-002 Retest + Support Email
- Status: ✅ Complete (3 tests: 1 pass, 1 fail, 1 blocked)
- Tests Run: 3 | Passed: 1 | Failed: 1 | Blocked: 1
- Pre-checks: QA Test Role in DB ✅ | QA Test Location in DB ✅ | TC-ROLES-002 fix deployed ✅ | TC-TEAM-006 fix NOT deployed ✅
- TC-ROLES-002-RETEST: ❌ STILL FAILING — new root cause identified: PUT IS sent (200 OK) but targets the wrong role_id (auto-selected role on page load, not the clicked tab). Stale `selectedRoleId` closure. Session 5 original bug (guard after optimistic update) was fixed; new bug is stale closure capturing wrong role.
- TC-TEAM-006-RETEST: 🔲 BLOCKED — fix not deployed
- TC-SUPPORT-001: ✅ PASS (env constraint) — POST /support/submit reaches backend; 409 because Gmail OAuth not connected in test account; form submission logic confirmed functional
- Side effects: test data in DB (QA Test Role, QA Test Location) — developer cleanup needed
- **HEADLESS QA COMPLETE** — remaining items require live voice calls (AI behavior) or Stripe (Billing)

### Session 6 — 2026-04-29 — CSE Structural Checks
- Status: ✅ Complete (16 tests: 6 pass, 0 fail, 10 blocked)
- Pre-checks: QA Test Role still in DB ⚠️ | QA Test Location still in DB ⚠️ | TC-ROLES-002 fix NOT deployed | TC-TEAM-006 fix NOT deployed
- TC-ROLES-002-RETEST: 🔲 BLOCKED — fix not deployed
- TC-TEAM-006-RETEST: 🔲 BLOCKED — fix not deployed
- TC-CSE-SETUP: ✅ PASS — setup page at /dashboard/customer-service/setup renders; checklist shows 5/8 tasks completed (A:phone✅ B:voice○ C:hours✅ D:forwarding✅ E:calendar○ F:booking✅ G:greeting○ H:test✅); agent activity shows real call history
- TC-CSE-DASHBOARD: ✅ PASS — Agent Performance page renders
- TC-CSE-RECORDINGS: ✅ PASS — Call Recordings page renders with call history UI
- TC-CSE-SCHEDULER: ✅ PASS — Scheduler page renders with hours/schedule UI
- TC-CSE-FORWARDING: ✅ PASS — Call Forwarding page renders
- TC-CSE-SETTINGS: ✅ PASS — Agent Settings page renders with settings UI
- TC-AI-001 through TC-AI-008: 🔲 BLOCKED — AI agent uses voice-only interface (useWebAgentCall / LiveKit WebRTC); headless Playwright cannot provide microphone access; must test via live browser "Test with Web Call" button or actual phone call
- Screenshot: docs/qa-screenshots/TC-CSE-SETUP-page.png — setup checklist + agent activity clearly visible

### Session 5 — 2026-04-29 — Roles Verify + Phone Numbers + Locations
- Status: ✅ Complete (5 tests run)
- Tests Run: 5 | Passed: 3 | Failed: 1 | Blocked: 1
- Pre-checks: QA Test Role still in DB ✅ | TC-TEAM-006 fix NOT deployed ✅
- TC-ROLES-002-RETEST: ❌ REAL BUG CONFIRMED — permission toggle sends zero PUT requests to backend; optimistic unchecked reverts to checked on reload; root cause is early return in togglePermission (line 102, RolesPermissions.tsx)
- TC-TEAM-006-RETEST: 🔲 BLOCKED — developer fix not deployed
- TC-PHONE-001: ✅ PASS — phone numbers page renders per-location; "Assign number" opens inline form with US country + area code input; purchase flow present. Note: route is /dashboard/settings/phone-numbers (not /dashboard/phone-numbers)
- TC-PHONE-002: ✅ PASS — Canadian number (647) 584-4089 confirmed assigned to Downtown office and displayed
- TC-LOC-001: ✅ PASS — Add Location dialog opens (4 fields); "QA Test Location" created (backend seed confirmed: `POST /locations/{id}/seed 200 OK`); slow API >3s but functional. Route: /dashboard/settings/locations
- Side effects: "QA Test Location" created — needs manual cleanup
- Note: Backend API response times consistently slow (>2-3s) for creation operations — role create, location create both required longer waits than 3s

### Session 4 — 2026-04-29 — Global Settings + Team Management + Roles & Permissions
- Status: ✅ Complete (10 tests run)
- Tests Run: 10 | Passed: 7 | Failed: 3 (1 real bug; 2 test timing/locator false-fails)
- TC-GLOB-001: Language & Region — 4 selects present; time format toggled (12h↔24h) and saved with success toast ✅
- TC-GLOB-002: Brand Voice — wizard navigated to "Do Not Say" step; "QATestWord" added/badge appeared/removed; saved ✅
- TC-TEAM-001: Invite dialog — email input, role dropdown (Admin/User), 2 location checkboxes present; Cancel safe ✅
- TC-TEAM-002: Change Role — dialog opens; role changed+saved with "Role updated successfully" toast; restored ✅
- TC-TEAM-003: Manage Locations — dialog opens with 2 location checkboxes; Cancel closes safely ✅
- TC-TEAM-004: Manage Services — dialog opens successfully ✅
- TC-TEAM-005: Manage Hours — weekly availability dialog opens ✅
- TC-TEAM-006: Remove User — ❌ REAL BUG — no confirmation dialog; action fires immediately on DropdownMenuItem click (TeamManagement.tsx:373-381)
- TC-ROLES-001: ❌ FALSE-FAIL — role WAS created (confirmed by TC-ROLES-002 screenshot); API response >2s exceeded test timeout
- TC-ROLES-002: ❌ INDETERMINATE — "Saving…" indicator confirmed API was called; Playwright read stale checkbox state; manual re-test needed
- Note: "QA Test Role" created in DB — needs manual cleanup
- Next: Session 5 → Phone Numbers + Locations + manual verify TC-ROLES-002

---

### Session 58 — 2026-07-08 — Sales Employee full E2E (Canary/Playwright, real browser)
- Status: ✅ Complete
- Tool: Canary session recording (real Playwright browser, trace/video/HAR/console) — session `sales-employee-e2e-qa-mrbvotec-32a925`, report at `~/.canary/sessions/sales-employee-e2e-qa-mrbvotec-32a925/report.html`
- Tests Run: 25 | Passed: 22 | Failed: 3 (all real bugs)
- Scope: full logged-in flow (rahul.excel2011@gmail.com, business "Woyce Tech") across all 4 Sales Employee modules — first time this product's frontend was QA'd end-to-end in a real browser, not just backend curl testing
- TC-SALES-NAV-001/002: login + navigation across all 4 sub-pages ✅
- Lead Researcher (6 tests, 5 pass 1 fail): real LinkedIn lookup → full card render ✅ (honest "Unverified guess" confidence framing confirmed), History/Saved Leads tabs ✅, bookmark toggle ✅, dedupe across 2 browser tabs ✅ (backend log confirmed "already in flight ... reusing"). TC-SALES-LR-003 ❌ REAL BUG — no URL validation anywhere, a real paid Apify run starts for garbage input (e.g. "not-a-real-url"), fails gracefully but wastefully.
- Competitor Agent (6 tests, 5 pass 1 fail): add competitor with strong (hubspot.com) and weak (example.com) social presence both handled correctly, report generation/history ✅. TC-SALES-CA-004 ❌ REAL BUG — sparse-data detection regex (`SPARSE_DATA_PATTERN`) never matches real LLM output phrasing or the backend's own literal "Nothing found." placeholder; "Limited data available" indicator has never actually fired against real data.
- Market Agent (5 tests, 4 pass 1 fail): manual refresh ✅, bookmark ✅, custom analyst creation + inclusion in next refresh ✅ (confirmed real Exa-sourced content for the custom "Pricing Watchdog" analyst). TC-SALES-MA-001 ❌ REAL BUG — "What's Changing" banner never populates on page load despite valid data existing, only appears right after an actively-triggered refresh in the same session; root cause confirmed fixable without backend changes (cards already carry `run_id`, frontend just never fetches the run's summary on mount).
- Report Scheduler (6 tests, all pass): empty-recipient guard ✅ (exact expected text), live preview via sandboxed iframe ✅ (no script tags — safe), real test-send confirmed via direct API response capture (`{"sent":true,"detail":"Test email sent to rahul.excel2011@gmail.com."}`), module-toggle preview update ✅.
- All 3 failures logged to Active Failures above: TC-SALES-LR-003, TC-SALES-CA-004, TC-SALES-MA-001. Test sheet: `docs/sales-employee-qa-test-sheet.md`.
- Next: fixes for the 3 findings (not made this session — QA only, no source edits); re-verify once fixed.

---
*Maintained by Claude Code during QA sessions. Source code is never modified.*