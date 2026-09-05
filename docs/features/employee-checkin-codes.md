# Employee Check-in / Payment Codes (AIE-28, AIE-58)

## What it does
Businesses that share one front-desk login across staff had no way to tell *which employee*
actually checked in a customer or collected a payment — useful for resolving payment
disputes/errors. Each team member can now be given an optional 4-digit code. An Admin can
independently require that code before (a) marking an appointment "Checked In"/"No Show"/
"Cancelled" and/or (b) recording a payment entry. The resolved employee identity is stored
alongside the action.

**AIE-58 (2026-09-05)** extended (b) to also gate *deleting* a payment/refund entry, and to keep
a permanent record of who deleted it — see "Deleting a payment/refund entry" below.

**Attribution is captured either way, code-required or not** (as of 2026-08-27): if the business
hasn't turned the code requirement on, the action is attributed to whoever is actually logged in
and made the change, rather than left blank. The code path exists specifically for the
shared-login case, where the authenticated session isn't necessarily the person standing at the
desk — it's not a prerequisite for attribution to be captured at all. See "Attribution fallback"
under Decisions/tradeoffs.

## Data model
- `user_roles.check_in_code` — nullable `TEXT`, `CHECK (check_in_code ~ '^[0-9]{4}$')`. Unique
  per business via a partial index `(business_id, check_in_code) WHERE check_in_code IS NOT NULL`
  (not globally unique — two different businesses may reuse the same 4 digits).
- `businesses.require_checkin_employee_code` / `businesses.require_payment_employee_code` —
  booleans, default `false`. Two independent toggles, not one combined switch.
- `appointments.checked_in_by_user_id` + `checked_in_at` — set only when the check-in flag is on
  and a valid code was entered; untouched otherwise.
- `appointments.no_show_by_user_id` + `no_show_at`, `appointments.cancelled_by_user_id` +
  `cancelled_at` — same pattern, one dedicated triplet per status rather than a single reused set
  of columns, so an appointment that transitions more than once (e.g. `checked_in` then later
  `cancelled`) keeps both records intact instead of one overwriting the other.
- `appointment_payment_entries.collected_by_user_id` — set only when the payment flag is on and
  a valid code was entered. Kept separate from the pre-existing `created_by` (who was logged in)
  since the two can differ on a shared login.
- `appointments.checked_in_by_code` / `no_show_by_code` / `cancelled_by_code` /
  `appointment_payment_entries.collected_by_code` — an **immutable snapshot** of the exact 4-digit
  code typed at that moment, stored alongside (not instead of) the `_user_id` columns above. Unlike
  `user_roles.check_in_code`, these never change after the fact — if an Admin later resets the
  employee's code, historical records still show whatever was actually entered at the time, while
  the `_user_id` column still correctly resolves to the same employee regardless. Same
  `^[0-9]{4}$` format check as the live code column.
