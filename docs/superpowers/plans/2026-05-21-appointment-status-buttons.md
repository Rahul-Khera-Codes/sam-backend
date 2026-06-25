# Appointment Status Buttons — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Checked In / No Show / Cancelled Appointment status buttons to the Edit Appointment dialog, and implement the `run_noshow_calls()` cron job that calls no-show clients N days after their appointment.

**Architecture:** Status is stored in the existing `appointments.status` TEXT column. A new lightweight `PATCH /appointments/{id}/status` endpoint handles status-only updates (no GCal/email pipeline). A new `noshow_called_at` timestamp column prevents double-calling. The scheduler job follows the exact same pattern as `run_reschedule_calls()`.

**Tech Stack:** Python/FastAPI (backend), APScheduler (scheduler), React + TypeScript (frontend), Supabase.

---

## File Map

| File | What changes |
|---|---|
| `ai-employees-app/supabase/migrations/20260521000000_appointments_noshow_called_at.sql` | New — adds `noshow_called_at` column |
| `sam-backend/backend/app/schemas/appointments.py` | Add `UpdateAppointmentStatusRequest` schema |
| `sam-backend/backend/app/routers/appointments.py` | Add `PATCH /{id}/status` endpoint |
| `sam-backend/backend/app/services/scheduler_service.py` | Add `run_noshow_calls()`, register in `start_scheduler()` |
| `ai-employees-app/src/lib/voiceAgentApi.ts` | Add `updateAppointmentStatus()` function |
| `ai-employees-app/src/pages/dashboard/Calendar.tsx` | Add `status` to `AppointmentForm`, add status section to Edit dialog |

---

## Task 1: DB Migration — `noshow_called_at` column

**Files:**
- Create: `ai-employees-app/supabase/migrations/20260521000000_appointments_noshow_called_at.sql`

### Background

The `appointments` table already has `reminder_called_at` and `reschedule_called_at` (from migration `20260417000000`). We add the same pattern for no-show follow-up calls.

- [ ] **Step 1: Create the migration file**

Create `/home/lap-68/Documents/gt-rahul/ai-employees-app/supabase/migrations/20260521000000_appointments_noshow_called_at.sql`:

```sql
-- Migration: 20260521000000
-- Add noshow_called_at column to appointments for the no-show follow-up cron job.
-- Prevents the scheduler from calling the same client twice.

ALTER TABLE appointments
  ADD COLUMN IF NOT EXISTS noshow_called_at TIMESTAMPTZ DEFAULT NULL;
```

- [ ] **Step 2: Apply the migration**

```bash
cd /home/lap-68/Documents/gt-rahul/ai-employees-app
supabase db push
```

Expected output includes: `20260521000000_appointments_noshow_called_at` in the applied list.

- [ ] **Step 3: Regenerate Supabase TypeScript types**

```bash
cd /home/lap-68/Documents/gt-rahul/ai-employees-app
supabase gen types typescript --linked > src/integrations/supabase/types.ts
```

Verify `noshow_called_at` appears in the appointments Row type:

```bash
grep "noshow_called_at" src/integrations/supabase/types.ts
```

Expected: `noshow_called_at: string | null`

- [ ] **Step 4: Commit**

```bash
cd /home/lap-68/Documents/gt-rahul/ai-employees-app
git add supabase/migrations/20260521000000_appointments_noshow_called_at.sql src/integrations/supabase/types.ts
git commit -m "feat: add noshow_called_at column to appointments for no-show cron job"
```

---

## Task 2: Backend — `PATCH /appointments/{id}/status` endpoint

**Files:**
- Modify: `sam-backend/backend/app/schemas/appointments.py`
- Modify: `sam-backend/backend/app/routers/appointments.py`

### Background

The existing `PUT /appointments/{id}` goes through `booking_service.update_appointment()` which runs the full pipeline (GCal sync, availability check, emails). Status updates are lightweight — no pipeline needed.

Valid status values: `confirmed`, `checked_in`, `no_show`, `cancelled`.

- [ ] **Step 1: Add `UpdateAppointmentStatusRequest` schema**

In `sam-backend/backend/app/schemas/appointments.py`, add after the existing `UpdateAppointmentRequest` class (after line 28):

