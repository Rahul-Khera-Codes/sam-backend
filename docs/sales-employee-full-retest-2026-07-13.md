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
| TC-BRAND-001 | Page loads, existing data shown | — | Mission, Target Niche, Unique Value Claims ("24/7 Support"), Competitors ("Acme Corp") all show pre-filled values | ⏳ |
| TC-BRAND-002 | Edit Core Brand fields | Mission: realistic rewrite; Extra Guidelines: dummy text | Textareas accept input, no crash | ⏳ |
| TC-BRAND-003 | Add + remove a Unique Value Claim tag | Add "Same-day setup", then remove it | Tag appears as removable badge, disappears on click | ⏳ |
| TC-BRAND-004 | Add + remove a Competitor tag | Add "Test Competitor Inc", then remove it | Same tag behavior as above | ⏳ |
| TC-BRAND-005 | Change colors + fonts | Primary color dummy hex `#123abc`; Heading Font → a different option | Swatch updates live; dropdown selection persists in local state | ⏳ |
| TC-BRAND-006 | Toggle Use Emojis | Flip on/off | Switch visually toggles | ⏳ |
| TC-BRAND-007 | Fill Market Insights realistically | Target Niche: something specific and different from current value (e.g. "AI receptionist + sales tools for home-service businesses") | Field accepts, no truncation | ⏳ |
| TC-BRAND-008 | Save Changes | — | Save completes (button spinner in/out); **known issue**: no visible toast (TC-TOAST-001, already logged, don't re-log) | ⏳ |
| TC-BRAND-009 | Reload persistence | Full page reload after save | All changes from 002–007 still present | ⏳ |
| TC-BRAND-010 | Edge case: clear Target Niche to empty | Save with empty Target Niche | Save succeeds (field is optional); Market Agent should fall back to `businesses.type` for its next report (see TC-MA-INTEGRATION-001) | ⏳ |

## 2. Lead Researcher

| ID | Flow | Test Data | Expected | Status |
|---|---|---|---|---|
| TC-LR-001 | Submit invalid URL | `garbage-not-a-url` (dummy) | Rejected client-side immediately, no backend call, no Apify run started | ⏳ |
| TC-LR-002 | Submit valid LinkedIn URL | A real profile URL (reuse an already-scraped one to avoid new Apify cost if possible) | Completes to full lead card with honest confidence framing | ⏳ |
| TC-LR-003 | Switch to History tab while a lookup is running (if feasible to trigger), or verify existing self-poll behavior | — | History tab shows "running" status and updates on its own within ~8s once complete — no manual reload needed (this is the session-60 fix) | ⏳ |
| TC-LR-004 | Saved Leads tab | — | Shows only bookmarked leads | ⏳ |

## 3. Competitor Agent

| ID | Flow | Test Data | Expected | Status |
|---|---|---|---|---|
| TC-CA-001 | View monitored competitors list | — | Existing competitors (HubSpot, Higgsfield AI, example.com) shown | ⏳ |
| TC-CA-002 | Generate a new report for an existing competitor | HubSpot | Completes without getting stuck "Generating..." (webhook-crash fix), shows all platforms it has real data for (platform-drop fix) | ⏳ |
| TC-CA-003 | Add a brand-new competitor | A realistic new website URL, not previously tracked | Discovery completes (or fails cleanly with a real reason — e.g. if OpenAI key issue recurs, that's TC-DISCOVERY-RETRY, see below) | ⏳ |
| TC-CA-004 | Add competitor with dummy/garbage URL | `not-a-real-site` | Rejected or fails gracefully, no crash | ⏳ |

## 4. Market Agent

| ID | Flow | Test Data | Expected | Status |
|---|---|---|---|---|
| TC-MA-001 | Page load | — | "What's Changing" banner + analyst cards show real content immediately, no blank state | ⏳ |
| TC-MA-002 | Manual refresh | — | All cards (6 Exa + Business Intelligence + any custom analysts) complete | ⏳ |
| **TC-MA-INTEGRATION-001** | **Industry-relevance fix — the actual point of this session's Branding work** | Ensure Target Niche is set to something specific (from TC-BRAND-007), trigger a refresh, then inspect the actual Exa query/report content | Report content should reference the specific niche/context set in Branding, not generic "restaurant"/"other" industry language — this is the real proof the fix works end-to-end, not just that the field saves | ⏳ |
| TC-MA-003 | Bookmark a card | — | Bookmark toggles and persists | ⏳ |

## 5. Report Scheduler

| ID | Flow | Test Data | Expected | Status |
|---|---|---|---|---|
| TC-RS-001 | Toggle a module checkbox without saving | Uncheck "Lead Researcher" | Live preview updates within ~1s to drop that section, WITHOUT clicking Save (session-60 fix) | ⏳ |
| TC-RS-002 | Re-check the box | — | Preview restores the section | ⏳ |
| TC-RS-003 | Save Automation | — | Saves correctly (no visible toast — known TC-TOAST-001, don't re-log) | ⏳ |
| TC-RS-004 | Send Test Email | — | Real email sent, confirm via network response `{"sent":true,...}` | ⏳ |

## 6. Cross-cutting

| ID | Flow | Expected | Status |
|---|---|---|---|
| TC-SALES-NAV-001 | Login + navigate to all 5 sub-pages (4 modules + Branding via Business Settings) | All load without error | ⏳ |

---

## Known Issues Not To Re-Log
- **TC-TOAST-001** — no save confirmation toast anywhere in the app (already logged, app-wide, unrelated to any single module).

## Execution Log
*(filled in after the pass)*
