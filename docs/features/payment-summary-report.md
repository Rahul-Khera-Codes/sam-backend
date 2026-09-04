# Payment Summary Report (AIE-27)

## What it does
A new **Reports** section in the left sidebar (currently one report, built to hold more later per
the ticket's follow-up comment) showing money made over a date range: subtotal, tax, tips, grand
total, and payment count — broken down by date, payment type, and employee. Filters: date range
(Today/This Week/This Month presets, or custom), location (single-select), and team members
(multi-select).

## Scope decisions (confirmed with the user before implementation)
- **Two employee breakdowns, not one** — `by_assigned_employee` (who the appointment was assigned
  to — always populated) and `by_collected_employee` (who entered their [[project_employee_checkin_codes|AIE-28]]
  code to collect payment — only populated when a business has that toggle on). The team-member
  filter scopes on `assigned_user_id`.
- **Tip/tax allocated proportionally per payment entry** — tip/tax live on the invoice
  (`appointment_payments.tip_amount`/`tax_total`), not per entry, so a split/partial payment entry's
  `amount` is divided into subtotal/tax/tip portions using the parent invoice's own ratios
  (`subtotal:tax:tip` out of `grand_total`). The three portions always sum back to the entry's
  `amount` — no double-counting.
- **Location filter reuses the single-select convention** — no new multi-select pattern; the report
  page's own dropdown (all accessible locations + "All Locations") defaults to the sidebar's
  globally selected location but is independently changeable per-report.
- **Access: Admin & Super Admin** (`isAdmin()`), not Super Admin only — matches how other
  financial/sensitive pages (e.g. the AIE-28 payment-code toggles) are gated, unlike Mission
  Control/Sales Manager which are hardcoded Super-Admin-only in `AuthContext.canAccess()`. Reports
  deliberately goes through the normal DB-driven `permittedPaths`/`RESTRICTED_PAGES` path instead
  of a hardcoded prefix check, so per-user access can still be granted/restricted via Roles &
  Permissions.
- **Two assumptions not specified in the ticket**, flagged and accepted:
  - Buckets/filters by `paid_at` (when money came in), not `appointment_date`.
  - Excludes refunds from "money made" — updated for AIE-50's partial-refund follow-up: the entries
    query now filters `entry_type != "refund"` directly (a refund entry sits in the same table as
    payment entries, see [[project_ai_employees_repos|appointment-payments.md]]), on top of the
    original invoice-level `refunded_at` exclusion which still applies for pre-AIE-50 historical
    rows that used the old all-or-nothing toggle.
- **Employee codes shown in "By Employee (Collected)" only, as snapshots** — the user asked to
  show codes since this page is Admin/Manager-only, but this deliberately does **not** expose each
  employee's live `user_roles.check_in_code`, which AIE-28 made write-only (an Admin sees it once
  at set time, never again — only the employee can view their own current code). Instead it shows
  the distinct `collected_by_code` snapshot(s) actually used for payments in the selected range —
  historical audit data, not a live secret, matching the existing precedent in
  `PaymentDetailsDialog` ("Jane · Code 4821"). "By Employee (Assigned)" has no code column at all —
  being assigned an appointment never requires entering a code.

## Data model
No new tables/columns/migration — built entirely on existing AIE-28-era columns:
`appointment_payment_entries` (`payment_type`, `amount`, `paid_at`, `collected_by_user_id`),
`appointment_payments` (`subtotal`, `tax_total`, `tip_amount`, `grand_total`, `location_id`,
`refunded_at`), `appointments` (`assigned_user_id`).

## Key files
**Backend (sam-backend)**
- `backend/app/routers/reports.py` — new router, `GET /reports/payment-summary?business_id&
  start_date&end_date&location_id&employee_ids`. Follows the existing `analytics.py` convention:
  `Depends(require_business_access())` for auth, `supabase_admin`, aggregation done in Python after
  fetching filtered rows (not Postgres `GROUP BY`) — no embedded/nested Supabase joins, three
  separate queries (`appointment_payments` → `appointments` → `appointment_payment_entries`) joined
  in memory via dicts, matching how the rest of the codebase avoids relying on PostgREST embedded
  resource filtering.
- `backend/app/main.py` — registered `reports_router`.
- `collected_codes` (per-`collected_by_user_id` set of `collected_by_code` values seen in range) is
  built alongside `by_collected_employee` and attached to each row as `codes: string[]` — sorted,
  deduped, can be more than one entry if the employee's code was reset mid-range.

**Frontend (ai-employees-app)**
- `src/components/layout/ReportsLayout.tsx` — gate (`isAdmin()`) + `<Outlet />`, mirrors
  `MissionControlLayout`/`SalesCommandCenterLayout`.
- `src/pages/dashboard/reports/PaymentSummaryReport.tsx` — the report page: date-range presets +
  custom date inputs (matches `Calendar.tsx`'s `<Input type="date">` convention), location
  `<Select>`, team-member multi-select via `<Popover>` + `<Checkbox>` list, `StatCard` totals row,
  and three `<Table>` breakdowns (by date, by payment type, two employee tables side by side).
- `src/components/layout/Sidebar.tsx` — new collapsible `NavGroup` "Reports" (icon `DollarSign`),
  gated by `showReports = isAdmin()`, containing `reportsNavItems` (currently just "Payment
  Summary" — designed to hold more report items later).
- `src/App.tsx` — `<Route path="reports" element={<ReportsLayout />}>` wrapping an index redirect
  to `payment-summary`, mirroring the Mission Control/Sales Command Center nested-layout pattern.
- `src/lib/roles.ts` — `RESTRICTED_PAGES["/dashboard/reports"]` and
  `RESTRICTED_PAGES["/dashboard/reports/payment-summary"]` both `["super_admin", "admin"]`.
- `src/pages/dashboard/RolesPermissions.tsx` — added to `ALL_PAGES` (group "Main") so admins can
  grant/restrict per-user access.
- `src/lib/voiceAgentApi.ts` — `getPaymentSummaryReport()` + `PaymentSummaryReportApi` types.

## Naming collision (pre-existing, unrelated)
`/dashboard/mission-control/reports` and `/dashboard/sales-command-center/reports` already exist —
both are unimplemented Super-Admin-only placeholders (exec/sales-manager reports), unrelated to
this feature. Not renamed as part of this work; flagged here so it isn't confused with the new
top-level Reports section.

## Possible follow-ups (not built)
- More report types under the same "Reports" sidebar section (the section was built to hold them).
- CSV/PDF export — not requested in the ticket.
- Multi-select location filtering, if a business wants a combined view across locations.