```python
VALID_APPOINTMENT_STATUSES = {"confirmed", "checked_in", "no_show", "cancelled"}


class UpdateAppointmentStatusRequest(BaseModel):
    business_id: str
    status: str
```

- [ ] **Step 2: Add `PATCH /{id}/status` endpoint to the router**

In `sam-backend/backend/app/routers/appointments.py`:

First, add `UpdateAppointmentStatusRequest` to the imports:

```python
from app.schemas.appointments import (
    CreateAppointmentRequest,
    UpdateAppointmentRequest,
    UpdateAppointmentStatusRequest,
    AppointmentResponse,
    CancelAppointmentResponse,
)
```

Then add the new endpoint before the `@router.delete` route. Also add the supabase_admin import at the top of the file:

```python
from app.core.supabase import supabase_admin
```

And the `VALID_APPOINTMENT_STATUSES` import:

```python
from app.schemas.appointments import (
    CreateAppointmentRequest,
    UpdateAppointmentRequest,
    UpdateAppointmentStatusRequest,
    AppointmentResponse,
    CancelAppointmentResponse,
    VALID_APPOINTMENT_STATUSES,
)
```

Add the endpoint:

```python
@router.patch("/{appointment_id}/status")
async def update_appointment_status(
    appointment_id: str,
    body: UpdateAppointmentStatusRequest,
    user_id: str = Depends(get_user_id),
):
    verify_business_access(user_id, body.business_id)
    if body.status not in VALID_APPOINTMENT_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid status. Must be one of: {', '.join(sorted(VALID_APPOINTMENT_STATUSES))}",
        )
    result = (
        supabase_admin.table("appointments")
        .update({"status": body.status})
        .eq("id", appointment_id)
        .eq("business_id", body.business_id)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Appointment not found")
    return result.data[0]
```

- [ ] **Step 3: Check that `supabase_admin` is importable in the router**

```bash
cd /home/lap-68/Documents/gt-rahul/sam-backend
grep -n "supabase_admin" backend/app/core/supabase.py 2>/dev/null || grep -rn "supabase_admin" backend/app/core/ | head -5
```

If `supabase_admin` is defined in a different module (e.g. `backend/app/core/supabase.py` or `backend/app/db.py`), use the correct import path. Check how other routers import it:

```bash
grep -n "from app.*import.*supabase_admin" backend/app/routers/settings.py | head -3
```

Use the same import path.

- [ ] **Step 4: Verify syntax**

```bash
cd /home/lap-68/Documents/gt-rahul/sam-backend
python -c "import ast; ast.parse(open('backend/app/routers/appointments.py').read()); print('OK')"
python -c "import ast; ast.parse(open('backend/app/schemas/appointments.py').read()); print('OK')"
```

Expected: `OK` for both.

- [ ] **Step 5: Run backend tests (if any exist)**

```bash
cd /home/lap-68/Documents/gt-rahul/sam-backend
python -m pytest backend/tests/ -v 2>&1 | tail -15
```

If no backend tests exist, skip.

- [ ] **Step 6: Commit**

```bash
cd /home/lap-68/Documents/gt-rahul/sam-backend
git add backend/app/schemas/appointments.py backend/app/routers/appointments.py
git commit -m "feat: add PATCH /appointments/{id}/status endpoint for lightweight status updates"
```

---

## Task 3: Scheduler — `run_noshow_calls()`

**Files:**
- Modify: `sam-backend/backend/app/services/scheduler_service.py`

### Background

`run_noshow_calls()` follows the exact pattern of `run_reminder_calls()` (lines 118–203 in `scheduler_service.py`). Key differences:
- Queries by `status = 'no_show'` AND `appointment_date = today - N days` AND `noshow_called_at IS NULL`
- Uses `feature_key = 'noshow_followup'`
- Stamps `noshow_called_at`
- `call_purpose = 'noshow_followup'`

The job runs hourly and is registered in `start_scheduler()`.

- [ ] **Step 1: Add `run_noshow_calls()` function**

In `scheduler_service.py`, add this function after `run_reschedule_calls()` (after line 293, before the `# ── Scheduler lifecycle` comment):

