# Support & Wish List Email

## What it does
Dashboard users submit Support requests and Wish List (feature request) submissions from
`/dashboard/support` and `/dashboard/wishlist` in ai-employees-app. Both pages render the
same component with a `mode` prop.

Previously these emails were sent via the business's own connected Gmail account (OAuth),
which meant the feature was unusable for any business that hadn't connected Gmail. This was
replaced with Resend so the feature works with zero per-business setup.

## Key files
**Backend (sam-backend)**
- `backend/app/routers/support.py` — `POST /support/submit` and `POST /support/wishlist`.
  Both endpoints: validate name/subject/message, resolve the requester's email from the
  verified JWT (`Depends(get_current_user)`, `current_user.get("email")`) rather than any
  client-supplied field, build the HTML/plain email body, and send via
  `resend_email_service.send_via_resend`.
- `backend/app/services/resend_email_service.py` — raw `httpx` POST to
  `https://api.resend.com/emails` (no `resend` SDK, mirrors the existing Gmail-service pattern
  of calling the provider's REST API directly). Reads `settings.resend_api_key`.
- `backend/app/core/config.py` — `resend_api_key` setting (`RESEND_API_KEY` in `.env`).

**Frontend (ai-employees-app)**
- `src/pages/dashboard/Support.tsx` — shared Support/Wish List page. Email is a read-only
  display of the logged-in user's email (`user.email` from `AuthContext`) — not an editable
  field, so the sender identity always matches the authenticated account.
- `src/lib/voiceAgentApi.ts` — `submitSupportRequest`, `submitWishlistRequest`,
  `SubmitWishlistRequest` (shared type for both).

## Decisions / tradeoffs
- **Recipients are fixed, not per-business**: `SUPPORT_RECIPIENT = support@aiemployeesinc.com`,
  `WISHLIST_RECIPIENT = sam@aiemployeesinc.com` (module constants in `support.py`).
- **Sender addresses**: `support-requests@aiemployeesinc.com` / `wishlist-requests@aiemployeesinc.com`
  — on the already-verified `aiemployeesinc.com` Resend domain. A dedicated
  `requests.aiemployeesinc.com` subdomain was originally requested and added in the Resend
  dashboard, but it turned out to be under a *different* Resend account than the one whose API
  key is in `backend/.env` — `GET /domains` only showed `aiemployeesinc.com` as verified there.
  Rather than chase the subdomain across accounts, we switched to distinct local-parts on the
  already-verified root domain. If the subdomain is ever verified under the right account,
  switching back is a one-line change to `SUPPORT_SENDER_ADDRESS`/`WISHLIST_SENDER_ADDRESS`.
- **Reply-To**: set to the authenticated user's email so the team can reply directly. If a user
  has no email on their JWT (edge case), `reply_to` is omitted and the sender falls back to
  `anonymous@aiemployeesinc.com` as the displayed "Email:" value in the message body.
- **Email field is not client-editable**: originally a plain text input (pre-filled but
  overridable), changed to read-only + server-resolved-from-JWT specifically so the team
  always sees the real login email of whoever submitted the request, and so it can't be spoofed
  by editing the request body directly.
- **Business Gmail connection is no longer used or displayed on this page** — that UI card was
  removed. The business's own Gmail integration is untouched and still used by other features
  (appointment confirmations, reschedule/cancellation emails, staff notifications, sales digest
  — all still in `backend/app/services/email_service.py`, unrelated to this feature).

## Known gaps / follow-ups
- `requests.aiemployeesinc.com` is verified under a different Resend account than the one in
  use — never resolved which account owns it or why. If email volume grows, worth revisiting a
  dedicated subdomain instead of the root domain.
