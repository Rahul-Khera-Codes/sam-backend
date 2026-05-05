---
name: client_launch_checklist
description: Client's pre-launch QA checklist with status — what's done, what needs testing, and hard blockers. Updated QA session 7 (2026-04-29).
type: project
originSessionId: 29becce9-ad8f-4b26-8540-59f05b3f8002
---
Last updated: 2026-05-01 (session 40)

## Hard Blockers (must fix before launch)
- **Resend DNS** — domain verification failed; email verification broken; fix Hostinger DNS records
- **Merge + deploy** — `feature/strip-integration` not yet merged to main; billing URLs not updated on server

## Legend
- ✅ Done and verified
- ⚠️ Built — needs live/manual test (voice or real env)
- ❌ Not built or broken bug

---

## General
- ✅ Sign up with Email
- ✅ Sign up with Google
- ✅ Sign in with Email
- ✅ Sign in with Google
- ✅ Forgot Password

## Calendar (QA Session 1 ✅)
- ✅ Search Filter
- ✅ Dropdown Filter
- ✅ Views (Month, Week, Day, List)
- ✅ Make Appointment — Button
- ✅ Make Appointment — Double Click on Date

## Support
- ⚠️ Email goes to support@aiemployeesinc.com — form works; delivery needs Gmail OAuth connected

## Wishlist
- ⚠️ Email goes to sam@aiemployeesinc.com — Resend DNS now live; needs live test

## Global Settings (QA Session 4 ✅)
- ✅ Language and region settings
- ✅ Brand Voice — "do not say" words

## Business Settings (QA Session 3 ✅)
- ✅ Company Logo uploads
- ✅ Company information inputs
- ✅ Business hours inputs
- ✅ Integrations — connect to services (Gmail card renders; OAuth redirect not testable headlessly)
- ✅ Deactivation

## Profile Settings (QA Session 2 ✅)
- ✅ Icon photo changes
- ✅ Name input
- ✅ Password updates (validation confirmed; actual update not tested to preserve creds)
- ✅ Two-Factor Authentication (TOTP; SMS 2FA blocked on A2P 10DLC)
- ✅ Connected Google Accounts

## Locations (QA Session 5 ✅)
- ✅ Add a new location (API slow >2s but functional)

## Team Management (QA Session 4)
- ⚠️ Invite Team Member — invite dialog + role dropdown verified; edge fn redeploy needed for customRoleId
- ✅ Change Role works
- ✅ Manage Locations works
- ✅ Manage Services works
- ✅ Manage Hours works
- ✅ Remove User — fixed session 40, AlertDialog confirmation (TC-TEAM-006)

## Roles & Permissions (QA Session 4 + Session 40 fix)
- ✅ Add new custom roles (migrations applied; API slow but succeeds)
- ✅ Assign permissions — fixed session 40 (TC-ROLES-002)
- ⚠️ Sub window permissions — needs clarification on meaning

## Billing
- ✅ Stripe integration complete — Checkout (3 plans), Customer Portal, webhooks, usage bar + period dates (session 39)
- ✅ Migration `20260430000001_businesses_stripe.sql` applied

## Phone Numbers (QA Session 5 ✅)
- ✅ Search and buy US numbers
- ✅ Search and buy Canadian numbers — (647) 584-4089 confirmed assigned to Downtown office

## Customer Service Employee (QA Sessions 6-7)
- ⚠️ AI tells appointment time — requires live voice test
- ⚠️ AI answers from company info — requires live voice test
- ⚠️ AI answers from business hours — requires live voice test
- ⚠️ AI lists services — requires live voice test
- ⚠️ AI tells service time required — requires live voice test
- ⚠️ AI tells service price — requires live voice test
- ⚠️ AI does not mention deactivated services — requires live voice test
- ⚠️ AI answers from knowledge base PDF — requires live voice test
- ⚠️ Conflict handling services vs PDF — requires live voice test
- ⚠️ AI answers from manual knowledge base text — requires live voice test
- ⚠️ AI answers team member availability — requires live voice test
- ⚠️ AI answers team member services — requires live voice test
- ⚠️ AI handles days off — requires live voice test
- ⚠️ AI knows about new appointment after booking — requires live voice test
- ⚠️ Call Recordings — playback + download (page renders; requires actual recording)
- ⚠️ Call Recordings — transcript, summary, insights (requires actual call recording)
- ⚠️ Scheduler auto-start/stop (page renders; requires live AI run)
- ⚠️ Scheduler no location overlap (requires live AI run across locations)
- ⚠️ Call Forwarding — calls get transferred (page renders; requires live call)
- ⚠️ Call Forwarding — follows time rules (page renders; requires live call)
- ✅ All features in setup window (checklist wired to real data; 5/8 tasks completed)

## Pre-Conditions Status
- ✅ Migrations 20260428000001–000003 applied (QA Session 1)
- ✅ Edge functions deployed (QA Session 1)
- ✅ Resend DNS live on Hostinger (QA Session 1)

## **Why:** Client shared this checklist for pre-launch QA sign-off.
## **How to apply:** Fix TC-ROLES-002 + TC-TEAM-006 first. Apply Stripe migration. AI voice tests need "Test with Web Call" button or real phone — cannot be automated headlessly.
