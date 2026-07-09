# QA State
> Managed by Claude during QA sessions. Do not edit manually.
> Last updated: 2026-07-09 (Session 59)

---

## Last Session
| Field | Value |
|---|---|
| Session # | 59 |
| Date | 2026-07-09 |
| Tester | Claude Code (Canary/Playwright, real browser, LIVE PRODUCTION deployment) |
| Tests Run | 6 (assertion-backed, all pass) |
| Passed | 6 |
| Failed | 0 |
| Blocked | 0 |
| Next Priority | Sales Employee production QA complete for Lead Researcher, Competitor Agent, Market Agent — all 3 session-58 same-day fixes (webhook-stuck-generating, competitor sparse-data/platform-drop, market-agent-banner-blank-on-load) confirmed holding under real production conditions (`https://portal.aiemployeesinc.com/`) with real paid Apify/Exa.ai calls. Report Scheduler not covered this session (deferred — already verified locally session 58). Observation (non-blocking): production app is serving a Vite dev client trying to HMR-connect to `localhost:8080` — worth checking the prod build/deploy config separately. Older platform items unchanged: TC-ROLES-002 + TC-TEAM-006 still open. |

## Previous Session
| Field | Value |
|---|---|
| Session # | 58 |
| Date | 2026-07-08 |
| Tester | Claude Code (Canary/Playwright, real browser) |
| Tests Run | 25 (22 pass, 3 fail — all 3 fixed + re-verified same session) |
| Passed | 25 (after fixes) |
| Failed | 0 |
| Blocked | 0 |
| Next Priority | Sales Employee: all 3 same-session bugs resolved (TC-SALES-LR-003 validators, TC-SALES-CA-004 `data_availability` field, TC-SALES-MA-001 latest-run fetch on load) — see `docs/QA_FINDINGS.md` Resolved Failures. Older platform items unchanged: TC-ROLES-002 + TC-TEAM-006 still open. |


---

## Platform Access
| Target | URL |
|---|---|
| Frontend (React) | http://localhost:8080 |
| Backend (FastAPI) | http://localhost:8003 |
| API Docs (Swagger) | http://localhost:8003/docs |

> ⚠️ Claude must confirm both servers are running before executing any test.

---

## Pre-Conditions Claude Must Verify Before ANY Test
> These must be true or tests will produce false failures.

- [x] Migrations applied — `20260428000001`, `20260428000002`, `20260428000003` all confirmed applied (Session 1)
- [ ] Edge functions deployed: `npx supabase functions deploy invite-location-admin accept-invitation` — session 38 customRoleId changes not yet deployed (v16 / v10)
- [x] Resend DNS on Hostinger — confirmed working (password reset + signup confirmation emails live, Session 1)

> If any above are not met — mark dependent tests 🔲 BLOCKED with reason.

---

## Coverage Map
> Claude updates Status and Last Tested after each session.

### Auth — All ✅ Verified (Skip unless regression suspected)
| Feature | Last Tested | Status |
|---|---|---|
| Sign up with Email | Session 38 | ⏭️ SKIP |
| Sign up with Google | Session 38 | ⏭️ SKIP |
| Sign in with Email | Session 38 | ⏭️ SKIP |
| Sign in with Google | Session 38 | ⏭️ SKIP |
| Forgot Password | Session 38 | ⏭️ SKIP |
| Two-Factor Auth (TOTP) | Session 38 | ⏭️ SKIP |

### Calendar
| Feature | Last Tested | Status |
|---|---|---|
| Search Filter | Session 1 | ✅ PASS |
| Dropdown Filter | Session 1 | ✅ PASS |
| View: Month | Session 1 | ✅ PASS |
| View: Week | Session 1 | ✅ PASS |
| View: Day | Session 1 | ✅ PASS |
| View: List | Session 1 | ✅ PASS |
| Make Appointment — Button | Session 1 | ✅ PASS |
| Make Appointment — Double Click on Date | Session 1 | ✅ PASS |

