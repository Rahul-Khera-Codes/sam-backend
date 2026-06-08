# Spec: Team Management Option B — Reassign Before Remove

**Date:** 2026-06-08  
**Requested by:** Sam Maisuria (confirmed Option B, 2026-06-05)  
**Status:** Ready to implement

---

## Problem

Admins can remove a team member who has upcoming appointments assigned to them. Those appointments become orphaned (no assigned staff). A naive bulk-reassign to one replacement is unsafe — the replacement may already have appointments at the same time slots, creating double-bookings.

---

## Desired Behaviour

When an admin clicks **Remove** on a team member:

1. **Check for upcoming appointments** — query `appointments` where `assigned_user_id = userId AND appointment_date >= today AND status NOT IN ('cancelled', 'no_show')`
2. **If 0 upcoming appointments** — remove immediately (existing behaviour, unchanged)
3. **If N upcoming appointments exist** — open the reassign dialog (table view, one row per appointment)

---

## UI Flow

```
Admin clicks Remove on User X
  └─ fetch upcoming appointments for User X
       ├─ 0 → existing confirm dialog → remove
       └─ N →
            ┌──────────────────────────────────────────────────────────────────┐
            │ ⚠ Alex has 3 upcoming appointments                               │
            │ Select a replacement for each. Conflicts are flagged in red.     │
            │                                                                  │
            │ Date/Time          Service       Replacement        Status       │
            │ Jun 12, 10:00 AM   Haircut       [Sam ▼]            ✅ Available │
            │ Jun 13, 2:00 PM    Beard Trim    [Sam ▼]            ❌ Conflict  │
            │                                  → Sam has appt at 2:00 PM Jun 13│
            │ Jun 15, 11:00 AM   Haircut       [Maria ▼]          ✅ Available │
            │                                                                  │
            │ [Cancel]                         [Reassign & Remove] (disabled  │
            │                                   until all rows resolved)       │
            └──────────────────────────────────────────────────────────────────┘
```

- **Per-row replacement dropdown** — each appointment has its own dropdown, defaulting to empty
- **Conflict validation** — fires when a replacement is selected for a row:
  - Fetch replacement's existing appointments on the same date
  - Check overlap: `new_start < existing_end AND new_end > existing_start`
  - If conflict: row turns red, shows "Conflict: [Replacement] has an appointment at [time] on [date]"
  - If clear: row turns green ✅
- **"Reassign & Remove" button** — disabled until ALL rows have a replacement selected AND no row has a conflict
- **Cancel** — closes dialog, no changes

---

## Validation Logic

For each row where a replacement is selected:

```ts
// Fetch replacement's appointments on the same date
const { data: existingAppts } = await supabase
  .from('appointments')
  .select('id, appointment_time, duration_minutes')
  .eq('assigned_user_id', replacementId)
  .eq('appointment_date', appointment.appointment_date)
  .not('status', 'in', '("cancelled","no_show")')

// Check overlap for each existing appointment
const newStart = timeToMinutes(appointment.appointment_time)
const newEnd = newStart + (appointment.duration_minutes ?? 60)

const hasConflict = existingAppts.some(existing => {
  const exStart = timeToMinutes(existing.appointment_time)
  const exEnd = exStart + (existing.duration_minutes ?? 60)
  return newStart < exEnd && newEnd > exStart
})
```

Conflict message: `"[Replacement name] has an appointment at [existing_time] on [date]"`

---

## State

```ts
type RowState = {
  appointmentId: string
  date: string
  time: string
  service: string
  durationMinutes: number
  replacementId: string        // "" = not selected yet
  conflict: string | null      // null = no conflict, string = conflict message
  validating: boolean
}

const [reassignDialogUser, setReassignDialogUser] = useState<TeamMember | null>(null)
const [rows, setRows] = useState<RowState[]>([])
const [isReassigning, setIsReassigning] = useState(false)
```

`"Reassign & Remove"` enabled when:
```ts
rows.every(r => r.replacementId !== "" && r.conflict === null && !r.validating)
```

---

## Data fetching

**Upcoming appointments for removed user:**
```ts
const today = new Date().toISOString().split('T')[0]
const { data } = await supabase
  .from('appointments')
  .select('id, service, appointment_date, appointment_time, duration_minutes')
  .eq('assigned_user_id', userId)
  .eq('business_id', businessId)
  .gte('appointment_date', today)
  .not('status', 'in', '("cancelled","no_show")')
  .order('appointment_date', { ascending: true })
```

**Conflict check** — fires per row when replacement selected (debounced or on change).

**Bulk reassign on confirm:**
```ts
// One update per unique replacement (group rows by replacementId)
for (const [replacementId, apptIds] of groupedByReplacement) {
  await supabase
    .from('appointments')
    .update({ assigned_user_id: replacementId })
    .in('id', apptIds)
}
```

---

## Replacement dropdown content
- All active team members in the same business
- Excludes the user being removed
- Uses existing `teamMembers` state already loaded on the page

---

## Dialog copy

**Title:** `"[Name] has [N] upcoming appointment(s)"`  
**Subtitle:** `"Assign a replacement for each before removing. Conflicts are shown in red."`  
**Table columns:** Date & Time | Service | Replacement | Status  
**Primary button:** `"Reassign & Remove"` — disabled until all rows resolved  
**Cancel:** `"Cancel"`

---

## Error handling
- Conflict validation fails (network) → show "Could not validate. Try again." on that row, keep button disabled
- Bulk reassign fails → toast error, keep dialog open (no partial writes if grouped by replacement)
- Remove fails after reassign → toast error. Appointments already reassigned — no data loss, admin can retry remove.

---

## What this does NOT change
- Remove flow with 0 upcoming appointments — unchanged
- Existing AlertDialog confirmation for 0-appointment removal — kept as-is
- Google Calendar events on those appointments — not updated (DB only; GCal sync is future work)
- No new backend endpoints needed — all queries go via Supabase client directly