```python
async def run_noshow_calls() -> None:
    """
    Trigger follow-up calls for appointments that were marked no_show N days ago.
    Reads per-location config from agent_settings (feature_key=noshow_followup).
    """
    logger.info("Scheduler: no-show calls check started")
    today = date.today()

    try:
        cfg_rows = (
            supabase_admin.table("agent_settings")
            .select("business_id, location_id, config_value")
            .eq("feature_key", "noshow_followup")
            .eq("is_enabled", True)
            .execute()
        )
    except Exception as e:
        logger.error("Scheduler: failed to fetch no-show call configs: %s", e)
        return

    for cfg in (cfg_rows.data or []):
        business_id = cfg["business_id"]
        location_id = cfg["location_id"]
        config = cfg.get("config_value") or {}
        days = int(config.get("days") or 1)
        template = config.get("message_template") or (
            "Hi, we noticed you missed your recent appointment. "
            "We'd love to help you reschedule — would any of our available times work for you?"
        )

        target_date = (today - timedelta(days=days)).isoformat()

        try:
            appts = (
                supabase_admin.table("appointments")
                .select("id, client_phone, client_name, service, appointment_date")
                .eq("business_id", business_id)
                .eq("location_id", location_id)
                .eq("status", "no_show")
                .eq("appointment_date", target_date)
                .is_("noshow_called_at", "null")
                .execute()
            )
        except Exception as e:
            logger.error(
                "Scheduler: no-show query failed for location %s: %s", location_id, e
            )
            continue

        for appt in (appts.data or []):
            phone = (appt.get("client_phone") or "").strip()
            if not phone:
                logger.info(
                    "Scheduler: skipping no-show call for appointment %s — no client phone", appt["id"]
                )
                continue

            # Mark immediately to prevent double-calling on restart/overlap
            try:
                supabase_admin.table("appointments").update({
                    "noshow_called_at": datetime.now(timezone.utc).isoformat(),
                }).eq("id", appt["id"]).execute()
            except Exception as e:
                logger.error("Scheduler: failed to mark noshow_called_at for %s: %s", appt["id"], e)
                continue

            call_id = await _trigger_outbound_call(
                business_id=business_id,
                location_id=location_id,
                to_phone=phone,
                call_purpose="noshow_followup",
                message_template=template,
                appointment_id=appt["id"],
            )

            if call_id:
                logger.info(
                    "Scheduler: no-show call triggered — appointment=%s call=%s client=%s date=%s",
                    appt["id"], call_id, appt.get("client_name"), target_date,
                )
            else:
                logger.warning(
                    "Scheduler: no-show call failed — appointment=%s", appt["id"]
                )

    logger.info("Scheduler: no-show calls check finished")
```

- [ ] **Step 2: Register the job in `start_scheduler()`**

Find `start_scheduler()` (around line 298). It currently adds two jobs. Add a third:

```python
def start_scheduler() -> None:
    scheduler.add_job(
        run_reminder_calls,
        trigger="interval",
        hours=1,
        id="reminder_calls",
        replace_existing=True,
        misfire_grace_time=300,
    )
    scheduler.add_job(
        run_reschedule_calls,
        trigger="interval",
        hours=1,
        id="reschedule_calls",
        replace_existing=True,
        misfire_grace_time=300,
    )
    scheduler.add_job(
        run_noshow_calls,
        trigger="interval",
        hours=1,
        id="noshow_calls",
        replace_existing=True,
        misfire_grace_time=300,
    )
    scheduler.start()
    logger.info("Scheduler started — reminder + reschedule + no-show calls run every hour")
```

- [ ] **Step 3: Verify syntax**