- `appointment_payment_entry_deletions` (added AIE-58) — a standalone insert-only audit table, not
  a column triplet on `appointment_payment_entries`, since deleting an entry is a **hard delete**
  (the row itself is gone, so `deleted_by_*` can't live on it). Snapshots the deleted entry's own
  data (`payment_entry_id`, `appointment_payment_id`, `business_id`, `entry_type`, `payment_type`,
  `amount`, `note`, `paid_at`, `collected_by_user_id`/`collected_by_code`) plus
  `deleted_by_user_id` + `deleted_by_code` (same immutable-snapshot format as the other `_code`
  columns) + `deleted_at`. RLS: `FOR SELECT` only, scoped by `business_id` — no write policy,
  since only the backend's service-role client ever inserts into it.
- Migrations: `ai-employees-app/supabase/migrations/20260824060000_employee_checkin_codes.sql`
  (base feature), `20260824101200_employee_checkin_code_snapshot.sql` (the `_code` snapshot
  columns), `20260827120000_appointment_status_attribution.sql` (the `no_show_by_*` /
  `cancelled_by_*` triplets, added 2026-08-27 per an AIE-28 client follow-up asking the UI to show
  who marked an appointment No Show/Cancelled and when, not just Checked In), and
  `20260905090000_payment_entry_deletion_audit.sql` (the `appointment_payment_entry_deletions`
  table, AIE-58).
- **Gap:** the AI voice agent can also cancel an appointment directly
  (`agent/executive_agent.py`, `agent/agent.py`) via a code path that bypasses this endpoint
  entirely (by design — there's no human employee to attribute on an agent-driven action). Those
  cancellations leave `cancelled_by_user_id`/`cancelled_at` null, so the UI correctly shows just
  "Cancelled" with no attribution line for them.

**Rollout safety:** both flags default off, so no existing business is affected. No RLS changes
were needed — the code is only ever written by the backend via the service-role client. It's
write-only for everyone except its owner: an Admin sees it once at set time and never again, but
the employee it belongs to can always view their own current code (see "Employee self-view"
below) — otherwise there'd be no way for them to actually learn it.

## Key files
**Backend (sam-backend)**
- `backend/app/routers/appointments.py` — `_resolve_employee_code()` / `_get_business_code_flags()`
  helpers; `update_appointment_status` (gates on `require_checkin_employee_code`, for the
  `checked_in`, `no_show`, and `cancelled` transitions — attribution now written for all three,
  each to its own column triplet), `add_payment_entry`/`refund_appointment_payment` (gate on
  `require_payment_employee_code`), and `delete_payment_entry` (AIE-58, same flag) all accept an
  optional `employee_code` and 422 with "Employee code required"/"Invalid employee code" when the
  flag is on and the code is missing/wrong. `delete_payment_entry` always attributes the delete
  (code-resolved user when the flag is on, otherwise the authenticated `user_id`, same fallback
  `update_appointment_status` uses — see Decisions/tradeoffs) by inserting a snapshot row into
  `appointment_payment_entry_deletions` before returning, built from the row Postgrest's
  `.delete()` itself returns (no extra SELECT needed to capture the entry before it's gone).
- `backend/app/routers/roles.py` — admin-only endpoints (reuses the existing `_require_admin`
  helper): `GET /roles/check-in-codes` (per-member `has_code` status, never the code itself),
  `PUT /roles/users/{id}/check-in-code` (set/reset one member's code, custom or auto-generated,
  returned once in the response), `POST /roles/check-in-codes/bulk-generate` (assigns a code to
  every member currently missing one — the backfill path for businesses with zero codes set).
  Also `GET /roles/my-check-in-code` — no admin check, scoped to the caller's own `user_id` from
  the JWT (not a path param), so an employee can always look up their own current code.
- `backend/app/schemas/appointments.py`, `backend/app/schemas/roles.py` — request/response models.

**Frontend (ai-employees-app)**
- `src/components/team/EmployeeCodeDialog.tsx` — generic 4-digit PIN entry modal used to confirm
  an action; used from both call sites below.
- `src/components/team/SetEmployeeCodeDialog.tsx` — admin-facing "set/reset a member's code"
  dialog (custom digits or auto-generate), used from Team Management.
- `src/pages/dashboard/Calendar.tsx` — `handleStatusChangeClick`/`performStatusUpdate`: opens the
  PIN dialog (via `codeGateAction` state, which carries both the appointment id and target status)
  before marking an appointment Checked In, No Show, or Cancelled when
  `business.require_checkin_employee_code` is true. The `EmployeeCodeDialog` title/description are
  worded per target status.
- `src/components/appointments/PaymentDetailsDialog.tsx` — `submitEntry`/`submitRefund`: same gate
  on "Add Payment"/"Record Refund" for `business.require_payment_employee_code`.
  `handleDeleteEntryClick`/`handleDeleteEntry` (AIE-58): same gate on the trash-icon delete button
  for both payment and refund entries (one endpoint/button covers both — refunds are just
  `entry_type = 'refund'` rows in the same ledger), via a `deleteGateEntryId` state carrying which
  entry is pending deletion, mirroring Calendar's `codeGateAction` pattern.
- `src/pages/dashboard/TeamManagement.tsx` — per-member "Set/Reset Employee Code" menu item, a
  "No employee code set" indicator, and a page-level "Generate codes for N missing" bulk action.
  Admin/super_admin only (`isAdmin`).
- `src/pages/dashboard/BusinessSettings.tsx` (Company Info tab) — the two toggles. Before turning
  either on, it calls `getCheckInCodeStatus` and blocks the save with a toast if any member still
  lacks a code, pointing the admin at Team Management's bulk-generate action.
- `src/components/account/EmployeeCodeBadge.tsx` — a compact pill rendered at the top of
  `AccountSettings.tsx` ("Profile Settings"), right next to the role badge beside the user's
  avatar/name. Shows the caller's own code (masked behind an eye-toggle) via `getMyCheckInCode`,
  or "No employee code — ask an Admin" if none is set yet. This is the answer to "how does the
  employee find out their code" — the Admin-facing dialogs only ever show it once at set time.
- `src/lib/voiceAgentApi.ts` — `getCheckInCodeStatus`, `setCheckInCode`, `bulkGenerateCheckInCodes`,
  `getMyCheckInCode`, and `employee_code` threaded through `updateAppointmentStatus`/`addPaymentEntryApi`.

## Viewing who checked in / marked no-show / cancelled / collected a payment
The attribution captured above (`checked_in_by_user_id`, `collected_by_user_id`, etc.) was
originally write-only from the UI's perspective — stored on the record but not rendered anywhere.
This is now surfaced directly on the two existing screens rather than a separate report page:
- `src/pages/dashboard/Calendar.tsx` — the read-only "Appointment Details" dialog (`detailsOpen`)
  shows an **Appointment Status** field (via `APPOINTMENT_STATUS_LABELS`: Confirmed/Checked
  In/No Show/Cancelled) alongside Client/Service/Assigned To/etc. Directly beneath it, a
  conditional attribution line picks the column triplet matching the current status
  (`checked_in_by_user_id`/`_at`, `no_show_by_user_id`/`_at`, or `cancelled_by_user_id`/`_at`) and
  renders `"Jane · Aug 25, 2026 at 3:42 PM"` via the existing `getMemberName(userId)` helper —
  omitted entirely when the current status has no attribution (toggle was off at the time, the
  appointment predates this feature, or it's an agent-driven cancellation, see the Data model
  gap above). This field was originally called **Checked In By** and only ever considered
  `checked_in_by_*` regardless of status — renamed and widened 2026-08-27 per an AIE-28 client
  follow-up. **Note:** it also originally displayed the raw `checked_in_by_code` snapshot instead
  of a timestamp (`"Jane · Code 4821"`) — QA flagged that as a plaintext leak of the employee's
  secret code (AIE-28, comment 2026-08-25), fixed to show the check-in timestamp instead.
  `checked_in_by_code`/`no_show_by_code`/`cancelled_by_code` are still captured and stored for the
  audit trail (see below) — they're just never rendered in this dialog.
- `src/components/appointments/PaymentDetailsDialog.tsx` — each payment entry shows a
  **Collected by** line under its timestamp, same "—" fallback when unset and same
  `"Jane · Code 4821"` format via `collected_by_code`. The dialog takes a new optional
  `getMemberName` prop (passed in from `Calendar.tsx`, which already has team member data via
  `useTeamManagement`) rather than fetching its own copy of the team list.
- No new role gate — this is visible to anyone who can already open these dialogs (matches every
  other field on them; there's no existing precedent for hiding parts of an appointment/payment
  from non-admin staff who have page access).
- `Appointment` (`useAppointments.ts`) and `AppointmentForm` (`Calendar.tsx`) both gained
  `checked_in_by_user_id`/`checked_in_at`/`no_show_by_user_id`/`no_show_at`/
  `cancelled_by_user_id`/`cancelled_at` (snake/camel respectively) to carry the values from the
  already-`select("*")` Supabase query through to the UI.

## Uniqueness, generation, and code reuse
- **Generation** (`roles.py::_generate_unused_check_in_code`): a uniform random 4-digit value
  (`random.randint(0, 9999)`, zero-padded), checked against an in-memory set of the business's
  currently-assigned codes before being offered as a candidate.
- **Guarantee**: uniqueness is enforced per business by a partial unique DB index —
  `(business_id, check_in_code) WHERE check_in_code IS NOT NULL` — not by the in-memory check
  alone, which is just an optimization to avoid pointless write attempts. Two different
  businesses can freely reuse the same 4 digits (the index key includes `business_id`).
- **Race-condition hardening** (`_write_check_in_code` / `_assign_unique_code`): auto-generated
  codes (single "Set Employee Code" with no custom value, and every code in bulk-generate) are
  written through a retry loop that catches the DB's `23505` unique-violation error (via
  `postgrest.exceptions.APIError`) if a concurrent request wins the same code first, and
  transparently retries with a fresh candidate (up to 5 attempts) rather than surfacing a raw
  500. An admin-typed *custom* code is never silently substituted on a conflict — that case
  surfaces as a clean 409 instead, since retrying would hand out a code the admin didn't ask for.
- **Freeing on removal**: no special-case code exists for this — "Remove User" in Team Management
  (`useTeamManagement.ts::removeUserFromBusiness`) hard-deletes the employee's `user_roles` row,
  and `check_in_code` lives on that row, so the code disappears from the unique index and becomes
  assignable again the moment they're removed. `_existing_check_in_codes()` only ever reflects
  currently-existing rows.
- **Immediate reuse is intentional and safe**: `appointments.checked_in_by_user_id` and
  `appointment_payment_entries.collected_by_user_id` store the resolved `user_id`, not the code
  itself, at the moment the action happens — so historical records stay correctly attributed to
  the original employee even after their old code is reissued to someone new. No cooldown.

## Decisions / tradeoffs
- **Attribution fallback to the logged-in user when no code is required** (2026-08-27). Originally
  (through 2026-08-26) `checked_in_by_user_id`/`no_show_by_user_id`/`cancelled_by_user_id` were
  populated *only* when `require_checkin_employee_code` was on and a code was resolved — with the
  flag off, the columns stayed null and the "Appointment Status" attribution line never appeared
  at all. Reversed after a client walkthrough (AIE-28) surfaced that most businesses don't turn
  the toggle on, so the field the client asked for was effectively invisible by default. Now
  `update_appointment_status` (`backend/app/routers/appointments.py`) always populates the
  triplet for `checked_in`/`no_show`/`cancelled`: the code-resolved employee id when the flag is
  on, otherwise the authenticated `user_id` from the request's own session — `*_by_code` stays
  null in the fallback case, since no code was actually entered. This is not a security-relevant
  change: the caller was already authenticated and authorized (`verify_business_access`) either
  way, this only changes what gets *recorded* about who they were.
- **Two independent toggles, not one** — a business might want accountability on payments but
  not check-in, or vice versa.
- **Admin-assigned only, no self-service** — matches the existing `_require_admin` pattern already
  used for role/permission management; also prevents an employee resetting their own code to
  dodge accountability.
- **Codes are write-only for everyone except their owner** — once set, the plaintext value is
  returned exactly once to the Admin who set it (in the set/bulk-generate response), and is never
  retrievable by another admin or via the general Team Management member list. The owner is the
  one exception — they can always view their own current code from Account Settings — otherwise
  the Admin would be the sole channel for ever communicating the code, with no recovery path if
  they forgot to pass it on. This still sidesteps RLS changes on `user_roles`: the self-view
  endpoint scopes strictly to the caller's own `user_id` from the JWT, never a path param.
- **No hard rollout risk** — both flags default off; the UI actively blocks turning a flag on
  while any member is missing a code, and bulk-generate exists specifically to clear that
  blocker in one action for businesses (the common case today) where no one has a code yet.
- **Code required for `checked_in`, `no_show`, and `cancelled`** (not `confirmed`). Originally
  scoped to `checked_in` only, matching the ticket's literal wording — widened 2026-08-26 after a
  QA comment on AIE-28 asked for the same requirement on No Show/Cancelled.
- **Deletion audit has no UI surface yet (AIE-58, 2026-09-05).** `appointment_payment_entry_deletions`
  rows are captured on every delete but nothing renders them in the app today — same starting point
  as `no_show_by_*`/`cancelled_by_*` before their 2026-08-27 follow-up added the Appointment Details
  attribution line. Deliberately out of scope for AIE-58 (the ticket asked to gate the delete and
  keep a record, not to add a report view); can be surfaced later the same way if asked, e.g. from
  a query against this table by `business_id`.
- **Attribution now recorded for all three gated transitions, not just `checked_in`.** Initially
  (2026-08-26) No Show/Cancelled were gate-only — code validated but nothing recorded — as a
  deliberate scope decision to avoid a migration. Reversed 2026-08-27 after the client asked
  (AIE-28) for the Appointment Details dialog to actually show who marked something No
  Show/Cancelled and when, not just gate the action. Added `no_show_by_*`/`cancelled_by_*` column
  triplets rather than reusing a single generic set, so a later transition never overwrites an
  earlier one's attribution.
