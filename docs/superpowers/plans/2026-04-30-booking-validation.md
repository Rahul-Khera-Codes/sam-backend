# Booking Validation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add server-side validation to `get_available_slots` and `book_appointment` so the agent cannot book on closed days, in the past, or outside business hours — regardless of LLM reasoning errors.

**Architecture:** A single `_validate_booking_datetime()` function in `agent/supabase_helpers.py` handles all date/time/hours checks and is called from both agent tools. It returns `None` on success or an error string the agent can speak to the customer. `get_available_slots` gets a lighter guard (past date + business open on that day). `book_appointment` gets the full check plus a double-booking guard.

**Tech Stack:** Python, LiveKit Agents SDK, Supabase Python client, pytest

---

## File Map

| File | Change |
|---|---|
| `agent/supabase_helpers.py` | Add `_validate_booking_datetime()` |
| `agent/agent.py` | Guard `get_available_slots` (past + closed day) and `book_appointment` (full validation + double-booking) |
| `agent/tests/test_booking_validation.py` | New — unit tests for `_validate_booking_datetime` |

---

### Task 1: `_validate_booking_datetime()` in supabase_helpers.py

**Files:**
- Modify: `agent/supabase_helpers.py` (add after `_fetch_business_hours_for_location` at line ~342)
- Test: `agent/tests/test_booking_validation.py` (create new)

**Context:**
- `_fetch_business_hours_for_location(supabase, business_id, location_id)` → returns list of `{day_of_week, open_time, close_time, is_open}` rows. `day_of_week` is lowercase e.g. `"thursday"`.
- `_fetch_active_custom_schedule(supabase, business_id, location_id, now=datetime)` → returns custom schedule dict or `None`. Schema: `is_agent_disabled` (bool), `open_time` (str "HH:MM:SS" or None), `close_time` (str "HH:MM:SS" or None).
- `_fmt_time_12h(t: str) -> str` — converts `"14:30"` → `"2:30 PM"`. Already exists in the file.
- Both are already imported/available — no new imports needed beyond what's at the top of the file (`from datetime import datetime, timezone, timedelta`).

- [ ] **Step 1: Create test file with failing tests**

```bash
mkdir -p agent/tests
touch agent/tests/__init__.py
```

Create `agent/tests/test_booking_validation.py`:

```python
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock
import pytest

# We test _validate_booking_datetime directly after it's implemented.
# Import will fail until Task 1 Step 3 is done — that's expected.
from supabase_helpers import _validate_booking_datetime


def _mock_supabase(hours=None, custom=None):
    """Build a minimal supabase mock that returns preset hours/schedule."""
    sb = MagicMock()
    return sb


# ── Past date ──────────────────────────────────────────────────────────────────

def test_rejects_past_date():
    result = _validate_booking_datetime(
        supabase=None,
        business_id="biz-1",
        location_id="loc-1",
        date="2020-01-01",
        time="10:00",
    )
    assert result is not None
    assert "past" in result.lower()


def test_accepts_today():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with patch("supabase_helpers._fetch_active_custom_schedule", return_value=None), \
         patch("supabase_helpers._fetch_business_hours_for_location", return_value=[
             {"day_of_week": datetime.now(timezone.utc).strftime("%A").lower(),
              "is_open": True, "open_time": "00:00:00", "close_time": "23:59:00"}
         ]):
        result = _validate_booking_datetime(None, "biz", "loc", today, "10:00")
    assert result is None


# ── Invalid formats ────────────────────────────────────────────────────────────

def test_rejects_bad_date_format():
    result = _validate_booking_datetime(None, "b", "l", "30-04-2026", "10:00")
    assert result is not None
    assert "invalid" in result.lower() or "format" in result.lower()


def test_rejects_bad_time_format():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    result = _validate_booking_datetime(None, "b", "l", today, "10am")
    assert result is not None


# ── Business hours ─────────────────────────────────────────────────────────────

def test_rejects_closed_day():
    future = "2099-01-07"  # Monday
    with patch("supabase_helpers._fetch_active_custom_schedule", return_value=None), \
         patch("supabase_helpers._fetch_business_hours_for_location", return_value=[
             {"day_of_week": "monday", "is_open": False, "open_time": None, "close_time": None}
         ]):
        result = _validate_booking_datetime(None, "b", "l", future, "10:00")
    assert result is not None
    assert "closed" in result.lower()


def test_rejects_time_before_open():
    future = "2099-01-07"  # Monday
    with patch("supabase_helpers._fetch_active_custom_schedule", return_value=None), \
         patch("supabase_helpers._fetch_business_hours_for_location", return_value=[
             {"day_of_week": "monday", "is_open": True,
              "open_time": "09:00:00", "close_time": "17:00:00"}
         ]):
        result = _validate_booking_datetime(None, "b", "l", future, "08:00")
    assert result is not None
    assert "outside" in result.lower() or "hours" in result.lower()


def test_rejects_time_after_close():
    future = "2099-01-07"  # Monday
    with patch("supabase_helpers._fetch_active_custom_schedule", return_value=None), \
         patch("supabase_helpers._fetch_business_hours_for_location", return_value=[
             {"day_of_week": "monday", "is_open": True,
              "open_time": "09:00:00", "close_time": "17:00:00"}
         ]):
        result = _validate_booking_datetime(None, "b", "l", future, "17:00")
    assert result is not None


def test_accepts_valid_time_within_hours():
    future = "2099-01-07"  # Monday
    with patch("supabase_helpers._fetch_active_custom_schedule", return_value=None), \
         patch("supabase_helpers._fetch_business_hours_for_location", return_value=[
             {"day_of_week": "monday", "is_open": True,
              "open_time": "09:00:00", "close_time": "17:00:00"}
         ]):
        result = _validate_booking_datetime(None, "b", "l", future, "10:30")
    assert result is None


# ── Custom schedule ────────────────────────────────────────────────────────────

def test_rejects_custom_schedule_agent_disabled():
    future = "2099-01-07"
    with patch("supabase_helpers._fetch_active_custom_schedule", return_value={
        "is_agent_disabled": True, "open_time": None, "close_time": None
    }):
        result = _validate_booking_datetime(None, "b", "l", future, "10:00")
    assert result is not None
    assert "closed" in result.lower() or "special" in result.lower()


def test_custom_schedule_overrides_regular_hours():
    future = "2099-01-07"
    # Regular hours say closed, but custom schedule opens 08:00–20:00
    with patch("supabase_helpers._fetch_active_custom_schedule", return_value={
        "is_agent_disabled": False,
        "open_time": "08:00:00",
        "close_time": "20:00:00",
    }), patch("supabase_helpers._fetch_business_hours_for_location", return_value=[
        {"day_of_week": "monday", "is_open": False, "open_time": None, "close_time": None}
    ]):
        result = _validate_booking_datetime(None, "b", "l", future, "10:00")
    assert result is None


def test_custom_schedule_rejects_outside_special_hours():
    future = "2099-01-07"
    with patch("supabase_helpers._fetch_active_custom_schedule", return_value={
        "is_agent_disabled": False,
        "open_time": "08:00:00",
        "close_time": "12:00:00",
    }):
        result = _validate_booking_datetime(None, "b", "l", future, "14:00")
    assert result is not None
    assert "outside" in result.lower() or "hours" in result.lower()
```

- [ ] **Step 2: Run tests to confirm they fail (import error expected)**

```bash
cd agent && python -m pytest tests/test_booking_validation.py -v 2>&1 | head -20
```

Expected: `ImportError: cannot import name '_validate_booking_datetime'`

- [ ] **Step 3: Add `_validate_booking_datetime` to supabase_helpers.py**

Insert after the `_fetch_business_hours_for_location` function (after line ~342 in `agent/supabase_helpers.py`):

