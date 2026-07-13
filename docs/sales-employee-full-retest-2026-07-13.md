# Sales Employee — Full Real-User Re-Test Sheet (2026-07-13)

> Full end-to-end re-test of all 4 Sales Employee modules plus the new Business
> Branding feature, as real user-facing flows — real browser (Canary/Playwright),
> real backend, real external API calls where applicable, realistic + dummy data.
> No curl shortcuts. Covers everything changed since the last full pass
> (session 58/59): Lead Researcher History self-polling, Competitor Agent
> webhook-crash + platform-drop fixes, Market Agent industry-context wiring,
> Report Scheduler live-preview fix, and the new Business Branding tab.
>
> **Rule:** Claude never modifies source code during this pass. Findings only —
> logged to `docs/QA_FINDINGS.md` in TC-[id] format.

---

## Environment

| Target | URL |
|---|---|
| Frontend | http://localhost:8080 (Docker, `sam-frontend`) |
| Backend | http://localhost:8003 (Docker) |
| Test login | rahul.excel2011@gmail.com |
| Test business | Woyce Tech / "Eifel Tower 8" (`f46ce260-45da-4db8-9bc1-b0af01ec3acc`) |
| Branch under test | `feature/business-branding` (both repos) |

## Status Legend
| Symbol | Meaning |
|---|---|
| ✅ PASS | Test ran, all assertions passed |
| ❌ FAIL | Test ran, assertion failed — logged to QA_FINDINGS.md |
| 🔲 BLOCKED | Cannot run — missing dependency |
| ⏳ PENDING | Not yet executed |

---

## 1. Business Branding (new feature)

