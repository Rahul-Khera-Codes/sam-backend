# Customer List (AIE-61)

## What it does
A "Customer List" page at `/dashboard/customer-list`, a top-level Sidebar item between Dashboard and Calendar, that lets a business search, add, edit, delete, and bulk-import customer records — plus a shared `customers` table that appointment booking (web and voice agent) now resolves-or-creates automatically, so a customer's appointment history accumulates on one durable record instead of being scattered as free-text per appointment.

Before this feature there was no customer entity at all: `appointments.client_name/client_phone/client_email` were free-text columns duplicated per booking, with no dedup and no way to look up a client's history.

## Key files

**ai-employees-app (frontend)**
- `supabase/migrations/20260907160000_customers.sql` — new `customers` table (RLS scoped by `business_id`/`location_id`, following the `calls` table convention) and `appointments.customer_id` (nullable FK, `ON DELETE SET NULL`).
- `src/hooks/useCustomers.ts` — CRUD hook (direct Supabase reads/writes, no backend REST layer — matches the `LocationsTab.tsx` precedent for plain CRUD tables), plus `fetchLastVisits` (bulk `{customer_id, appointment_date}` query, reduced client-side to avoid N+1) and `fetchAppointmentHistory` (per-customer appointment list for the edit modal).
- `src/pages/dashboard/CustomerList.tsx` — the page: search/filter, table with a "days since last visit" pill, Add/Edit/Delete dialogs, CSV import (client-side parse/preview, no new dependency — ported from the design mockup's own vanilla-JS parser).
- `src/components/layout/Sidebar.tsx` — added the top-level "Customer List" nav item, between Dashboard and Calendar.
- `src/App.tsx` — added the `customer-list` route directly under `/dashboard`, alongside `calendar`.

**sam-backend**
- `backend/app/services/customers_service.py` — `resolve_or_create_customer(supabase, business_id, location_id, client_name, client_phone, client_email, do_not_contact)`: normalizes phone to E.164, looks up an existing customer by phone (falling back to email), creates one if not found, returns its id. Duplicated (not imported) into `agent/agent.py` as `_resolve_or_create_customer` — `backend/` and `agent/` are separate Docker build contexts with no shared module, matching how booking logic is already duplicated between them.
- `backend/app/services/booking_service.py::create_appointment` — calls the helper before inserting, sets `customer_id` on the new appointment row.
- `agent/agent.py::book_appointment` — same, using the agent's own Supabase client.

## Decisions / tradeoffs
- **Placement**: Customer List is a top-level Sidebar item, between Dashboard and Calendar — not nested under any employee's sub-nav. (First pass had it under the Sales Employee sub-nav, matching the attached design mockup's literal layout; the client's actual intent, per a follow-up correction, was a standalone top-level section, matching the issue title's "above the Calendar, below the Dashboard" wording.)
- **No "Sales History" section**: the mockup showed mock product/invoice line items; there's no products/invoicing data model in either repo, so v1 only has real **Appointment History** (from `appointments.customer_id`). Add Sales History once an invoicing system exists.
- **Only appointment *creation* links to a customer.** `update_appointment`/`cancel_appointment` are untouched in both `booking_service.py` and `agent.py` — the request was specifically about new appointments.
- **No new backend REST endpoints for customer CRUD.** The frontend does direct Supabase table access for manual add/edit/delete (like `locations`), since there are no server-side side effects needed for a plain customer record. The backend only touches `customers` internally, as part of the booking flow.
- **Matching key**: phone (E.164-normalized) first, email as fallback, scoped to `business_id`. No fuzzy name matching — deliberately conservative to avoid merging two different people.
- **No backfill.** `appointments.customer_id` is null on every pre-existing row; only appointments created after this ships get linked.
- Calendar.tsx's "New Appointment" modal was **not** changed — customer linking happens transparently server-side; adding a customer-search/autocomplete to that modal's Client Name field is a possible follow-up, not built here.

## Verified
- `supabase db push` applied; `customers` table + `appointments.customer_id` confirmed present via generated types (`src/integrations/supabase/types.ts` regenerated).
- `npx tsc --noEmit` clean on the frontend.
- `resolve_or_create_customer` tested directly against the live DB (business "Test corp"): first call creates a customer with normalized phone; second call with a differently-formatted same phone number resolves to the same row instead of duplicating; test row cleaned up after.
- Both Docker stacks (`ai-employees-app`, `sam-backend`) rebuilt and confirmed responsive after the change.
- Not yet verified: an interactive browser walkthrough of the Customer List page and a full end-to-end appointment booking through the web "New Appointment" modal / a live voice-agent call (needs a logged-in session / test call — see open items below).