```python
def _validate_booking_datetime(
    supabase,
    business_id: str,
    location_id: str | None,
    date: str,
    time: str,
) -> str | None:
    """
    Returns None if the date/time is valid for booking.
    Returns an error string (agent-readable) if not.
    Checks: date not in past, valid formats, business open on that day,
    time within open/close hours, custom schedule overrides.
    """
    # 1. Parse date
    try:
        appt_date = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        return f"Invalid date format '{date}'. Please use YYYY-MM-DD."

    today = datetime.now(timezone.utc).date()
    if appt_date < today:
        return (
            f"Cannot book appointments in the past. "
            f"Today is {today.strftime('%Y-%m-%d')}."
        )

    # 2. Parse time
    try:
        appt_time = datetime.strptime(time[:5], "%H:%M").time()
    except ValueError:
        return f"Invalid time format '{time}'. Please use HH:MM (24-hour)."

    day_names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    day_name = day_names[appt_date.weekday()]

    # 3. Check custom schedule first (takes priority over regular hours)
    appt_dt = datetime(
        appt_date.year, appt_date.month, appt_date.day, tzinfo=timezone.utc
    )
    custom = _fetch_active_custom_schedule(
        supabase, business_id, location_id, now=appt_dt
    )
    if custom is not None:
        if custom.get("is_agent_disabled"):
            return (
                f"The business is closed on {date} due to a special schedule. "
                f"Please choose a different date."
            )
        open_t = (custom.get("open_time") or "")[:5]
        close_t = (custom.get("close_time") or "")[:5]
        if open_t and close_t:
            try:
                open_time = datetime.strptime(open_t, "%H:%M").time()
                close_time = datetime.strptime(close_t, "%H:%M").time()
                if appt_time < open_time or appt_time >= close_time:
                    return (
                        f"The time {_fmt_time_12h(time[:5])} is outside the special "
                        f"schedule hours ({_fmt_time_12h(open_t)}–{_fmt_time_12h(close_t)}) "
                        f"for {date}."
                    )
            except ValueError:
                pass
        return None  # Custom schedule valid, skip regular hours check

    # 4. Regular business hours
    if supabase and business_id:
        hours = _fetch_business_hours_for_location(supabase, business_id, location_id)
        day_hours = next(
            (h for h in hours if h.get("day_of_week") == day_name), None
        )
        if day_hours is not None and not day_hours.get("is_open"):
            return (
                f"The business is closed on {day_name.capitalize()}s. "
                f"Please choose a day when the business is open."
            )
        if day_hours:
            open_t = (day_hours.get("open_time") or "")[:5]
            close_t = (day_hours.get("close_time") or "")[:5]
            if open_t and close_t:
                try:
                    open_time = datetime.strptime(open_t, "%H:%M").time()
                    close_time = datetime.strptime(close_t, "%H:%M").time()
                    if appt_time < open_time or appt_time >= close_time:
                        return (
                            f"The time {_fmt_time_12h(time[:5])} is outside business hours "
                            f"({_fmt_time_12h(open_t)}–{_fmt_time_12h(close_t)}) "
                            f"on {day_name.capitalize()}s."
                        )
                except ValueError:
                    pass

    return None
```

- [ ] **Step 4: Run tests — all should pass**

```bash
cd agent && python -m pytest tests/test_booking_validation.py -v
```

Expected output:
```
test_rejects_past_date PASSED
test_accepts_today PASSED
test_rejects_bad_date_format PASSED
test_rejects_bad_time_format PASSED
test_rejects_closed_day PASSED
test_rejects_time_before_open PASSED
test_rejects_time_after_close PASSED
test_accepts_valid_time_within_hours PASSED
test_rejects_custom_schedule_agent_disabled PASSED
test_custom_schedule_overrides_regular_hours PASSED
test_custom_schedule_rejects_outside_special_hours PASSED
11 passed
```

- [ ] **Step 5: Commit**

```bash
git add agent/supabase_helpers.py agent/tests/__init__.py agent/tests/test_booking_validation.py
git commit -m "feat: add _validate_booking_datetime to supabase_helpers"
```

---

### Task 2: Guard `get_available_slots` in agent.py

**Files:**
- Modify: `agent/agent.py` — `get_available_slots` method starting at line ~311

**Context:**
`get_available_slots` currently:
1. Resolves staff from `staff_name`
2. Calls `_compute_available_slots(availability, overrides, booked, date, slot_minutes)` — uses staff's personal `user_availability` table, NOT business hours
3. Returns available slots as a string

The bug: if the business is closed on Thursday but a staff member has Thursday configured in their personal availability, the tool still returns slots. We need to check business hours first.

