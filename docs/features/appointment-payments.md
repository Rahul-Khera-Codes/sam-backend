# Appointment Payments (Split / Partial Payments)

## What it does
Staff record payment against a booked appointment from the "Payment Details" dialog (opened
from an appointment in Calendar). Originally this only supported one payment method for the
full amount, set via a manual Status/Payment Type dropdown pair. It now supports **split and
partial payments** — e.g. a customer pays $25 cash and the rest on debit card, or pays $100
today and the remaining balance on a later visit.

## Data model
- **`appointment_payments`** — the "invoice": line items, selected taxes, subtotal, tax total,
  tip, grand total. One row per appointment (`UNIQUE(appointment_id)`, unchanged from before).
  `status` and `payment_type` columns were **dropped** — no longer stored, since a split
  payment can't be described by a single type, and a stored status could drift from what was
  actually paid.
- **`appointment_payment_entries`** (new) — one row per individual payment recorded against an
  appointment_payments row: `payment_type`, `amount`, optional `note`, `paid_at`. Many rows per
  appointment now possible. Editable/deletable (not an append-only ledger).
  `payment_type` is a `TEXT CHECK` (no native Postgres enum), currently:
  `cash`, `credit_card`, `debit_card`, `e_transfer`, `other`, `coupon`, `gift_card`, `paypal`,
  `cheque` (last 4 added for AIE-26, migration
  `20260824000000_add_payment_types_coupon_giftcard_paypal_cheque.sql`). The CHECK constraint,
  the backend `PaymentType` Literal (`schemas/appointments.py`), the frontend `PaymentType`
  union (`lib/voiceAgentApi.ts`), the dropdown labels (`PAYMENT_TYPE_LABELS` in
  `hooks/useAppointmentPayments.ts`), and the entry icon map (`PAYMENT_TYPE_ICONS` in
  `PaymentDetailsDialog.tsx`) must all be updated together whenever a payment type is
  added/removed — there's no single source of truth. Refund is invoice-level
  (`appointment_payments.refunded_at`), so it doesn't special-case any payment type; no
  reporting/analytics code sums `appointment_payment_entries` today, so type additions have no
  other blast radius.
- **`refunded_at`** (new, on `appointment_payments`) — the one manual override. Everything else
  is computed.
- **`collected_by_user_id`** (new, on `appointment_payment_entries`) — added for AIE-28. Separate
  from `created_by` (who was logged in): when a business turns on
  `businesses.require_payment_employee_code`, staff must enter their own 4-digit code to record
  a payment, and this column stores the employee the code identified. See
  `docs/features/employee-checkin-codes.md`.

**Status is always computed, never stored**, at read time in
`backend/app/routers/appointments.py::_build_full_payment_response`:
- `refunded_at is not null` → `refunded`
- `paid_amount <= 0` → `unpaid`
- `paid_amount < grand_total` → `partially_paid`
- `paid_amount >= grand_total` → `paid` (overpayment is allowed — `owing_amount` goes negative,
  displayed in the UI as a "Credit")

`paid_at` on the response is derived too: the timestamp of whichever entry first pushed the
cumulative sum to `>= grand_total` (not stored, not preserved through partial refund/re-payment
cycles — recomputed fresh every time from current entries).

Migration: `ai-employees-app/supabase/migrations/20260819100000_appointment_payment_entries.sql`.
It backfills history for pre-existing rows before dropping columns: any row that was
`status='paid'` gets one `appointment_payment_entries` row for its full `grand_total` (so
historical fully-paid appointments don't silently show `$0 paid`), and any `status='refunded'`
row gets `refunded_at` set from its old `paid_at`/`updated_at`.

## Key files
**Backend (sam-backend)**
- `backend/app/routers/appointments.py` — `GET/PUT /appointments/{id}/payment` (invoice),
  `POST /appointments/{id}/payment/entries` (add a payment — requires the invoice row to
  already exist, 404s otherwise), `PATCH/DELETE .../entries/{entry_id}` (edit/delete one
  entry), `POST/DELETE .../payment/refund` (set/clear `refunded_at`). All return the full
  `AppointmentPaymentResponse` (entries + computed paid/owing/status) so the frontend can just
  replace its local state wholesale after any mutation.
- `backend/app/schemas/appointments.py` — `PaymentStatus`, `PaymentType`,
  `AppointmentPaymentEntry`, `CreatePaymentEntryRequest`, `UpdatePaymentEntryRequest`,
  `RefundPaymentRequest`, `AppointmentPaymentResponse`.

**Frontend (ai-employees-app)**
- `src/components/appointments/PaymentDetailsDialog.tsx` — the editable dialog. "Save Payment
  Details" saves only the invoice (line items/tax/tip) and closes the dialog. "Add Payment"
  first re-saves the invoice (ensures the row exists/is current), then records the entry, and
  does **not** close the dialog — supports adding multiple entries in one sitting (the $25
  cash + rest on card case) without re-opening.
- `src/pages/dashboard/Calendar.tsx` — read-only appointment-detail summary. No longer
  duplicates paid/owing math — consumes `paid_amount`/`owing_amount`/`status` directly from the
  API response instead of re-deriving them client-side (the old duplicated calculation was a
  known drift risk flagged when this feature was scoped).
- `src/hooks/useAppointmentPayments.ts` — `savePayment`, `addPaymentEntry`,
  `updatePaymentEntry`, `deletePaymentEntry`, `refundPayment`, `unrefundPayment`. Also exports
  `PAYMENT_TYPE_LABELS`/`PAYMENT_STATUS_LABELS` (shared between the dialog and Calendar.tsx —
  previously each file had its own copy).
- `src/lib/voiceAgentApi.ts` — API client functions/types for all of the above.

## Decisions / tradeoffs
- **No frontend recomputation of paid/owing/status** — both consumers read these directly from
  the backend response. This was simpler than the originally-planned "shared frontend helper"
  once it became clear the backend already computes and returns these fields authoritatively.
- **Entries are editable/deletable**, not an append-only ledger — chosen deliberately so staff
  can fix a mis-entered amount/type directly rather than needing an offsetting correction entry.
- **Overpayment is allowed and shown as a credit** (negative `owing_amount`), not blocked.
- **Adding a payment always re-saves the invoice first** — avoids needing the backend to
  auto-create a default invoice snapshot (which would require duplicating the frontend's
  service-price-lookup logic server-side); the frontend already holds the current line
  items/tax/tip in state, so re-saving is cheap and keeps the invoice current.
- **Payments can be added across multiple separate sessions** (not just split at one checkout
  moment) — the "Add Payment" action works identically whether the dialog was just opened for
  the first time or reopened weeks later; nothing about the data model or endpoints assumes a
  single sitting.
