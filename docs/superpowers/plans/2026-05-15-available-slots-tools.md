# Available Slots Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the broken `get_available_slots` tool, add a new `find_next_available_slot` tool that scans forward to proactively offer options, and update the agent prompt to use it intelligently.

**Architecture:** Three changes to the agent codebase only — no backend, no frontend, no DB migrations. (1) A new `_validate_booking_date` helper in `supabase_helpers.py` that validates date-only (no time check). (2) A new `_find_next_slots` helper that scans forward N days. (3) A new `find_next_available_slot` agent tool. (4) Updated `DEFAULT_INSTRUCTIONS` so the agent uses the new tool proactively instead of asking the caller to guess a date.

**Tech Stack:** Python, LiveKit Agents, supabase-py, pytest

---

## File Map

**Modify:**
- `agent/supabase_helpers.py` — add `_validate_booking_date` + `_find_next_slots`
- `agent/agent.py` — fix `get_available_slots` + add `find_next_available_slot` tool
- `agent/prompt_builder.py` — update `DEFAULT_INSTRUCTIONS`

**Modify (tests):**
- `agent/tests/test_booking_validation.py` — add tests for `_validate_booking_date` + `_find_next_slots`

---

## Task 1: Add `_validate_booking_date` helper (date-only validation)

**Files:**
- Modify: `agent/supabase_helpers.py` (after `_validate_booking_datetime`, around line 428)
- Modify: `agent/tests/test_booking_validation.py`

### Context

`_validate_booking_datetime` checks both the date AND whether a specific time falls within business hours. `get_available_slots` only needs to know "is this day open at all?" — not whether a specific time is valid. Passing `"00:00"` as the time causes the time-range check to fail for any normal business (which opens at 9am, not midnight), breaking the tool.

The new helper `_validate_booking_date` does everything `_validate_booking_datetime` does **except** the time-range check. It returns `None` if the date is valid, or an error string if not.

- [ ] **Step 1: Write failing tests**

Add to `agent/tests/test_booking_validation.py`:

```python
from supabase_helpers import _validate_booking_date


def test_validate_booking_date_rejects_past():
    result = _validate_booking_date(None, "biz-1", "loc-1", "2020-01-01")
    assert result is not None
    assert "past" in result.lower()


def test_validate_booking_date_rejects_bad_format():
    result = _validate_booking_date(None, "b", "l", "20-05-2026")
    assert result is not None
    assert "format" in result.lower()


def test_validate_booking_date_accepts_open_day():
    future_monday = _future_date(0)
    with patch("supabase_helpers._fetch_active_custom_schedule", return_value=None), \
         patch("supabase_helpers._fetch_business_hours_for_location", return_value=[
             {"day_of_week": "monday", "is_open": True,
              "open_time": "09:00:00", "close_time": "17:00:00"}
         ]):
        result = _validate_booking_date(None, "biz", "loc", future_monday)
    assert result is None


def test_validate_booking_date_rejects_closed_day():
    future_monday = _future_date(0)
    with patch("supabase_helpers._fetch_active_custom_schedule", return_value=None), \
         patch("supabase_helpers._fetch_business_hours_for_location", return_value=[
             {"day_of_week": "monday", "is_open": False,
              "open_time": None, "close_time": None}
         ]):
        result = _validate_booking_date(None, "biz", "loc", future_monday)
    assert result is not None
    assert "closed" in result.lower()


def test_validate_booking_date_rejects_agent_disabled_schedule():
    future_monday = _future_date(0)
    with patch("supabase_helpers._fetch_active_custom_schedule",
               return_value={"is_agent_disabled": True}):
        result = _validate_booking_date(None, "biz", "loc", future_monday)
    assert result is not None
    assert "closed" in result.lower()


def test_validate_booking_date_accepts_custom_schedule_with_hours():
    """A custom schedule with open hours should be valid regardless of the time."""
    future_monday = _future_date(0)
    with patch("supabase_helpers._fetch_active_custom_schedule",
               return_value={"is_agent_disabled": False,
                             "open_time": "10:00", "close_time": "15:00"}):
        result = _validate_booking_date(None, "biz", "loc", future_monday)
    assert result is None


def test_validate_booking_date_does_not_check_time():
    """Key difference: even if it were midnight, date-only validation should pass for an open day."""
    future_monday = _future_date(0)
    with patch("supabase_helpers._fetch_active_custom_schedule", return_value=None), \
         patch("supabase_helpers._fetch_business_hours_for_location", return_value=[
             {"day_of_week": "monday", "is_open": True,
              "open_time": "09:00:00", "close_time": "17:00:00"}
         ]):
        # No time argument at all — should still pass
        result = _validate_booking_date(None, "biz", "loc", future_monday)
    assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/lap-68/Documents/gt-rahul/sam-backend/agent
source ../venv/sam-backend/bin/activate
python -m pytest tests/test_booking_validation.py -k "validate_booking_date" -v 2>&1 | tail -20
```
Expected: `ImportError` or `AttributeError: module 'supabase_helpers' has no attribute '_validate_booking_date'`

