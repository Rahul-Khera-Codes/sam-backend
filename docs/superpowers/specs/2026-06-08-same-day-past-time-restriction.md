# Spec: Block Same-Day Appointments Before Current Time

**Date:** 2026-06-08  
**Requested by:** Sam Maisuria (message 2026-06-08)  
**Status:** Ready to implement

---

## Problem

If a caller rings at 11:00 AM, the agent can currently suggest or accept bookings for earlier same-day slots (e.g. 9:00 AM, 10:00 AM). These times have already passed and cannot be fulfilled.

---

## Desired Behaviour

For same-day bookings only:
- Available slot lists must exclude any slot that starts at or before the current time
- Booking validation must reject a time that has already passed today
- The agent prompt must explicitly instruct the LLM not to suggest or accept past times on the same day

---

## Files to Change

### 1. `agent/supabase_helpers.py` — `_compute_available_slots`

After building the busy list, before generating slots, compute a cutoff for today:

```python
# If target_date is today (UTC), exclude slots at or before current time
now_cutoff: datetime | None = None
today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
if target_date == today_str:
    _now = datetime.now(timezone.utc)
    now_cutoff = datetime(1900, 1, 1, _now.hour, _now.minute)
```

In the slot generation loop, skip slots where `current <= now_cutoff`:

```python
while current + timedelta(minutes=slot_minutes) <= work_end:
    slot_end = current + timedelta(minutes=slot_minutes)
    if now_cutoff is not None and current <= now_cutoff:
        current += timedelta(minutes=slot_minutes)
        continue
    if not any(current < b_end and slot_end > b_start for b_start, b_end in busy):
        slots.append(current.strftime("%H:%M"))
    current += timedelta(minutes=slot_minutes)
```

**Note:** `now_cutoff` uses `datetime(1900,1,1,...)` to match the naive datetime format already used for `work_start`/`work_end` in this function.

### 2. `agent/supabase_helpers.py` — `_validate_booking_datetime`

After the existing "date is in the past" check, add same-day time check:

```python
# Reject same-day bookings at or before the current time
if appt_date == today and appt_time is not None:
    current_time = datetime.now(timezone.utc).time()
    if appt_time <= current_time:
        return (
            f"Cannot book at {_fmt_time_12h(time[:5])} — "
            f"that time has already passed today. "
            f"Please choose a time after {_fmt_time_12h(current_time.strftime('%H:%M'))}."
        )
```

### 3. `agent/prompt_builder.py` — `DEFAULT_INSTRUCTIONS`

Add one line to the General rules section:

```
- For same-day appointments, never suggest or accept a time at or before the current time.
  The availability tools automatically exclude past slots for today — always trust their results.
```

---

## Coverage

| Path | Fixed by |
|---|---|
| `find_next_available_slot` tool | `_compute_available_slots` fix |
| `get_available_slots` tool | `_compute_available_slots` fix |
| `book_appointment` tool | `_validate_booking_datetime` fix |
| `reschedule_appointment` tool | `_validate_booking_datetime` fix |
| LLM inventing a time without tools | prompt rule |

---

## What does NOT change

- Booking validation for future dates — unchanged
- Slot generation for future dates — unchanged
- Timezone handling — UTC throughout, consistent with rest of system

---

## No new packages needed
`datetime`, `timedelta`, `timezone` already imported in `supabase_helpers.py`.
