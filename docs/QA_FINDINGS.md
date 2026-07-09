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
| Open Failures | 2 (TC-TEAM-006, TC-ROLES-002 — real bugs, older platform sessions) |
| Resolved Failures | 3 (TC-SALES-LR-003, TC-SALES-CA-004, TC-SALES-MA-001 — Sales Employee session 58, fixed same session and re-verified live) |
| Hard Blockers (pre-existing) | 1 (Billing — Stripe not integrated) |
| Last Updated | 2026-07-08 (Session 58 — Sales Employee full E2E QA + same-session fixes, real browser via Canary/Playwright) |

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

---
**ID**: TC-SALES-MA-001
**Session found**: 58 (Sales Employee full E2E QA, 2026-07-08)
**Area**: Sales Employee — Market Agent
**Description**: "What's Changing" banner never showed on page load, only after an actively-triggered refresh in the same session, despite a valid summary already existing.
**Fix**: `MarketAgent.tsx`'s `fetchCards()` now uses `cards[0]?.run_id` (already present on every card) to call the existing `getMarketRun` endpoint and populate `whatsChanging` on mount — no backend change needed.
**Status**: ✅ RESOLVED — re-verified live: fresh page load (post-login, no refresh triggered) now shows the banner with real content immediately, confirmed via screenshot.
**Commit**: `ai-employees-app` `fd0c281`
---

---
**ID**: TC-SALES-LR-003
**Session found**: 58 (Sales Employee full E2E QA, 2026-07-08)
**Area**: Sales Employee — Lead Researcher
**Description**: No URL format validation anywhere — a real, paid Apify run started for any garbage string.
**Fix**: Added matching validators on both sides — backend `field_validator` on `LeadLookupRequest.linkedin_url` in `schemas/sales.py` (mandatory, protects direct API callers too) and a frontend regex check in `NewAnalysisTab.tsx` (immediate feedback, no round-trip). Same pattern already used for `report_schedules` recipient validation.
**Status**: ✅ RESOLVED — re-verified live: submitting `"not-a-real-url"` now shows an inline error toast and confirmed via backend logs that **no request reached the backend at all**. Backend validator separately confirmed to accept all real-world LinkedIn URL variants (http/https, with/without www, trailing slash, query strings) and reject garbage.
**Commits**: `sam-backend` `ad8c6fc`, `ai-employees-app` `3d4ccdc`
---

---
**ID**: TC-SALES-CA-004
**Session found**: 58 (Sales Employee full E2E QA, 2026-07-08)
**Area**: Sales Employee — Competitor Agent
**Description**: Sparse-data detection regex never matched real backend output; the "Limited data available" honesty safeguard never fired.
**Fix**: Root-caused as a structural problem, not a phrasing edge case — pattern-matching free-form LLM prose after the fact is inherently fragile. Real fix: `SYNTHESIS_PROMPT` in `competitor_agent.py` now asks the LLM to directly judge and return `data_availability: "sparse" | "sufficient"` per platform, rather than inferring it from text afterward. Frontend now uses this field as the primary signal; the old regex is kept only as a fallback for reports generated before this field existed (and broadened slightly, though intentionally not made "perfect" — new reports use the reliable field).
**Status**: ✅ RESOLVED — re-verified two ways: (1) re-ran synthesis against real stored HubSpot platform data (no new Apify cost) and confirmed the LLM correctly judged Instagram as "sparse" and the other 3 platforms as "sufficient"; (2) live in the browser, the existing HubSpot report (predating this field) now correctly shows "Limited data available for this platform" on Instagram via the fallback regex, with no such note on LinkedIn.
**Commits**: `sam-backend` `43cd1b7`, `ai-employees-app` `d9aba07`
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
- **Update, same session**: all 3 findings fixed and live-verified immediately after this QA pass (user explicitly asked to move from QA mode to fixing). See Resolved Failures above for fix details + commits. TC-SALES-MA-001 fixed with a frontend-only change (reuses existing `run_id` on cards). TC-SALES-LR-003 fixed with matching frontend+backend URL validators. TC-SALES-CA-004 fixed at the root — replaced regex-based sparse-data detection with an AI-judged `data_availability` field, verified against real stored data.

---
*Maintained by Claude Code during QA sessions. Source code is never modified.*