- [ ] **Step 3: Add `_validate_booking_date` to `supabase_helpers.py`**

Add after `_validate_booking_datetime` (after line 427):

```python
def _validate_booking_date(
    supabase,
    business_id: str,
    location_id: str | None,
    date: str,
) -> str | None:
    """
    Returns None if the date is valid for booking (not past, business open that day).
    Returns an agent-readable error string if not.
    Unlike _validate_booking_datetime, does NOT check whether a specific time is within hours.
    Use this when you need to know if a day is bookable without a specific time in mind.
    """
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

    day_names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    day_name = day_names[appt_date.weekday()]

    appt_dt = datetime(appt_date.year, appt_date.month, appt_date.day, tzinfo=timezone.utc)
    custom = _fetch_active_custom_schedule(supabase, business_id, location_id, now=appt_dt)
    if custom is not None:
        if custom.get("is_agent_disabled"):
            return (
                f"The business is closed on {date} due to a special schedule. "
                f"Please choose a different date."
            )
        return None  # custom schedule exists and agent is not disabled — day is valid

    hours = _fetch_business_hours_for_location(supabase, business_id, location_id)
    day_hours = next((h for h in hours if h.get("day_of_week") == day_name), None)
    if day_hours is not None and not day_hours.get("is_open"):
        return (
            f"The business is closed on {day_name.capitalize()}s. "
            f"Please choose a day when the business is open."
        )

    return None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_booking_validation.py -k "validate_booking_date" -v 2>&1 | tail -20
```
Expected: all 7 new tests PASS

- [ ] **Step 5: Commit**

```bash
cd /home/lap-68/Documents/gt-rahul/sam-backend
git add agent/supabase_helpers.py agent/tests/test_booking_validation.py
git commit -m "feat: add _validate_booking_date helper for date-only validation (no time check)"
```

---

## Task 2: Fix `get_available_slots` to use `_validate_booking_date`

**Files:**
- Modify: `agent/agent.py:332–337`
- Modify: `agent/tests/test_booking_validation.py`

### Context

`get_available_slots` currently calls `_validate_booking_datetime(... "00:00")`. Passing midnight fails the time-range check for any normal business. The fix is a one-line change: use `_validate_booking_date` instead, which only checks that the day itself is open.

- [ ] **Step 1: Write a regression test**

Add to `agent/tests/test_booking_validation.py`:

```python
def test_validate_booking_date_passes_for_open_day_regardless_of_time():
    """
    Regression: get_available_slots was broken because it passed "00:00" to
    _validate_booking_datetime which rejected midnight as outside business hours.
    _validate_booking_date must not have this problem.
    """
    future_monday = _future_date(0)
    with patch("supabase_helpers._fetch_active_custom_schedule", return_value=None), \
         patch("supabase_helpers._fetch_business_hours_for_location", return_value=[
             {"day_of_week": "monday", "is_open": True,
              "open_time": "09:00:00", "close_time": "17:00:00"}
         ]):
        # Would have failed with _validate_booking_datetime("00:00") — must pass with date-only
        result = _validate_booking_date(None, "biz", "loc", future_monday)
    assert result is None, f"Expected None but got: {result}"
```

- [ ] **Step 2: Run test to confirm it passes (it should, validating Task 1 was correct)**

