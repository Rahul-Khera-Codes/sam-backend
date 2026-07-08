# Sales Employee — Full E2E QA Test Sheet

> Created 2026-07-08. Full end-to-end browser testing of all 4 Sales Employee modules
> (Lead Researcher, Competitor Agent, Market Agent, Report Scheduler), backed by real
> browser sessions (Canary/Playwright) against the actual frontend + backend + real
> external APIs (Apify, Exa, Gmail) — not curl shortcuts, not backend-only checks.
>
> **Rule:** Claude never modifies source code during this pass. Findings only —
> logged to `docs/QA_FINDINGS.md` in TC-[id] format.

---

## Environment

| Target | URL |
|---|---|
| Frontend | http://localhost:8080 |
| Backend | http://localhost:8003 (tunneled via ngrok for Apify webhooks) |
| Test login | rahul.excel2011@gmail.com |
| Test business | Woyce Tech (`f46ce260-45da-4db8-9bc1-b0af01ec3acc`) |

## Status Legend
| Symbol | Meaning |
|---|---|
| ✅ PASS | Test ran, all assertions passed |
| ❌ FAIL | Test ran, assertion failed — logged to QA_FINDINGS.md |
| 🔲 BLOCKED | Cannot run — missing dependency |
| ⏳ PENDING | Not yet executed |

---

## 0. Cross-cutting

| ID | Flow | Test Data | Expected | Status |
|---|---|---|---|---|
| TC-SALES-NAV-001 | Login with test credentials | rahul.excel2011@gmail.com / Rahul@321 | Lands on dashboard | ✅ PASS |
| TC-SALES-NAV-002 | Navigate to each of the 4 Sales Employee sub-pages via sidebar/layout | — | All 4 pages load without error | ✅ PASS |

## 1. Lead Researcher

| ID | Flow | Test Data | Expected | Status |
|---|---|---|---|---|
| TC-SALES-LR-001 | Page loads | — | Empty/new-analysis state renders | ✅ PASS |
| TC-SALES-LR-002 | Submit a real LinkedIn URL, wait for completion | `https://www.linkedin.com/in/arun-kumar-64450b278/` (realistic, already scraped once before) | Card renders with name, company, email confidence ("Unverified guess"), insights, outreach draft | ✅ PASS — full card verified, all fields populated correctly, honest "Unverified guess (catch_all)" framing confirmed |
| TC-SALES-LR-003 | Submit an invalid/malformed URL | `not-a-real-url` (dummy) | Client or server validation error shown, no lookup created | ❌ FAIL — see QA_FINDINGS.md. No validation anywhere; a real (if tiny) paid Apify run was started for garbage input. Eventually fails gracefully, but wastefully. |
| TC-SALES-LR-004 | View History tab | — | Past lookups list renders, including recovered ones from session 58 | ✅ PASS |
| TC-SALES-LR-005 | Save/bookmark a completed lead from history | — | Save state toggles and persists on reload | ✅ PASS — confirmed `is_saved` flips correctly in DB for the exact clicked row |
| TC-SALES-LR-006 | Submit the same URL twice quickly (dedupe check) | Same URL as TC-002, resubmitted while first is still `running` | Second submit reuses the same lookup id, not a new one | ✅ PASS — tested via 2 separate browser tabs (same session), backend log confirmed "already in flight ... reusing" |

## 2. Competitor Agent

