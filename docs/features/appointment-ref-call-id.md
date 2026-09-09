# Appointment Ref ↔ Call ID linkage (AIE-79)

## What it does
The short customer-facing "Ref" (e.g. `A652932C`) shown in booking-confirmation SMS/email was
never persisted or linked back to the call it came from, and the Calendar's Appointment Details
was inadvertently leaking the long internal call UUID through the free-text `notes` field. Fixed
by adding a real FK from an appointment to its originating call, and surfacing the Ref everywhere
the call UUID used to leak or was simply missing.

## Key files
**Database (ai-employees-app)**
- `supabase/migrations/20260909000000_appointment_call_ref.sql` — adds
  `appointments.call_id UUID REFERENCES calls(id) ON DELETE SET NULL` + index. Nullable: only
  voice-agent bookings have an originating call; dashboard/API-created appointments stay NULL.

**Backend (sam-backend)**
- `agent/agent.py`
  - `_confirmation_ref(appointment_id)` (~line 97) — single source of truth for the Ref
    (`appointment_id[:8].upper()`), replacing 4 previously-duplicated inline slices in
    `book_appointment`, `find_appointments`, `update_appointment` (reschedule), and
    `cancel_appointment`.
  - `book_appointment` — no longer appends `"| call_id: <uuid>"` into the appointment's `notes`;
    writes `self._call_id` into the new `call_id` column instead. Notes now only ever contain what
    was actually said/entered.
- `backend/app/services/booking_service.py` — same `_confirmation_ref()` helper (dedup only; this
  is the non-voice booking path and never touched `notes`/`call_id`).
- `backend/app/schemas/calls.py` — `CallResponse.appointment_ref: Optional[str]`.
- `backend/app/routers/calls.py` `list_calls` (`GET /calls`) — after fetching call rows, batch-
  queries `appointments` for `call_id IN (<call ids>)` and attaches `appointment_ref` per call.
  This is the only calls list/detail endpoint the frontend uses (Call Recordings selects a call's
  detail from the already-loaded list — there's no separate single-call GET).

**Frontend (ai-employees-app)**
- `src/lib/voiceAgentApi.ts` — `CallRecord.appointment_ref?: string | null`.
- `src/pages/dashboard/customer-service/CallRecordings.tsx` — call-detail header shows
  `Ref: {appointment_ref}` when the selected call produced a booking.
- `src/pages/dashboard/Calendar.tsx` — Appointment Details dialog now shows a "Ref" row
  (`selectedAppointment.id.slice(0, 8).toUpperCase()`), computed client-side from the `id` already
  present in `useAppointments`' `select("*")` — no new backend field needed for Calendar itself.

## Decisions / tradeoffs
- **`call_id` on `appointments`, not `appointment_id` on `calls`.** An appointment has at most one
  originating call (the one it was booked during); a call can only ever have produced the one
  booking, so either direction works, but this keeps `calls` (append-only call log) untouched by
  booking-time writes.
- **Only set at creation, never on reschedule/cancel.** A customer rescheduling/cancelling by
  phone is a *different* call than the one that created the appointment — overwriting `call_id`
  on those calls would point it at the wrong call. It reflects "which call created this booking",
  not "which calls have touched this booking."
- **No retroactive backfill.** Appointments booked before this fix still have the old
  `"| call_id: <uuid>"` text baked into their stored `notes` — not cleaned up automatically.
- **Recording storage path/filename unchanged** (`{business_id}/{call_id}.ogg`) — Dev needs the
  raw call UUID for storage/tracing, and no on-screen label ever called it out as "Call ID" for
  end users to confuse with Ref, so there was nothing user-facing to change there.
- **Cancel/reschedule's ref lookup (`id.startswith(ref)`) left as-is** — same 8-char slice as
  everywhere else via `_confirmation_ref`, not a new issue introduced by this change.