```bash
cd /home/lap-68/Documents/gt-rahul/sam-backend/agent
python -m pytest tests/test_booking_validation.py::test_validate_booking_date_passes_for_open_day_regardless_of_time -v
```
Expected: PASS

- [ ] **Step 3: Fix the import in agent.py**

In `agent/agent.py`, find the import block that includes `_validate_booking_datetime`. Add `_validate_booking_date` to the same import:

```python
from supabase_helpers import (
    ...
    _validate_booking_datetime,
    _validate_booking_date,
    ...
)
```

- [ ] **Step 4: Replace the broken call in `get_available_slots`**

In `agent/agent.py`, find lines 332–337:

```python
        # Reject past dates and closed days before computing slots
        date_err = _validate_booking_datetime(
            self._supabase, self._business_id, self._location_id, date, "00:00"
        )
        if date_err:
            return date_err
```

Replace with:

```python
        # Reject past dates and closed days before computing slots (no time check needed)
        date_err = _validate_booking_date(
            self._supabase, self._business_id, self._location_id, date
        )
        if date_err:
            return date_err
```

- [ ] **Step 5: Verify syntax**

```bash
cd /home/lap-68/Documents/gt-rahul/sam-backend
python -c "import ast; ast.parse(open('agent/agent.py').read()); print('OK')"
```
Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add agent/agent.py agent/tests/test_booking_validation.py
git commit -m "fix: use _validate_booking_date in get_available_slots to stop rejecting midnight"
```

---

## Task 3: Add `_find_next_slots` helper to `supabase_helpers.py`

**Files:**
- Modify: `agent/supabase_helpers.py`
- Modify: `agent/tests/test_booking_validation.py`

### Context

This helper scans forward day by day from a start date, skipping closed days, and returns the first date that has any available slots. It returns a list of `{"date", "time", "staff_name", "staff_user_id"}` dicts so the agent can present concrete options to the caller.

It takes `user_entries` (list of `{"user_id": str, "name": str}`) so it works for both a specific staff member and any-staff searches.

- [ ] **Step 1: Write failing tests**

Add to `agent/tests/test_booking_validation.py`:

```python
from supabase_helpers import _find_next_slots
from datetime import date as date_cls


def test_find_next_slots_returns_empty_when_all_days_closed():
    """If all days are closed, returns empty list."""
    with patch("supabase_helpers._validate_booking_date", return_value="closed"), \
         patch("supabase_helpers._fetch_user_availability", return_value=[]):
        result = _find_next_slots(
            supabase=None,
            business_id="biz",
            location_id="loc",
            user_entries=[{"user_id": "u1", "name": "Rahul"}],
            slot_minutes=60,
            from_date="2099-01-06",  # Monday in far future
            max_days=5,
        )
    assert result == []