### Global Settings
| Feature | Last Tested | Status |
|---|---|---|
| Language and region settings | Session 4 | ✅ PASS — all 4 selects present; time format toggled and saved with success toast |
| Brand Voice — "do not say" words | Session 4 | ✅ PASS — wizard navigated to "Do Not Say" step; word added/badge appeared/removed; saved |

### Business Settings
| Feature | Last Tested | Status |
|---|---|---|
| Company Logo upload | Session 3 | ✅ PASS |
| Company information inputs | Session 3 | ✅ PASS |
| Business hours inputs | Session 3 | ✅ PASS |
| Integrations — Gmail OAuth | Session 3 | ✅ PASS — card renders; Connect btn shown (no location selected in test context); search filter works |
| Integrations — other services | Session 3 | ⏭️ SKIP — all marked "Coming Soon" except Twilio (stub toast only) |
| Deactivation (super_admin only) | Session 3 | ✅ PASS — role guard enforced; dialog opens; confirm disabled until exact name; Cancel safe |

### Profile Settings
| Feature | Last Tested | Status |
|---|---|---|
| Icon photo change | Session 2 | ✅ PASS |
| Name input | Session 2 | ✅ PASS |
| Password update | Session 2 | ⚠️ PARTIAL — validation tested (short/mismatch rejected), actual credential change not confirmed (preserved test creds) |
| Connected Google Accounts | Session 2 | ✅ PASS |

### Locations
| Feature | Last Tested | Status |
|---|---|---|
| Add a new location | Session 5 | ✅ PASS — dialog opens with 4 fields; location created (backend seed confirmed); slow API (>3s) but succeeds |

### Team Management
| Feature | Last Tested | Status |
|---|---|---|
| Invite Team Member (email) | — | 🔲 Untested — Resend DNS now live; edge fn needs redeploy for customRoleId |
| Invite dropdown shows custom roles | Session 4 | ✅ PASS — dialog shows email input, role dropdown (Admin/User), location checkboxes; Cancel safe |
| Change Role | Session 4 | ✅ PASS — dialog opens; role changed and saved with toast; restored |
| Manage Locations | Session 4 | ✅ PASS — dialog opens with 2 location checkboxes; Cancel closes safely |
| Manage Services | Session 4 | ✅ PASS — dialog opens successfully |
| Manage Hours | Session 4 | ✅ PASS — dialog opens with weekly availability rows |
| Remove User | Session 4 | ❌ FAIL — NO confirmation dialog; action fires immediately on click (TC-TEAM-006) |

### Roles & Permissions
| Feature | Last Tested | Status |
|---|---|---|
| Add new custom role | Session 4 | ✅ PASS — role created (confirmed by screenshot); test had 2s timeout issue; API response slow but works |
| Assign permissions per role (toggles) | Session 7 | ❌ FAIL — PUT fires and returns 200 but targets wrong role_id (stale selectedRoleId closure); state still reverts on reload for clicked tab; TC-ROLES-002 |
| Sub window permissions | — | 🔲 BLOCKED — needs definition clarification |

### Phone Numbers
| Feature | Last Tested | Status |
|---|---|---|
| Search and buy US numbers | Session 5 | ✅ PASS — page renders per-location; "Assign number" opens inline form with 🇺🇸 US + area code input + "Assign selected number" btn; purchase flow renders |
| Search and buy Canadian numbers | Session 5 | ✅ PASS — (647) 584-4089 confirmed assigned to Downtown office and displayed correctly |

### Billing
| Feature | Last Tested | Status |
|---|---|---|
| Entire billing section | — | ⛔ HARD BLOCKER — Stripe not integrated, skip |