| ID | Flow | Test Data | Expected | Status |
|---|---|---|---|---|
| TC-SALES-CA-001 | Page loads | — | Empty/add-competitor state renders | ✅ PASS |
| TC-SALES-CA-002 | Add competitor with strong social presence | `https://www.hubspot.com` (realistic, matches earlier backend test) | Discovery completes, all 4 platform icons populate | ✅ PASS (pre-existing from backend session, re-confirmed rendering correctly) |
| TC-SALES-CA-003 | Add competitor with a site likely to have minimal social presence | `https://example.com` (dummy) | Discovery completes with `discovery_status: completed` but most/all platform URLs null — graceful empty icon state, not an error | ✅ PASS — confirmed in DB and UI, no icons shown, no crash |
| TC-SALES-CA-004 | Generate report for the HubSpot competitor | — | Report dialog shows fan-out progress, completes with per-platform breakdown, sparse-data platforms show "Limited data available" | ❌ FAIL — see QA_FINDINGS.md. Report itself renders correctly (all 4 platforms, full text), but the sparse-data detection regex never matches real output, so "Limited data available" never shows even for genuinely thin data (HubSpot's Instagram). |
| TC-SALES-CA-005 | View monitored competitors list | — | Both added competitors appear | ✅ PASS — 3 competitors visible (Higgsfield AI from Yuvraj's testing, HubSpot, example.com) |
| TC-SALES-CA-006 | View past reports for a competitor | — | Report history list renders | ✅ PASS — date-selector combobox in the report dialog correctly shows prior report |

## 3. Market Agent

| ID | Flow | Test Data | Expected | Status |
|---|---|---|---|---|
| TC-SALES-MA-001 | Page loads | — | Existing cards (from session 58 backend test) or empty state renders | ❌ FAIL — cards render correctly, but see QA_FINDINGS.md: "What's Changing" banner is silently absent on page load despite a valid summary existing |
| TC-SALES-MA-002 | Trigger manual refresh, wait for completion | — | All 7 analyst cards complete (6 Exa + Business Intelligence), "What's Changing" banner populates | ✅ PASS — banner correctly appears right after an active trigger, confirming the bug is specifically about initial page load, not the refresh flow |
| TC-SALES-MA-003 | Bookmark a card | — | Bookmark state toggles and persists | ✅ PASS — confirmed in DB, button label correctly changes to "Remove bookmark" |
| TC-SALES-MA-004 | Add a custom analyst | Name: "Pricing Watchdog" (dummy), prompt: "Watch for pricing changes among AI voice agent competitors" | Analyst saved; note per Yuvraj's audit — no "view existing custom analysts" list UI exists yet, verify this gap is real | ✅ PASS — clear toast confirmation "will appear on the next refresh"; confirmed no list-existing-analysts UI exists (matches Yuvraj's audit) |
| TC-SALES-MA-005 | Trigger a second refresh after adding the custom analyst | — | Custom analyst's card appears alongside the 7 built-ins | ✅ PASS — "Pricing Watchdog" card confirmed present after refresh |

## 4. Report Scheduler

| ID | Flow | Test Data | Expected | Status |
|---|---|---|---|---|
| TC-SALES-RS-001 | Page loads | — | Config form + live preview panel render | ✅ PASS — pre-existing schedule (from backend session) loaded correctly |
| TC-SALES-RS-002 | Attempt to activate with no recipients | — | "Automation Active" toggle disabled, "Add at least one recipient to activate" shown | ✅ PASS — exact expected text confirmed |
| TC-SALES-RS-003 | Add a recipient, set frequency, save | Recipient: `rahul.excel2011@gmail.com` (real, so test-send can be verified), frequency: weekly | Schedule saves, preview panel updates with real digest content | ✅ PASS — preview correctly rendered in a sandboxed iframe (safe, no script tags), all 3 module sections present with real data |
| TC-SALES-RS-004 | Activate the schedule | — | Toggle now enabled and can be turned on | ✅ PASS |
| TC-SALES-RS-005 | Send test email | — | Success toast/message shown; verify actual delivery if feasible | ✅ PASS — captured the actual API response directly: `{"sent":true,"detail":"Test email sent to rahul.excel2011@gmail.com."}`. (Toast itself was hard to catch via automation timing — not logged as a finding since the response and handler code are both correct) |
| TC-SALES-RS-006 | Update the schedule (change a module toggle) | Turn off `include_lead_researcher` | Preview updates to drop that section | ✅ PASS — confirmed Lead Researcher section disappeared from preview while Competitor Agent remained; restored afterward |

---

## Execution Log

**Run date:** 2026-07-08 · **Tool:** Canary session recording (real Playwright browser — trace/video/HAR/console captured per step)
**Canary session:** `sales-employee-e2e-qa-mrbvotec-32a925` · **Report:** `~/.canary/sessions/sales-employee-e2e-qa-mrbvotec-32a925/report.html`

**Result: 25 tests run, 22 passed, 3 failed — all 3 failures are real, reproducible bugs, logged in detail in `docs/QA_FINDINGS.md`:**

1. **TC-SALES-LR-003** — No URL format validation anywhere (frontend or backend); a real, paid Apify run starts for any garbage input. Fails gracefully in the end, but wastefully.
2. **TC-SALES-CA-004** — The "sparse/limited data" detection regex in `CompetitorReportDialog.tsx` never actually matches real backend output (verified with Node against the exact real string), so the honesty safeguard requested in the API contract has never fired.
3. **TC-SALES-MA-001** — The "What's Changing" summary banner never populates on a normal page load, only right after the user personally triggers a refresh in that same session — even though a valid summary already exists in the DB. Confirmed fixable without backend changes (cards already carry `run_id`).

No source code was modified during this QA pass, per the QA Agent Rules — findings only. Test data created during this session (competitor "example.com", lead lookups for "Arun Kumar", custom analyst "Pricing Watchdog", schedule for "Woyce Tech") was left in place as realistic ongoing test fixtures rather than cleaned up, since this is a shared team test business.