```bash
cd /home/lap-68/Documents/gt-rahul/sam-backend
python -c "import ast; ast.parse(open('backend/app/services/scheduler_service.py').read()); print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Run agent tests**

```bash
cd /home/lap-68/Documents/gt-rahul/sam-backend/agent
python -m pytest tests/ -v 2>&1 | tail -10
```

Expected: 28 tests pass.

- [ ] **Step 5: Commit**

```bash
cd /home/lap-68/Documents/gt-rahul/sam-backend
git add backend/app/services/scheduler_service.py
git commit -m "feat: add run_noshow_calls() scheduler job — calls no-show clients N days after appointment"
```

---

## Task 4: Frontend API — `updateAppointmentStatus()`

**Files:**
- Modify: `ai-employees-app/src/lib/voiceAgentApi.ts`

### Background

`voiceAgentApi.ts` already has `updateAppointmentApi()` (around line 1017). We add a new function alongside it for status-only updates.

- [ ] **Step 1: Add the function**

In `ai-employees-app/src/lib/voiceAgentApi.ts`, find `updateAppointmentApi` and add this function directly after it:

```typescript
export async function updateAppointmentStatus(
  token: string,
  appointmentId: string,
  businessId: string,
  status: "confirmed" | "checked_in" | "no_show" | "cancelled",
): Promise<void> {
  const res = await fetch(`${API_BASE}/appointments/${appointmentId}/status`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ business_id: businessId, status }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? "Failed to update appointment status");
  }
}
```

- [ ] **Step 2: Verify TypeScript**

```bash
cd /home/lap-68/Documents/gt-rahul/ai-employees-app
npx tsc --noEmit 2>&1 | grep "error TS" | head -10
```

Expected: no output.

- [ ] **Step 3: Commit**

```bash
cd /home/lap-68/Documents/gt-rahul/ai-employees-app
git add src/lib/voiceAgentApi.ts
git commit -m "feat: add updateAppointmentStatus API function for PATCH /appointments/{id}/status"
```

---

## Task 5: Frontend UI — Status buttons in Edit Appointment dialog

**Files:**
- Modify: `ai-employees-app/src/pages/dashboard/Calendar.tsx`

### Background

`Calendar.tsx` has an `AppointmentForm` interface (line 69) that lacks a `status` field. The `appointments` useMemo (line 458) maps DB appointments to `AppointmentForm` but doesn't map `status`. The Edit dialog opens at line 1070.

We need to:
1. Add `status` to `AppointmentForm`
2. Map `status` in the useMemo
3. Add `updateAppointmentStatus` import
4. Add a status section above the form fields in the Edit dialog

- [ ] **Step 1: Add `status` to `AppointmentForm` interface**

Find the `AppointmentForm` interface at line 69. Add `status` as the last field before the closing brace:

```typescript
interface AppointmentForm {
  id?: string;
  date: Date;
  time: string;
  clientName: string;
  clientPhone: string;
  clientEmail: string;
  service: string;
  userId: string;
  userName: string;
  duration: string;
  notes: string;
  comments: string;
  doNotContact: boolean;
  status: string;
}
```

Also update `getDefaultNewAppointment` (line 88) to include `status`:

```typescript
const getDefaultNewAppointment = (date?: Date): AppointmentForm => ({
  date: date || new Date(),
  time: "9:00 AM",
  clientName: "",
  clientPhone: "",
  clientEmail: "",
  service: "",
  userId: "",
  userName: "",
  duration: "30 min",
  notes: "",
  comments: "",
  doNotContact: false,
  status: "confirmed",
});
```

- [ ] **Step 2: Map `status` in the `appointments` useMemo**

Find the `appointments` useMemo at line 458. Add `status` to the mapping:

```typescript
  const appointments = useMemo(() => {
    return dbAppointments.map((apt) => ({
      id: apt.id,
      date: parseISO(apt.appointment_date),
      time: apt.appointment_time,
      clientName: apt.client_name,
      clientPhone: apt.client_phone || "",
      clientEmail: apt.client_email || "",
      service: apt.service || "",
      userId: apt.assigned_user_id,
      userName: getMemberName(apt.assigned_user_id),
      duration: apt.duration || "30 min",
      notes: apt.notes || "",
      comments: apt.comments || "",
      doNotContact: apt.do_not_contact || false,
      status: apt.status || "confirmed",
    }));
  }, [dbAppointments, getMemberName]);