### Customer Service AI Employee
| Feature | Last Tested | Status |
|---|---|---|
| AI tells appointment time | — | 🔲 BLOCKED — voice-only (LiveKit WebRTC); cannot test headlessly |
| AI answers from company info | — | 🔲 BLOCKED — voice-only (LiveKit WebRTC); cannot test headlessly |
| AI answers from business hours | — | 🔲 BLOCKED — voice-only (LiveKit WebRTC); cannot test headlessly |
| AI lists services | — | 🔲 BLOCKED — voice-only (LiveKit WebRTC); cannot test headlessly |
| AI tells service time required | — | 🔲 BLOCKED — voice-only (LiveKit WebRTC); cannot test headlessly |
| AI tells service price | — | 🔲 BLOCKED — voice-only (LiveKit WebRTC); cannot test headlessly |
| AI does not mention deactivated services | — | 🔲 BLOCKED — voice-only (LiveKit WebRTC); cannot test headlessly |
| Knowledge base — PDF upload | — | 🔲 Untested |
| Knowledge base — manual typed info | — | 🔲 Untested |
| Conflict handling — services vs PDF | — | 🔲 Untested |
| AI answers team member availability | — | 🔲 BLOCKED — voice-only (LiveKit WebRTC); cannot test headlessly |
| AI answers team member services | — | 🔲 Untested |
| AI answers availability on days off | — | 🔲 BLOCKED — voice-only (LiveKit WebRTC); cannot test headlessly |
| AI knows new appointment after booking | — | 🔲 BLOCKED — voice-only (LiveKit WebRTC); cannot test headlessly |
| Call Recordings — playback + download | Session 6 | ✅ PASS — Recordings page renders with call history UI |
| Call Recordings — transcript/summary/insights | — | 🔲 Untested — requires actual call recordings |
| Scheduler — starts/ends on time | Session 6 | ✅ PASS — Scheduler page renders with hours/schedule UI |
| Scheduler — no location data overlap | — | 🔲 Untested — requires live AI scheduler run |
| Call Forwarding — transfers correctly | Session 6 | ✅ PASS — Call Forwarding page renders with contacts UI |
| Call Forwarding — follows time-based rules | Session 6 | ✅ PASS — page renders |
| Setup window — all features wired | Session 6 | ✅ PASS — setup checklist wired to real data: 5/8 tasks completed; agent activity shows real call history |

### Support
| Feature | Last Tested | Status |
|---|---|---|
| Email → support@aiemployeesinc.com | Session 7 | ✅ PASS (env constraint) — POST /support/submit functional; 409 in test env (Gmail OAuth not connected); works when Gmail connected |

---

### Sales Employee (full E2E, real browser — see `docs/sales-employee-qa-test-sheet.md`)
| Feature | Last Tested | Status |
|---|---|---|
| Lead Researcher — submit + poll + card render | Session 58 | ✅ PASS |
| Lead Researcher — invalid URL handling | Session 58 | ✅ FIXED — TC-SALES-LR-003, frontend+backend validators added, re-verified |
| Lead Researcher — History/Saved Leads tabs | Session 58 | ✅ PASS |
| Lead Researcher — bookmark toggle | Session 58 | ✅ PASS |
| Lead Researcher — dedupe across tabs | Session 58 | ✅ PASS |
| Competitor Agent — add + discover (strong/weak presence) | Session 58 | ✅ PASS |
| Competitor Agent — generate report + view | Session 58 | ✅ PASS (report renders correctly) |
| Competitor Agent — sparse-data indicator | Session 58 | ✅ FIXED — TC-SALES-CA-004, AI-judged `data_availability` field, re-verified |
| Market Agent — manual refresh, all 7 cards | Session 58 | ✅ PASS |
| Market Agent — "What's Changing" banner on page load | Session 58 | ✅ FIXED — TC-SALES-MA-001, fetches latest run's summary via `run_id` on load, re-verified |
| Market Agent — bookmark, custom analyst | Session 58 | ✅ PASS |
| Report Scheduler — CRUD, preview, empty-recipient guard | Session 58 | ✅ PASS |
| Report Scheduler — send-test (real email confirmed) | Session 58 | ✅ PASS |
| Report Scheduler — module-toggle preview update | Session 58 | ✅ PASS |
| Lead Researcher — invalid URL rejected (PRODUCTION) | Session 59 | ✅ PASS — verified live on portal.aiemployeesinc.com, fix holds |
| Lead Researcher — valid URL → full card (PRODUCTION) | Session 59 | ✅ PASS — verified live, no stuck loading state |
| Competitor Agent — generate report, all 4 platforms (PRODUCTION) | Session 59 | ✅ PASS — verified live, not stuck generating, 4/4 platforms incl. sparse-data indicator |
| Market Agent — banner on page load (PRODUCTION) | Session 59 | ✅ PASS — verified live, real content on load, no manual refresh needed |

