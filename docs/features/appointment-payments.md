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
- **`entry_type`** (new, on `appointment_payment_entries`, migration
  `20260904120500_partial_refund_entries.sql`) — `"payment"` (default) or `"refund"`. AIE-50
  follow-up: refunds are now **partial, amount-bound ledger entries** in the same table as
  payments, not an all-or-nothing toggle. A refund entry's `created_by` is the audit record of
  who processed it (Sam's ask: "a record should show who refunded it") — no new column needed,
  it reuses the column payment entries already had. `compute_invoice_status` sums `payment`
  entries minus `refund` entries to get `paid_amount`; a full refund brings it to `0` (status
  `"refunded"`), a partial refund just reduces it and reopens `owing_amount` by the same amount
  (status recomputes normally — `"partially_paid"`/`"paid"`/`"unpaid"` as usual). Undoing a
  refund is deleting that specific entry via the existing
  `DELETE /payment/entries/{entry_id}` — there's no separate "unrefund" endpoint anymore.
  **Validation**: `POST /payment/refund` and `PATCH /payment/entries/{entry_id}` both reject an
  amount greater than the amount currently paid (`paid_amount`, net of any prior refunds) with a
  400 — this was the actual QA follow-up comment on AIE-50 ("restriction error so you cannot
  refund more than the bill"). Client-side, `PaymentDetailsDialog.tsx` caps the refund input at
  `paidAmount` too, but the backend check is authoritative.
  `appointment_payments.refunded_at` (the old toggle column, migration
  `20260819100000_appointment_payment_entries.sql`) is no longer written to by the backend — the
  `refunded_at` field on `AppointmentPaymentResponse` is now derived at read time as the latest
  refund-entry's `paid_at`. The column itself is left in place (unused) rather than dropped, to
  avoid a destructive migration; historical rows that already have it set are still respected by
  `/payment-summary`'s "money collected" query (see below) for backward compatibility.
  The `GET /revenue-summary` endpoint's outstanding-balance total (`backend/app/routers/reports.py`)
  shares the same `compute_invoice_status` call, so a partially-or-fully refunded invoice with a
  net owing balance surfaces there too — kept deliberately distinct from `/payment-summary`'s
  "money collected" query, which excludes `entry_type = "refund"` rows outright so a refund is
  never counted as revenue (see `docs/features/payment-summary-report.md`).
- **`collected_by_user_id`** (new, on `appointment_payment_entries`) — added for AIE-28. Separate
  from `created_by` (who was logged in): when a business turns on
  `businesses.require_payment_employee_code`, staff must enter their own 4-digit code to record
  a payment, and this column stores the employee the code identified. See
  `docs/features/employee-checkin-codes.md`.

**Status is always computed, never stored**, at read time in
`backend/app/services/booking_service.py::compute_invoice_status` (called from
`appointments.py::_build_full_payment_response`, the dashboard appointments list, and from
`reports.py`'s outstanding-balance calc). `paid_amount` = sum of `entry_type="payment"` entries
minus sum of `entry_type="refund"` entries (floored at `0`):
- `paid_amount <= 0` and at least one refund entry exists → `refunded` (fully refunded — money
  was collected and then all of it returned)
- `paid_amount <= 0`, no refunds → `unpaid`
- `paid_amount < grand_total` → `partially_paid` (also covers a *partial* refund that still
  leaves a balance paid)
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
  entry — works for refund entries too, since they live in the same table), `POST .../payment/refund`
  (record a refund entry, validated against `paid_amount`). All return the full
  `AppointmentPaymentResponse` (entries + computed paid/owing/status) so the frontend can just
  replace its local state wholesale after any mutation.
- `backend/app/schemas/appointments.py` — `PaymentStatus`, `PaymentType`, `EntryType`,
  `AppointmentPaymentEntry`, `CreatePaymentEntryRequest`, `UpdatePaymentEntryRequest`,
  `RefundPaymentRequest` (now `business_id` + `payment_type` + `amount` + optional `note`/`employee_code`,
  not just `business_id`), `AppointmentPaymentResponse`.

**Frontend (ai-employees-app)**
- `src/components/appointments/PaymentDetailsDialog.tsx` — the editable dialog. "Save Payment
  Details" saves only the invoice (line items/tax/tip) and closes the dialog. "Add Payment"
  first re-saves the invoice (ensures the row exists/is current), then records the entry, and
  does **not** close the dialog — supports adding multiple entries in one sitting (the $25
  cash + rest on card case) without re-opening. A "Record a refund" block (only shown once
  `paid_amount > 0`) works the same way, capped client-side at `paidAmount`; refund entries
  render inline in the same entries list with an "Undo" icon, a "Refund" tag, and "Refunded by"
  instead of "Collected by" — deletable but not editable (delete and re-add instead of editing,
  to avoid re-implementing the cap-validation UI for an edit path).
- `src/pages/dashboard/Calendar.tsx` — read-only appointment-detail summary. No longer
  duplicates paid/owing math — consumes `paid_amount`/`owing_amount`/`status` directly from the
  API response instead of re-deriving them client-side (the old duplicated calculation was a
  known drift risk flagged when this feature was scoped). Its own entries list marks refund rows
  with a "(Refund)" suffix and a negative, destructive-colored amount.
- `src/hooks/useAppointmentPayments.ts` — `savePayment`, `addPaymentEntry`,
  `updatePaymentEntry`, `deletePaymentEntry`, `refundPayment` (now takes amount/payment_type/note/employee_code,
  not just an appointment id — `unrefundPayment` was removed, undo is `deletePaymentEntry` on the
  refund entry). Also exports `PAYMENT_TYPE_LABELS`/`PAYMENT_STATUS_LABELS` (shared between the
  dialog and Calendar.tsx — previously each file had its own copy).
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
- **Refunds reuse the `appointment_payment_entries` ledger** (AIE-50 follow-up) rather than a new
  `refunds` table — a refund is symmetric to a payment (amount, method, note, `paid_at`,
  `created_by` for audit), so `entry_type` was the smallest change that gave partial refunds,
  audit trail, and a real "amount paid" to validate against, all at once.
- **The refund cap is `paid_amount` (net of prior refunds), not `grand_total`** — the QA comment
  said "can't refund more than the bill," but the actually-correct constraint is you can't refund
  money that was never collected. If the invoice is only half paid, the cap is that half, not the
  full invoice total.
- **No separate "unrefund" endpoint** — since a refund is now just an entry, undoing one is
  deleting it via the endpoint that already existed for that (`DELETE .../entries/{entry_id}`).
  Keeping a dedicated unrefund endpoint alongside would have meant two ways to remove a refund
  entry that needed to stay in sync.
