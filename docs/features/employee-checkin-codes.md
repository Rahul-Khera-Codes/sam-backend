# Employee Check-in / Payment Codes (AIE-28)

## What it does
Businesses that share one front-desk login across staff had no way to tell *which employee*
actually checked in a customer or collected a payment — useful for resolving payment
disputes/errors. Each team member can now be given an optional 4-digit code. An Admin can
independently require that code before (a) marking an appointment "Checked In" and/or (b)
recording a payment entry. The resolved employee identity is stored alongside the action.

## Data model
- `user_roles.check_in_code` — nullable `TEXT`, `CHECK (check_in_code ~ '^[0-9]{4}$')`. Unique
  per business via a partial index `(business_id, check_in_code) WHERE check_in_code IS NOT NULL`
  (not globally unique — two different businesses may reuse the same 4 digits).
- `businesses.require_checkin_employee_code` / `businesses.require_payment_employee_code` —
  booleans, default `false`. Two independent toggles, not one combined switch.
- `appointments.checked_in_by_user_id` + `checked_in_at` — set only when the check-in flag is on
  and a valid code was entered; untouched otherwise.
- `appointment_payment_entries.collected_by_user_id` — set only when the payment flag is on and
  a valid code was entered. Kept separate from the pre-existing `created_by` (who was logged in)
  since the two can differ on a shared login.
- `appointments.checked_in_by_code` / `appointment_payment_entries.collected_by_code` — an
  **immutable snapshot** of the exact 4-digit code typed at that moment, stored alongside (not
  instead of) the `_user_id` columns above. Unlike `user_roles.check_in_code`, these never change
  after the fact — if an Admin later resets the employee's code, historical records still show
  whatever was actually entered at the time, while the `_user_id` column still correctly resolves
  to the same employee regardless. Same `^[0-9]{4}$` format check as the live code column.
- Migrations: `ai-employees-app/supabase/migrations/20260824060000_employee_checkin_codes.sql`
  (base feature) and `20260824101200_employee_checkin_code_snapshot.sql` (the `_code` snapshot
  columns, added after the base feature shipped).

**Rollout safety:** both flags default off, so no existing business is affected. No RLS changes
were needed — the code is only ever written by the backend via the service-role client. It's
write-only for everyone except its owner: an Admin sees it once at set time and never again, but
the employee it belongs to can always view their own current code (see "Employee self-view"
below) — otherwise there'd be no way for them to actually learn it.

## Key files
**Backend (sam-backend)**
- `backend/app/routers/appointments.py` — `_resolve_employee_code()` / `_get_business_code_flags()`
  helpers; `update_appointment_status` (gates on `require_checkin_employee_code`, only for the
  `checked_in` transition) and `add_payment_entry` (gates on `require_payment_employee_code`) both
  accept an optional `employee_code` and 422 with "Employee code required"/"Invalid employee code"
  when the flag is on and the code is missing/wrong.
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
- `src/pages/dashboard/Calendar.tsx` — `handleCheckInClick`/`performStatusUpdate`: opens the PIN
  dialog before marking an appointment Checked In when `business.require_checkin_employee_code`
  is true.
- `src/components/appointments/PaymentDetailsDialog.tsx` — `submitEntry`: same gate on "Add
  Payment" for `business.require_payment_employee_code`.
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

## Viewing who checked in / collected a payment
The attribution captured above (`checked_in_by_user_id`, `collected_by_user_id`) was originally
write-only from the UI's perspective — stored on the record but not rendered anywhere. This is
now surfaced directly on the two existing screens rather than a separate report page:
- `src/pages/dashboard/Calendar.tsx` — the read-only "Appointment Details" dialog (`detailsOpen`)
  shows a **Checked In By** field alongside Client/Service/Assigned To/etc., resolved via the
  existing `getMemberName(userId)` helper; shows "—" when no code was captured (toggle was off,
  or the appointment predates this feature). When `checked_in_by_code` is present it's appended
  as `"Jane · Code 4821"` — the snapshot code, not a live lookup of the employee's current code.
- `src/components/appointments/PaymentDetailsDialog.tsx` — each payment entry shows a
  **Collected by** line under its timestamp, same "—" fallback when unset and same
  `"Jane · Code 4821"` format via `collected_by_code`. The dialog takes a new optional
  `getMemberName` prop (passed in from `Calendar.tsx`, which already has team member data via
  `useTeamManagement`) rather than fetching its own copy of the team list.
- No new role gate — this is visible to anyone who can already open these dialogs (matches every
  other field on them; there's no existing precedent for hiding parts of an appointment/payment
  from non-admin staff who have page access).
- `Appointment` (`useAppointments.ts`) and `AppointmentForm` (`Calendar.tsx`) both gained
  `checked_in_by_user_id`/`checked_in_at` (snake/camel respectively) to carry the values from the
  already-`select("*")` Supabase query through to the UI — no query or schema change needed, the
  columns were already being fetched, just not typed or displayed.

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
- **Code required only for the `checked_in` transition**, not `no_show`/`cancelled`/`confirmed`
  — matches the ticket's literal scope ("checking in a customer").