For this tool, we only need a partial validation (no time check, since we're listing all slots for the day):
- Reject past dates
- Reject if business is closed on that day (regular hours or custom schedule)

- [ ] **Step 1: Write the failing test**

Add to `agent/tests/test_booking_validation.py`:

```python
# ── get_available_slots business-hours guard ───────────────────────────────────
# These are integration-level tests that verify agent.py returns the right
# string when business is closed. We call the tool method directly.

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from unittest.mock import patch, MagicMock, AsyncMock
import asyncio


def _make_agent(business_id="biz-1", location_id="loc-1"):
    """Build a minimal VoiceAgent instance with mocked supabase."""
    from agent import VoiceAgent  # adjust if class name differs
    agent = object.__new__(VoiceAgent)
    agent._supabase = MagicMock()
    agent._business_id = business_id
    agent._location_id = location_id
    agent._business_name = "Test Biz"
    agent._business_phone = ""
    agent._call_id = None
    agent._services = []
    agent._staff = [{"name": "Alice", "user_id": "u1", "role": "user"}]
    agent._locations = [{"id": location_id, "name": "Main"}]
    return agent


def test_get_available_slots_rejects_closed_day():
    agent = _make_agent()
    # Make _validate_booking_datetime return a closed message
    with patch("supabase_helpers._validate_booking_datetime",
               return_value="The business is closed on Thursdays."):
        result = asyncio.get_event_loop().run_until_complete(
            agent.get_available_slots.__wrapped__(agent, MagicMock(), "Alice", "2099-01-10", "")
        )
    assert "closed" in result.lower()


def test_get_available_slots_rejects_past_date():
    agent = _make_agent()
    with patch("supabase_helpers._validate_booking_datetime",
               return_value="Cannot book appointments in the past."):
        result = asyncio.get_event_loop().run_until_complete(
            agent.get_available_slots.__wrapped__(agent, MagicMock(), "Alice", "2020-01-01", "")
        )
    assert "past" in result.lower()
```

- [ ] **Step 2: Run the new tests to confirm they fail**

```bash
cd agent && python -m pytest tests/test_booking_validation.py::test_get_available_slots_rejects_closed_day tests/test_booking_validation.py::test_get_available_slots_rejects_past_date -v
```

Expected: FAIL (guard not yet added)

- [ ] **Step 3: Add the guard to `get_available_slots` in agent.py**

In `agent/agent.py`, find `get_available_slots` (around line 311). Insert validation right after the staff-not-found guard:

**Before (existing code at ~line 327):**
```python
        staff = self._resolve_staff(staff_name)
        if not staff:
            return f"Staff member '{staff_name}' not found."

        slot_minutes = 60
```

**After (with guard added):**
```python
        staff = self._resolve_staff(staff_name)
        if not staff:
            return f"Staff member '{staff_name}' not found."

        # Validate date and business hours before computing slots
        date_err = _validate_booking_datetime(
            self._supabase, self._business_id, self._location_id, date, "00:00"
        )
        if date_err:
            return date_err

        slot_minutes = 60
```

Note: We pass `"00:00"` for time because we only want the date/closed-day checks here — time-of-day filtering is handled by staff availability within `_compute_available_slots`.

Make sure `_validate_booking_datetime` is imported at the top of `agent.py`. It lives in `supabase_helpers.py`. Check how other helpers are imported — likely a `from supabase_helpers import ...` line. Add `_validate_booking_datetime` to that import.

- [ ] **Step 4: Run the new tests — should pass**

```bash
cd agent && python -m pytest tests/test_booking_validation.py -v
```

Expected: all 13 tests pass.

- [ ] **Step 5: Commit**

```bash
git add agent/agent.py agent/tests/test_booking_validation.py
git commit -m "feat: guard get_available_slots with business hours validation"
```

---

### Task 3: Guard `book_appointment` in agent.py

**Files:**
- Modify: `agent/agent.py` — `book_appointment` method starting at line ~352

**Context:**
`book_appointment` currently jumps straight from resolving staff/location/service to building the DB row and inserting. We need two guards before the insert:
1. **`_validate_booking_datetime`** — full check (past date, business hours, custom schedule, time within hours)
2. **Double-booking check** — if that exact time is already booked for the staff member, reject with a clear message

`_fetch_appointments_on_date(supabase, user_id, date)` already exists in `supabase_helpers.py` and is used by `get_available_slots`. It returns a list of appointment dicts with `appointment_time` (str "HH:MM:SS") and `duration`.

- [ ] **Step 1: Write the failing tests**

Add to `agent/tests/test_booking_validation.py`:

```python
def test_book_appointment_rejects_closed_day():
    agent = _make_agent()
    with patch("supabase_helpers._validate_booking_datetime",
               return_value="The business is closed on Thursdays."):
        result = asyncio.get_event_loop().run_until_complete(
            agent.book_appointment.__wrapped__(
                agent, MagicMock(),
                client_name="John", client_phone="+10000000000",
                client_email="john@example.com", service_name="Haircut",
                staff_name="Alice", location_name="Main",
                date="2099-01-10", time="10:00",
            )
        )
    assert "closed" in result.lower()


def test_book_appointment_rejects_double_booking():
    agent = _make_agent()
    with patch("supabase_helpers._validate_booking_datetime", return_value=None), \
         patch("supabase_helpers._fetch_appointments_on_date", return_value=[
             {"appointment_time": "10:00:00", "duration": "60"}
         ]):
        result = asyncio.get_event_loop().run_until_complete(
            agent.book_appointment.__wrapped__(
                agent, MagicMock(),
                client_name="John", client_phone="+10000000000",
                client_email="john@example.com", service_name="Haircut",
                staff_name="Alice", location_name="Main",
                date="2099-01-07", time="10:00",
            )
        )
    assert "already booked" in result.lower() or "not available" in result.lower()
```

- [ ] **Step 2: Run to confirm they fail**

```bash
cd agent && python -m pytest tests/test_booking_validation.py::test_book_appointment_rejects_closed_day tests/test_booking_validation.py::test_book_appointment_rejects_double_booking -v
```

Expected: FAIL

- [ ] **Step 3: Add guards to `book_appointment` in agent.py**

In `agent/agent.py`, find `book_appointment`. The existing early-exit block starts at ~line 371:

```python
        if not self._supabase or not self._business_id:
            return "Booking is unavailable right now. Please call back or book in person."
```

Add the two guards immediately after the staff/location/service resolution block (after `service_label = ...`, before `combined_notes = ...`). The exact block to find:

```python
        duration_str = str(svc["duration_minutes"]) if svc and svc.get("duration_minutes") else "60"
        service_label = svc["name"] if svc else service_name
        location_label = loc["name"] if loc else location_name

        combined_notes = notes or ""
```

Replace with:

```python
        duration_str = str(svc["duration_minutes"]) if svc and svc.get("duration_minutes") else "60"
        service_label = svc["name"] if svc else service_name
        location_label = loc["name"] if loc else location_name

        # Guard 1: date/time/business-hours validation
        booking_location_id = (loc["id"] if loc else None) or self._location_id
        date_err = _validate_booking_datetime(
            self._supabase, self._business_id, booking_location_id, date, time
        )
        if date_err:
            return date_err

        # Guard 2: double-booking — slot already taken for this staff member
        existing = _fetch_appointments_on_date(self._supabase, staff["user_id"], date)
        for appt in existing:
            if (appt.get("appointment_time") or "")[:5] == time[:5]:
                return (
                    f"{staff['name']} is not available at {_fmt_time_12h(time[:5])} on {date}. "
                    f"Please choose a different time slot."
                )

        combined_notes = notes or ""
```

Make sure `_fetch_appointments_on_date` and `_validate_booking_datetime` are both in the `from supabase_helpers import ...` line at the top of `agent.py`.

- [ ] **Step 4: Run all tests**

```bash
cd agent && python -m pytest tests/test_booking_validation.py -v
```

Expected: all 15 tests pass.

- [ ] **Step 5: Restart the agent and do a manual smoke test**

```bash
docker compose restart sam-agent
docker logs -f sam-backend-sam-agent-1
```

Try booking: call the agent, ask for an appointment on a closed day — it should say the business is closed. Ask for a valid open day/time — booking should succeed as before.

- [ ] **Step 6: Commit**

```bash
git add agent/agent.py agent/tests/test_booking_validation.py
git commit -m "feat: guard book_appointment with hours validation and double-booking check"
```

---

## Self-Review

**Spec coverage:**
- ✅ Cannot book on closed days (business_hours `is_open = false`) — Task 1 + 2 + 3
- ✅ Cannot book in the past — Task 1 + 2 + 3
- ✅ Cannot book outside open/close hours — Task 1 + 3
- ✅ Custom schedule override: `is_agent_disabled` → closed, custom hours → enforced — Task 1 + 3
- ✅ Double-booking guard — Task 3
- ✅ `get_available_slots` won't show slots on closed days — Task 2
- ✅ Error messages are agent-readable (agent speaks them to customer) — throughout

**Placeholder scan:** None found.

**Type consistency:** `_validate_booking_datetime` returns `str | None` — used as `if date_err: return date_err` in both tools — consistent.