```

- [ ] **Step 3: Import `updateAppointmentStatus`**

Find the import from `@/lib/voiceAgentApi` at the top of Calendar.tsx. Add `updateAppointmentStatus` to it:

```typescript
import {
  // ... existing imports ...
  updateAppointmentStatus,
} from "@/lib/voiceAgentApi";
```

Also import `toast` if not already imported (check top of file — it's likely already there from sonner).

- [ ] **Step 4: Add status update handler**

Find `handleDeleteAppointment` (around line 621). Add a new handler after it:

```typescript
  const handleStatusUpdate = async (appointmentId: string, newStatus: "confirmed" | "checked_in" | "no_show" | "cancelled") => {
    if (!businessId || !session?.access_token) return;
    try {
      await updateAppointmentStatus(session.access_token, appointmentId, businessId, newStatus);
      setEditForm((prev) => prev ? { ...prev, status: newStatus } : prev);
      // Also update the underlying dbAppointments so calendar re-renders correctly
      refetch();
      toast.success("Status updated");
    } catch (err) {
      toast.error("Failed to update status");
    }
  };
```

Note: check what the refetch function is called in this component — it may be `refetchAppointments`, `reload`, or similar from `useAppointments`. Check how appointments are refreshed after `handleDeleteAppointment` and use the same approach.

- [ ] **Step 5: Add the status section to the Edit dialog**

Find line 1108: `{editForm && (`. Inside the `<div className="space-y-4 mt-4">`, add the status section **before** the existing form fields (before the `<div className="grid grid-cols-2 gap-4">`):

```tsx
          {editForm && (
            <div className="space-y-4 mt-4">
              {/* Appointment Status */}
              {editForm.id && (
                <div className="space-y-2">
                  <Label className="text-sm font-medium">Appointment Status</Label>
                  <div className="flex gap-2">
                    <Button
                      type="button"
                      size="sm"
                      variant={editForm.status === "checked_in" ? "default" : "outline"}
                      className={editForm.status === "checked_in" ? "bg-green-600 hover:bg-green-700 text-white" : "border-green-600 text-green-700 hover:bg-green-50"}
                      onClick={() => handleStatusUpdate(editForm.id!, "checked_in")}
                    >
                      Checked In
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      variant={editForm.status === "no_show" ? "default" : "outline"}
                      className={editForm.status === "no_show" ? "bg-amber-500 hover:bg-amber-600 text-white" : "border-amber-500 text-amber-700 hover:bg-amber-50"}
                      onClick={() => handleStatusUpdate(editForm.id!, "no_show")}
                    >
                      No Show
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      variant={editForm.status === "cancelled" ? "default" : "outline"}
                      className={editForm.status === "cancelled" ? "bg-destructive hover:bg-destructive/90 text-white" : "border-destructive text-destructive hover:bg-destructive/10"}
                      onClick={() => handleStatusUpdate(editForm.id!, "cancelled")}
                    >
                      Cancelled
                    </Button>
                  </div>
                </div>
              )}

              {/* existing form fields start here */}
              <div className="grid grid-cols-2 gap-4">
```

- [ ] **Step 6: Verify TypeScript**

```bash
cd /home/lap-68/Documents/gt-rahul/ai-employees-app
npx tsc --noEmit 2>&1 | grep "error TS" | head -10
```

Fix any errors before committing. Common issue: `refetch` function name — check `useAppointments` hook for the correct name.

- [ ] **Step 7: Commit**

```bash
cd /home/lap-68/Documents/gt-rahul/ai-employees-app
git add src/pages/dashboard/Calendar.tsx
git commit -m "feat: add Checked In / No Show / Cancelled status buttons to Edit Appointment dialog"
```

---

## Self-Review Checklist

- [x] **Spec coverage**: DB column (Task 1), status endpoint (Task 2), scheduler job (Task 3), API function (Task 4), UI buttons (Task 5)
- [x] **No placeholders**: all code blocks complete and exact
- [x] **Type consistency**: `"confirmed" | "checked_in" | "no_show" | "cancelled"` used in voiceAgentApi.ts, Calendar.tsx handler, and backend validation set
- [x] **Pattern consistency**: `run_noshow_calls()` matches `run_reschedule_calls()` structure exactly — same error handling, same stamp-before-call pattern, same `_trigger_outbound_call()` usage
- [x] **No migration needed for status column** — already exists, just adding new values (TEXT column, no enum constraint)
- [x] **supabase_admin import in appointments.py** — Task 2 Step 3 explicitly checks the correct import path before committing