| ID | Flow | Test Data | Expected | Status |
|---|---|---|---|---|
| TC-BRAND-001 | Page loads, existing data shown | — | Mission, Target Niche, Unique Value Claims ("24/7 Support"), Competitors ("Acme Corp") all show pre-filled values | ✅ PASS |
| TC-BRAND-002 | Edit Core Brand fields | Mission: realistic rewrite; Extra Guidelines: dummy text | Textareas accept input, no crash | ✅ PASS |
| TC-BRAND-003 | Add + remove a Unique Value Claim tag | Add "Same-day setup", then remove it | Tag appears as removable badge, disappears on click | ✅ PASS |
| TC-BRAND-004 | Add + remove a Competitor tag | Add "Test Competitor Inc", then remove it | Same tag behavior as above | ✅ PASS |
| TC-BRAND-005 | Change colors + fonts | Primary color dummy hex `#123abc`; Heading Font → a different option | Swatch updates live; dropdown selection persists in local state | ✅ PASS — swatch updated live, font changed Poppins→Montserrat |
| TC-BRAND-006 | Toggle Use Emojis | Flip on/off | Switch visually toggles | ✅ PASS |
| TC-BRAND-007 | Fill Market Insights realistically | Target Niche: something specific and different from current value (e.g. "AI receptionist + sales tools for home-service businesses") | Field accepts, no truncation | ✅ PASS |
| TC-BRAND-008 | Save Changes | — | Save completes (button spinner in/out); **known issue**: no visible toast (TC-TOAST-001, already logged, don't re-log) | ✅ PASS — save confirmed via spinner + persisted data, no toast (expected) |
| TC-BRAND-009 | Reload persistence | Full page reload after save | All changes from 002–007 still present | ✅ PASS — every field confirmed correct after hard reload |
| TC-BRAND-010 | Edge case: clear Target Niche to empty | Save with empty Target Niche | Save succeeds (field is optional); Market Agent should fall back to `businesses.type` for its next report (see TC-MA-INTEGRATION-001) | ✅ PASS — field genuinely cleared, confirmed via reload, other fields unaffected |

## 2. Lead Researcher

| ID | Flow | Test Data | Expected | Status |
|---|---|---|---|---|
| TC-LR-001 | Submit invalid URL | `garbage-not-a-url` (dummy) | Rejected client-side immediately, no backend call, no Apify run started | ✅ PASS — zero network requests fired, confirmed via network listener |
| TC-LR-002 | Submit valid LinkedIn URL | A real profile URL (reuse an already-scraped one to avoid new Apify cost if possible) | Completes to full lead card with honest confidence framing | ✅ PASS — full card rendered (Arun Kumar), honest "Unverified guess (catch_all)" framing intact |
| TC-LR-003 | Switch to History tab while a lookup is running (if feasible to trigger), or verify existing self-poll behavior | — | History tab shows "running" status and updates on its own within ~8s once complete — no manual reload needed (this is the session-60 fix) | ✅ PASS — badge flipped running→completed with zero manual interaction |
| TC-LR-004 | Saved Leads tab | — | Shows only bookmarked leads | ✅ PASS — 13+ History entries vs. 2 in Saved Leads, confirms it's a filtered view |

## 3. Competitor Agent

| ID | Flow | Test Data | Expected | Status |
|---|---|---|---|---|
| TC-CA-001 | View monitored competitors list | — | Existing competitors (HubSpot, Higgsfield AI, example.com) shown | ✅ PASS |
| TC-CA-002 | Generate a new report for an existing competitor | HubSpot | Completes without getting stuck "Generating..." (webhook-crash fix), shows all platforms it has real data for (platform-drop fix) | ✅ PASS — all 4 platforms shown, none dropped. Note: fired twice by accident (tooling ambiguity), real Apify cost incurred 2x — not a bug, flagged for awareness |
| TC-CA-003 | Add a brand-new competitor | `salesforce.com` (real site) | Discovery completes (or fails cleanly with a real reason — e.g. if OpenAI key issue recurs, that's TC-DISCOVERY-RETRY, see below) | ✅ PASS (locally) — OpenAI calls clean 200s, no auth errors. New minor finding: 0 social links discovered for Salesforce despite the site having them — likely a Jina AI Reader extraction gap, not the auth bug. See TC-CA-SOCIAL-GAP below |
| TC-CA-004 | Add competitor with dummy/garbage URL | `not-a-real-site` | Rejected or fails gracefully, no crash | ✅ PASS — fails gracefully as "Discovery failed" row, no crash. Minor UX note: no client-side validation, so junk entries persist in the list |

## 4. Market Agent

| ID | Flow | Test Data | Expected | Status |
|---|---|---|---|---|
| TC-MA-001 | Page load | — | "What's Changing" banner + analyst cards show real content immediately, no blank state | ✅ PASS |
| TC-MA-002 | Manual refresh | — | All cards (6 Exa + Business Intelligence + any custom analysts) complete | ✅ PASS — all 8 cards completed with coherent new content, refresh triggered exactly once |
| **TC-MA-INTEGRATION-001** | **Industry-relevance fix — the actual point of this session's Branding work** | Ensure Target Niche is set to something specific (from TC-BRAND-007), trigger a refresh, then inspect the actual Exa query/report content | Report content should reference the specific niche/context set in Branding, not generic "restaurant"/"other" industry language — this is the real proof the fix works end-to-end, not just that the field saves | ✅ **PASS — strong evidence.** Post-refresh cards explicitly reference "home services," AI receptionist/scheduling tools, and name real competitors (ServiceTitan, Avoca, Goodcall, Rosie) with trade-press citations (ServiceMag, ACHR News, direct HVAC references). Zero restaurant/generic-industry language. Backend logs confirm `GET .../business_branding?select=target_niche` fired before the 7 Exa calls — direct technical proof, not coincidence. |
| TC-MA-003 | Bookmark a card | — | Bookmark toggles and persists | ✅ PASS — confirmed via reload |

## 5. Report Scheduler

| ID | Flow | Test Data | Expected | Status |
|---|---|---|---|---|
| TC-RS-001 | Toggle a module checkbox without saving | Uncheck "Lead Researcher" | Live preview updates within ~1s to drop that section, WITHOUT clicking Save (session-60 fix) | ✅ PASS |
| TC-RS-002 | Re-check the box | — | Preview restores the section | ✅ PASS |
| TC-RS-003 | Save Automation | — | Saves correctly (no visible toast — known TC-TOAST-001, don't re-log) | ✅ PASS — confirmed via direct API capture (200, fresh updated_at) |
| TC-RS-004 | Send Test Email | — | Real email sent, confirm via network response `{"sent":true,...}` | ❌ **FAIL (regression)** — response was `{"sent":false,"detail":"Gmail is not connected for this business, or the send failed."}`. Root cause: Gmail OAuth refresh token expired (`token_expiry: 2026-07-09`, 4 days stale) — Google rejected the refresh with 401. Environment/OAuth issue, NOT a Report Scheduler code defect (worked fine in session 60). See TC-RS-004-GMAIL-TOKEN in QA_FINDINGS.md. |

## 6. Cross-cutting

| ID | Flow | Expected | Status |
|---|---|---|---|
| TC-SALES-NAV-001 | Login + navigate to all 5 sub-pages (4 modules + Branding via Business Settings) | All load without error | ✅ PASS — confirmed across all 5 agent sessions, no navigation errors |

---

## Known Issues Not To Re-Log
- **TC-TOAST-001** — no save confirmation toast anywhere in the app (already logged, app-wide, unrelated to any single module).

## Execution Log

**Run date:** 2026-07-13 · **Tool:** 5 parallel Canary session recordings (real Playwright browser), one per module/area.

**Result: 26 tests run, 25 passed, 1 failed.**

The 1 failure (TC-RS-004) is a **regression caused by an expired Gmail OAuth token in this environment**, not a code defect — Report Scheduler's send-test worked correctly in session 60 on this same business. Needs a Gmail reconnect, not a code fix.

**The headline result is TC-MA-INTEGRATION-001**: direct, quoted evidence that Market Agent's reports now genuinely reflect the business's Branding data (home-service/HVAC/plumbing context, real named competitors, trade-press citations) instead of generic or wrong-industry content — this is the actual proof that the whole Business Branding feature accomplishes what Sam asked for, not just that the UI saves data.

**3 additional minor findings, not blocking:**
1. A React `validateDOMNesting` console warning in `LeadHistoryTab.tsx` (button nested in button) — cosmetic, not functional.
2. Competitor Agent's "Generate New Report" fired twice due to a UI-timing ambiguity during testing, incurring real Apify cost twice — a testing artifact, not reproduced as a genuine double-submit bug, but worth a glance at button-disable timing.
3. Competitor discovery returned zero social links for a real, well-known site (Salesforce) — likely a scraping/extraction quality gap (Jina AI Reader missing footer social links on some sites), separate from the earlier OpenAI-key bug.

No source code was modified during this pass, per the QA Agent Rules — findings only.