def test_find_next_slots_skips_closed_days_and_finds_open():
    """Skips a closed Monday and finds slots on Tuesday."""
    monday = _future_date(0)
    tuesday = (datetime.strptime(monday, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")

    def date_validator(supabase, business_id, location_id, date):
        return "closed" if date == monday else None

    with patch("supabase_helpers._validate_booking_date", side_effect=date_validator), \
         patch("supabase_helpers._fetch_user_availability", return_value=[
             {"day_of_week": "tuesday", "is_available": True,
              "start_time": "09:00", "end_time": "17:00"}
         ]), \
         patch("supabase_helpers._fetch_user_overrides", return_value=[]), \
         patch("supabase_helpers._fetch_appointments_on_date", return_value=[]):
        result = _find_next_slots(
            supabase=None,
            business_id="biz",
            location_id="loc",
            user_entries=[{"user_id": "u1", "name": "Rahul"}],
            slot_minutes=60,
            from_date=monday,
            max_days=5,
        )

    assert len(result) > 0
    assert all(r["date"] == tuesday for r in result)
    assert all(r["staff_name"] == "Rahul" for r in result)


def test_find_next_slots_returns_max_3_per_staff():
    """Returns at most 3 slots per staff member per day."""
    future_monday = _future_date(0)

    with patch("supabase_helpers._validate_booking_date", return_value=None), \
         patch("supabase_helpers._fetch_user_availability", return_value=[
             {"day_of_week": "monday", "is_available": True,
              "start_time": "09:00", "end_time": "17:00"}
         ]), \
         patch("supabase_helpers._fetch_user_overrides", return_value=[]), \
         patch("supabase_helpers._fetch_appointments_on_date", return_value=[]):
        result = _find_next_slots(
            supabase=None,
            business_id="biz",
            location_id="loc",
            user_entries=[{"user_id": "u1", "name": "Rahul"}],
            slot_minutes=60,
            from_date=future_monday,
            max_days=5,
        )

    # Should have at most 3 slots for "Rahul" (9-17 with 60min slots = 8 slots, capped at 3)
    rahul_slots = [r for r in result if r["staff_name"] == "Rahul"]
    assert 1 <= len(rahul_slots) <= 3
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/lap-68/Documents/gt-rahul/sam-backend/agent
python -m pytest tests/test_booking_validation.py -k "find_next_slots" -v 2>&1 | tail -10
```
Expected: `ImportError` or `AttributeError`

- [ ] **Step 3: Add `_find_next_slots` to `supabase_helpers.py`**

Add after `_validate_booking_date`:

```python
def _find_next_slots(
    supabase,
    business_id: str,
    location_id: str | None,
    user_entries: list[dict],
    slot_minutes: int,
    from_date: str,
    max_days: int = 30,
) -> list[dict]:
    """
    Scan forward from from_date (YYYY-MM-DD) for the next day that has available slots.
    user_entries: list of {"user_id": str, "name": str}
    Returns list of {"date": str, "time": str, "staff_name": str, "staff_user_id": str}.
    Returns at most 3 slots per staff member for the first available day.
    Returns [] if no availability found within max_days.
    """
    try:
        start = datetime.strptime(from_date, "%Y-%m-%d").date()
    except ValueError:
        return []

    today = datetime.now(timezone.utc).date()
    if start < today:
        start = today

    for i in range(max_days):
        check_date = start + timedelta(days=i)
        date_str = check_date.strftime("%Y-%m-%d")

        if _validate_booking_date(supabase, business_id, location_id, date_str):
            continue  # closed day — skip

        day_slots: list[dict] = []
        for entry in user_entries:
            user_id = entry["user_id"]
            name = entry["name"]
            try:
                availability = _fetch_user_availability(supabase, user_id)
                overrides = _fetch_user_overrides(supabase, user_id, date_str)
                booked = _fetch_appointments_on_date(supabase, user_id, date_str)
                slots = _compute_available_slots(
                    availability, overrides, booked, date_str, slot_minutes
                )
                for slot in slots[:3]:  # cap at 3 per staff member
                    day_slots.append({
                        "date": date_str,
                        "time": slot,
                        "staff_name": name,
                        "staff_user_id": user_id,
                    })
            except Exception as e:
                logger.warning("_find_next_slots: error for user %s on %s: %s", user_id, date_str, e)
                continue

        if day_slots:
            return day_slots  # return first day that has any slots

    return []
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_booking_validation.py -k "find_next_slots" -v 2>&1 | tail -15
```
Expected: all 3 tests PASS

- [ ] **Step 5: Run the full test suite to check no regressions**

```bash
python -m pytest tests/test_booking_validation.py -v 2>&1 | tail -20
```
Expected: all tests PASS

- [ ] **Step 6: Commit**

```bash
cd /home/lap-68/Documents/gt-rahul/sam-backend
git add agent/supabase_helpers.py agent/tests/test_booking_validation.py
git commit -m "feat: add _find_next_slots helper for proactive slot scanning"
```

---

## Task 4: Add `find_next_available_slot` tool to `agent.py`

**Files:**
- Modify: `agent/agent.py` — add import + new `@function_tool()`

### Context

The new tool gives the agent the ability to answer "when is the next available?" without forcing the caller to guess a date. It lives between `get_available_slots` and `book_appointment` in the file. The tool uses `_find_next_slots` and formats the result as a human-readable string the agent can speak.

- [ ] **Step 1: Add `_find_next_slots` and `_validate_booking_date` to the import block**

In `agent/agent.py`, find the `from supabase_helpers import (` block and add both new names. The full import list after this change:

```python
from supabase_helpers import (
    _fetch_business_hours_for_location,
    _fetch_active_custom_schedule,
    _fetch_locations,
    _fetch_business,
    _fetch_staff_with_ids,
    _fetch_user_service_ids,
    _fetch_services_for_location,
    _fetch_knowledge_base_for_location,
    _fetch_forwarding_contacts,
    _is_feature_enabled_for_location,
    _get_feature_config_value,
    _fetch_user_availability,
    _fetch_user_overrides,
    _fetch_appointments_on_date,
    _compute_available_slots,
    _validate_booking_datetime,
    _validate_booking_date,
    _find_next_slots,
    _fmt_time_12h,
)
```

Read the existing import block first and add only the two new names to avoid overwriting others.

- [ ] **Step 2: Add the new tool after `get_available_slots` (after line 357)**

```python
    @function_tool()
    async def find_next_available_slot(
        self,
        context: RunContext,
        service_name: str,
        staff_name: str = "",
        from_date: str = "",
    ) -> str:
        """
        Find the next available appointment slot, scanning forward from today (or from_date).
        Use this proactively when a caller asks "when is next available?", "when can I book?",
        or "who is free soonest?" — do NOT ask the caller to pick a date first.
        If staff_name is given, searches only that person.
        If staff_name is empty, searches all staff qualified for the service.
        from_date is optional YYYY-MM-DD; defaults to today.
        """
        if not self._supabase:
            return "Availability check is unavailable right now."

        # Resolve service for slot duration
        slot_minutes = 60
        svc = self._resolve_service(service_name) if service_name else None
        if svc and svc.get("duration_minutes"):
            slot_minutes = svc["duration_minutes"]

        # Build the list of staff to search
        if staff_name:
            staff = self._resolve_staff(staff_name)
            if not staff:
                return f"Staff member '{staff_name}' not found."
            user_entries = [{"user_id": staff["user_id"], "name": staff["name"]}]
        else:
            # All staff at this location who offer the service
            service_id = svc.get("id") if svc else None
            candidates = []
            for s in self._staff:
                if not s.get("user_id"):
                    continue
                if service_id:
                    offered = self._user_service_ids.get(s["user_id"], [])
                    if service_id not in offered:
                        continue
                candidates.append({"user_id": s["user_id"], "name": s["name"]})
            if not candidates:
                service_label = svc["name"] if svc else service_name
                return f"No staff at this location offer {service_label}."
            user_entries = candidates

        start = from_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")

        slots = _find_next_slots(
            supabase=self._supabase,
            business_id=self._business_id,
            location_id=self._location_id,
            user_entries=user_entries,
            slot_minutes=slot_minutes,
            from_date=start,
            max_days=30,
        )

        if not slots:
            search_desc = f"with {staff_name}" if staff_name else "with any available staff"
            return (
                f"I couldn't find any available slots {search_desc} "
                f"in the next 30 days. You may want to call back or check with the team directly."
            )

        # Group by staff name for a natural response
        by_staff: dict[str, list[str]] = {}
        date_str = slots[0]["date"]
        for s in slots:
            by_staff.setdefault(s["staff_name"], []).append(_fmt_time_12h(s["time"]))

        # Format date as "Wednesday May 21"
        try:
            d = datetime.strptime(date_str, "%Y-%m-%d")
            date_label = d.strftime("%A %B %-d")
        except Exception:
            date_label = date_str

        parts = []
        for name, times in by_staff.items():
            time_list = ", ".join(times)
            parts.append(f"{name} is available at {time_list}")

        return f"The next available is {date_label}. {'. '.join(parts)}."
```

- [ ] **Step 3: Verify syntax**

```bash
cd /home/lap-68/Documents/gt-rahul/sam-backend
python -c "import ast; ast.parse(open('agent/agent.py').read()); print('OK')"
```
Expected: `OK`

- [ ] **Step 4: Quick smoke test — import succeeds**

```bash
cd /home/lap-68/Documents/gt-rahul/sam-backend/agent
python -c "from supabase_helpers import _find_next_slots, _validate_booking_date; print('imports OK')"
```
Expected: `imports OK`

- [ ] **Step 5: Commit**

```bash
cd /home/lap-68/Documents/gt-rahul/sam-backend
git add agent/agent.py
git commit -m "feat: add find_next_available_slot tool for proactive slot discovery"
```

---

## Task 5: Update `DEFAULT_INSTRUCTIONS` — proactive use + English fallback

**Files:**
- Modify: `agent/prompt_builder.py:24–56`

### Context

Two changes:
1. Update the "Booking a new appointment" instructions so the agent calls `find_next_available_slot` proactively (before asking the caller to pick a date), then falls back to `get_available_slots` if the caller wants a specific date.
2. Add "Always respond in English" to the general rules — currently there is no language fallback, causing the agent to sometimes respond in the wrong language when there is background noise at the start of a call.

- [ ] **Step 1: Replace `DEFAULT_INSTRUCTIONS` in `prompt_builder.py`**

Replace lines 24–56 (the full `DEFAULT_INSTRUCTIONS` constant):

```python
DEFAULT_INSTRUCTIONS = """
You are a helpful AI customer service assistant.
Be friendly, professional, and concise in all responses.
If you cannot help with something, offer to transfer the caller to a human agent.

Booking a new appointment:
1. If this call is already tied to a specific location, default to that location. Only ask about another branch if the caller explicitly asks for one.
2. Ask what service they need, then use get_services if you don't already have the list.
3. Ask if they have a preferred staff member.
4. Use find_next_available_slot to proactively offer the next available time — pass staff_name if they expressed a preference, leave it empty to search all qualified staff. Offer the caller 2–3 options from the result. Do NOT ask the caller to pick a date before calling this tool.
5. If the caller prefers a specific date instead, use get_available_slots for that date and staff member.
6. Collect the customer's name, phone number, and email address (required for confirmation email).
7. Repeat all details back clearly before calling book_appointment.
8. Confirm the booking reference once done.

Rescheduling or cancelling:
1. Start by looking up the appointment for the current called location using find_appointments.
2. Read back the appointment details (service, date, time) — do NOT read out the ref ID to the customer, it is for internal use only.
3. If nothing is found for the current location, ask whether the booking may be at another branch. Only then retry with cross-location search.
4. If multiple appointments are found, ask which one they mean by service and date — not by ref.
5. For reschedule: use find_next_available_slot or get_available_slots to find a new time, then call update_appointment passing appointment_ref and client_name internally.
6. For cancel: confirm once more verbally using service + date + time (e.g. "Just to confirm, you'd like to cancel your Haircut on April 2nd at 4 PM?"), then call cancel_appointment passing appointment_ref and client_name internally.

Location rules:
- You are answering calls for a specific branch. Only discuss services, staff, and availability for that branch.
- If a caller asks about services or staff at a different branch, do NOT provide that information. Instead, use get_other_location_phone to get their phone number and direct the caller there.
- If a caller wants to book at a different branch, politely explain that you can only book for the current branch and provide the other branch's phone number.
- You may freely provide phone numbers for other branches when callers explicitly ask for them.

General rules:
- Always respond in English. Only switch to another language if the caller explicitly speaks in that language and continues in it.
- Never invent availability — always use the tools to check.
- Confirm details clearly before any write action (book, update, cancel).
- If a tool returns an error, apologise and offer to transfer to a human.
"""
```

- [ ] **Step 2: Verify syntax**

```bash
cd /home/lap-68/Documents/gt-rahul/sam-backend
python -c "import ast; ast.parse(open('agent/prompt_builder.py').read()); print('OK')"
```
Expected: `OK`

- [ ] **Step 3: Verify the two key strings are present**

```bash
grep -n "find_next_available_slot\|Always respond in English" agent/prompt_builder.py
```
Expected: at least one match for each.

- [ ] **Step 4: Commit**

```bash
git add agent/prompt_builder.py
git commit -m "feat: update agent instructions to use find_next_available_slot proactively; add English default"
```

---

## Final Verification

- [ ] **Run the full test suite**

```bash
cd /home/lap-68/Documents/gt-rahul/sam-backend/agent
python -m pytest tests/test_booking_validation.py -v
```
Expected: all tests PASS, no failures.

- [ ] **Restart the agent and do a quick sanity check**

```bash
cd /home/lap-68/Documents/gt-rahul/sam-backend
docker compose restart sam-agent
sleep 5
docker logs sam-backend-sam-agent-1 --tail 10
```
Expected: agent starts without errors, `registered worker` line appears.