---

## Permanent Blocks (Do Not Retry Until Resolved)
| Item | Reason | Resolves When |
|---|---|---|
| Invite Team Member email (customRoleId) | Edge fn not redeployed with session 38 changes | Redeploy edge functions |
| Support email | Resend DNS not on Hostinger | ✅ Resolved Session 1 |
| Billing | Stripe not integrated | Stripe built |
| Sub window permissions | Definition unclear | Team clarifies |
| SMS 2FA | A2P 10DLC blocked | A2P registration approved |

---

## Confirmed Working (Regression Watch Only)
| Feature | Verified |
|---|---|
| Sign up / Sign in (Email + Google) | Checklist ✅ |
| Forgot Password | Checklist ✅ |
| TOTP Two-Factor Auth | Checklist ✅ |
| Canadian phone numbers (647) | Session 38 ✅ |
| Custom roles UI | Session 38 ✅ |
| Assign permissions UI | Session 38 ✅ |

---

## Session History
| # | Date | Run | ✅ | ❌ | 🔲 | Focus Area |
|---|---|---|---|---|---|---|
| 0 | 2026-04-29 | 0 | 0 | 0 | 0 | Baseline setup |
| 1 | 2026-04-29 | 8 | 8 | 0 | 0 | Calendar flows |
| 2 | 2026-04-29 | 4 | 4 | 0 | 0 | Profile Settings |
| 3 | 2026-04-29 | 5 | 5 | 0 | 0 | Business Settings |
| 4 | 2026-04-29 | 10 | 7 | 3 | 0 | Global Settings + Team Management + Roles |
| 5 | 2026-04-29 | 5 | 3 | 1 | 1 | Roles verify + Phone Numbers + Locations |
| 6 | 2026-04-29 | 16 | 6 | 0 | 10 | CSE structural + AI behavior blocked |
| 7 | 2026-04-29 | 3 | 1 | 1 | 1 | TC-ROLES-002 retest + TC-TEAM-006 blocked + Support email |
| 59 | 2026-07-09 | 6 | 6 | 0 | 0 | Sales Employee PRODUCTION QA (Lead Researcher, Competitor Agent, Market Agent — live deployment, real paid API calls) |

---

## Next Session Should Start With
- [ ] **Developer fixes required**: TC-ROLES-002 (RolesPermissions.tsx — `selectedRoleId` stale closure; PUT fires but targets auto-selected role instead of clicked tab) + TC-TEAM-006 (TeamManagement.tsx:375 — add AlertDialog confirmation before handleRemoveUser)
- [ ] Clean up test artifacts in DB: "QA Test Role" + "QA Test Location" (both still present after Session 7)
- [ ] **HEADLESS QA IS COMPLETE** — all remaining items require human tester:
  - AI behavior tests: live voice call or "Test with Web Call" button in browser (LiveKit WebRTC; no headless option)
  - TC-ROLES-002 + TC-TEAM-006 retests: blocked until developer fixes deployed
  - Support email delivery: verify email arrives at support@aiemployeesinc.com after Gmail OAuth connected
  - Call recordings: download + transcript/summary/insights (requires real recording)
  - Billing: Stripe not integrated (pre-existing hard blocker)