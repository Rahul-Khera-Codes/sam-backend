from datetime import datetime, timezone, timedelta
from unittest.mock import patch
import pytest

from supabase_helpers import _validate_booking_datetime, _local_now, _compute_available_slots


def _future_date(weekday: int) -> str:
    """Return a far-future date string (year 2099) that falls on the given weekday (0=Mon)."""
    d = datetime(2099, 1, 1)
    days_ahead = (weekday - d.weekday()) % 7
    return (d + timedelta(days=days_ahead)).strftime("%Y-%m-%d")


FUTURE_MONDAY = _future_date(0)
FUTURE_DAY_NAME = datetime.strptime(FUTURE_MONDAY, "%Y-%m-%d").strftime("%A").lower()


def test_rejects_past_date():
    result = _validate_booking_datetime(
        supabase=None, business_id="biz-1", location_id="loc-1",
        date="2020-01-01", time="10:00",
    )
    assert result is not None
    assert "past" in result.lower()


def test_accepts_today():
    # Fixed "now" (rather than the real wall clock) so this doesn't flake
    # depending on what time of day the suite happens to run.
    fixed_now = datetime(2099, 1, 1, 8, 0)
    today = fixed_now.strftime("%Y-%m-%d")
    with patch("supabase_helpers._local_now", return_value=fixed_now), \
         patch("supabase_helpers._fetch_active_custom_schedule", return_value=None), \
         patch("supabase_helpers._fetch_business_hours_for_location", return_value=[
             {"day_of_week": fixed_now.strftime("%A").lower(),
              "is_open": True, "open_time": "00:00:00", "close_time": "23:59:00"}
         ]):
        result = _validate_booking_datetime(None, "biz", "loc", today, "10:00")
    assert result is None


def test_rejects_bad_date_format():
    result = _validate_booking_datetime(None, "b", "l", "30-04-2026", "10:00")
    assert result is not None
    assert "invalid" in result.lower() or "format" in result.lower()


def test_rejects_bad_time_format():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    result = _validate_booking_datetime(None, "b", "l", today, "10am")
    assert result is not None


def test_rejects_closed_day():
    future = FUTURE_MONDAY
    with patch("supabase_helpers._fetch_active_custom_schedule", return_value=None), \
         patch("supabase_helpers._fetch_business_hours_for_location", return_value=[
             {"day_of_week": FUTURE_DAY_NAME, "is_open": False, "open_time": None, "close_time": None}
         ]):
        result = _validate_booking_datetime(None, "b", "l", future, "10:00")
    assert result is not None
    assert "closed" in result.lower()


def test_rejects_time_before_open():
    future = FUTURE_MONDAY
    with patch("supabase_helpers._fetch_active_custom_schedule", return_value=None), \
         patch("supabase_helpers._fetch_business_hours_for_location", return_value=[
             {"day_of_week": FUTURE_DAY_NAME, "is_open": True,
              "open_time": "09:00:00", "close_time": "17:00:00"}
         ]):
        result = _validate_booking_datetime(None, "b", "l", future, "08:00")
    assert result is not None
    assert "outside" in result.lower() or "hours" in result.lower()


def test_rejects_time_after_close():
    future = FUTURE_MONDAY
    with patch("supabase_helpers._fetch_active_custom_schedule", return_value=None), \
         patch("supabase_helpers._fetch_business_hours_for_location", return_value=[
             {"day_of_week": FUTURE_DAY_NAME, "is_open": True,
              "open_time": "09:00:00", "close_time": "17:00:00"}
         ]):
        result = _validate_booking_datetime(None, "b", "l", future, "17:00")
    assert result is not None


def test_accepts_valid_time_within_hours():
    future = FUTURE_MONDAY
    with patch("supabase_helpers._fetch_active_custom_schedule", return_value=None), \
         patch("supabase_helpers._fetch_business_hours_for_location", return_value=[
             {"day_of_week": FUTURE_DAY_NAME, "is_open": True,
              "open_time": "09:00:00", "close_time": "17:00:00"}
         ]):
        result = _validate_booking_datetime(None, "b", "l", future, "10:30")
    assert result is None


def test_rejects_custom_schedule_agent_disabled():
    future = FUTURE_MONDAY
    with patch("supabase_helpers._fetch_active_custom_schedule", return_value={
        "is_agent_disabled": True, "open_time": None, "close_time": None
    }):
        result = _validate_booking_datetime(None, "b", "l", future, "10:00")
    assert result is not None
    assert "closed" in result.lower() or "special" in result.lower()


def test_custom_schedule_overrides_regular_hours():
    future = FUTURE_MONDAY
    with patch("supabase_helpers._fetch_active_custom_schedule", return_value={
        "is_agent_disabled": False, "open_time": "08:00:00", "close_time": "20:00:00",
    }), patch("supabase_helpers._fetch_business_hours_for_location", return_value=[
        {"day_of_week": FUTURE_DAY_NAME, "is_open": False, "open_time": None, "close_time": None}
    ]):
        result = _validate_booking_datetime(None, "b", "l", future, "10:00")
    assert result is None


def test_custom_schedule_rejects_outside_special_hours():
    future = FUTURE_MONDAY
    with patch("supabase_helpers._fetch_active_custom_schedule", return_value={
        "is_agent_disabled": False, "open_time": "08:00:00", "close_time": "12:00:00",
    }):
        result = _validate_booking_datetime(None, "b", "l", future, "14:00")
    assert result is not None
    assert "outside" in result.lower() or "hours" in result.lower()


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
    future_monday = _future_date(0)
    with patch("supabase_helpers._fetch_active_custom_schedule",
               return_value={"is_agent_disabled": False,
                             "open_time": "10:00", "close_time": "15:00"}):
        result = _validate_booking_date(None, "biz", "loc", future_monday)
    assert result is None


def test_validate_booking_date_does_not_check_time():
    """
    Regression test: _validate_booking_datetime("00:00") was used in get_available_slots,
    which rejected midnight as outside business hours (9am–5pm) and broke slot retrieval.
    _validate_booking_date must pass for the same open day without being tripped by a time.
    """
    future_monday = _future_date(0)
    mock_hours = [{"day_of_week": "monday", "is_open": True,
                   "open_time": "09:00:00", "close_time": "17:00:00"}]

    with patch("supabase_helpers._fetch_active_custom_schedule", return_value=None), \
         patch("supabase_helpers._fetch_business_hours_for_location", return_value=mock_hours):

        # The old broken approach: passes midnight, which is outside 9am-5pm
        broken = _validate_booking_datetime(None, "biz", "loc", future_monday, "00:00")
        assert broken is not None, "midnight should be outside business hours"
        assert "outside" in broken.lower()

        # The fix: date-only check passes for the same open day
        fixed = _validate_booking_date(None, "biz", "loc", future_monday)
        assert fixed is None, f"date-only check should pass for an open day, got: {fixed}"


def test_rejects_duration_pushing_past_close():
    """A start time within hours must still be rejected if start+duration runs past closing."""
    future = FUTURE_MONDAY
    with patch("supabase_helpers._fetch_active_custom_schedule", return_value=None), \
         patch("supabase_helpers._fetch_business_hours_for_location", return_value=[
             {"day_of_week": FUTURE_DAY_NAME, "is_open": True,
              "open_time": "09:00:00", "close_time": "17:00:00"}
         ]):
        # 16:45 start is within hours, but a 60-minute service ends at 17:45 — past close.
        result = _validate_booking_datetime(None, "b", "l", future, "16:45", duration_minutes=60)
    assert result is not None
    assert "outside" in result.lower() or "hours" in result.lower()


def test_accepts_duration_ending_exactly_at_close():
    future = FUTURE_MONDAY
    with patch("supabase_helpers._fetch_active_custom_schedule", return_value=None), \
         patch("supabase_helpers._fetch_business_hours_for_location", return_value=[
             {"day_of_week": FUTURE_DAY_NAME, "is_open": True,
              "open_time": "09:00:00", "close_time": "17:00:00"}
         ]):
        result = _validate_booking_datetime(None, "b", "l", future, "16:00", duration_minutes=60)
    assert result is None


from supabase_helpers import _validate_staff_availability


def test_staff_availability_skips_when_unconfigured():
    """No user_availability rows at all — skip enforcement, defer to business hours."""
    with patch("supabase_helpers._fetch_user_availability", return_value=[]):
        result = _validate_staff_availability(
            None, "user-1", "Alex", FUTURE_MONDAY, "23:45", duration_minutes=60,
        )
    assert result is None


def test_staff_availability_rejects_duration_past_employee_end_time():
    """The exact reported bug: employee ends at 4pm, agent tries to book 4:45pm."""
    with patch("supabase_helpers._fetch_user_availability", return_value=[
        {"day_of_week": FUTURE_DAY_NAME, "is_available": True,
         "start_time": "09:00", "end_time": "16:00"}
    ]), patch("supabase_helpers._fetch_user_overrides", return_value=[]), \
         patch("supabase_helpers._fetch_appointments_on_date", return_value=[]):
        result = _validate_staff_availability(
            None, "user-1", "Alex", FUTURE_MONDAY, "16:45", duration_minutes=30,
        )
    assert result is not None
    assert "Alex" in result


def test_staff_availability_accepts_slot_within_employee_hours():
    with patch("supabase_helpers._fetch_user_availability", return_value=[
        {"day_of_week": FUTURE_DAY_NAME, "is_available": True,
         "start_time": "09:00", "end_time": "17:00"}
    ]), patch("supabase_helpers._fetch_user_overrides", return_value=[]), \
         patch("supabase_helpers._fetch_appointments_on_date", return_value=[]):
        result = _validate_staff_availability(
            None, "user-1", "Alex", FUTURE_MONDAY, "16:00", duration_minutes=60,
        )
    assert result is None


def test_staff_availability_rejects_day_off():
    with patch("supabase_helpers._fetch_user_availability", return_value=[
        {"day_of_week": "tuesday", "is_available": True,
         "start_time": "09:00", "end_time": "17:00"}
    ]):
        result = _validate_staff_availability(
            None, "user-1", "Alex", FUTURE_MONDAY, "10:00", duration_minutes=60,
        )
    assert result is not None


def test_staff_availability_rejects_full_day_override():
    with patch("supabase_helpers._fetch_user_availability", return_value=[
        {"day_of_week": FUTURE_DAY_NAME, "is_available": True,
         "start_time": "09:00", "end_time": "17:00"}
    ]), patch("supabase_helpers._fetch_user_overrides", return_value=[
        {"is_unavailable": True, "start_time": None, "end_time": None}
    ]), patch("supabase_helpers._fetch_appointments_on_date", return_value=[]):
        result = _validate_staff_availability(
            None, "user-1", "Alex", FUTURE_MONDAY, "10:00", duration_minutes=60,
        )
    assert result is not None


def test_staff_availability_rejects_overlap_with_existing_booking():
    """Overlap detection must work even without an exact start-time match."""
    with patch("supabase_helpers._fetch_user_availability", return_value=[
        {"day_of_week": FUTURE_DAY_NAME, "is_available": True,
         "start_time": "09:00", "end_time": "17:00"}
    ]), patch("supabase_helpers._fetch_user_overrides", return_value=[]), \
         patch("supabase_helpers._fetch_appointments_on_date", return_value=[
             {"id": "existing-1", "appointment_time": "10:00", "duration": "60"}
         ]):
        # New request 10:30-11:00 overlaps the existing 10:00-11:00 booking.
        result = _validate_staff_availability(
            None, "user-1", "Alex", FUTURE_MONDAY, "10:30", duration_minutes=30,
        )
    assert result is not None


def test_staff_availability_excludes_self_when_rescheduling():
    """Rescheduling an appointment to overlap its own prior slot must not self-conflict."""
    with patch("supabase_helpers._fetch_user_availability", return_value=[
        {"day_of_week": FUTURE_DAY_NAME, "is_available": True,
         "start_time": "09:00", "end_time": "17:00"}
    ]), patch("supabase_helpers._fetch_user_overrides", return_value=[]), \
         patch("supabase_helpers._fetch_appointments_on_date", return_value=[
             {"id": "appt-1", "appointment_time": "10:00", "duration": "60"}
         ]):
        result = _validate_staff_availability(
            None, "user-1", "Alex", FUTURE_MONDAY, "10:15", duration_minutes=60,
            exclude_appointment_id="appt-1",
        )
    assert result is None


from supabase_helpers import _find_next_slots


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
            from_date="2099-01-06",  # far-future date; all days mocked as closed
            max_days=5,
        )
    assert result == []


def test_find_next_slots_skips_closed_days_and_finds_open():
    """Skips a closed Monday and finds slots on Tuesday."""
    monday = _future_date(0)
    tuesday = (datetime.strptime(monday, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")

    def date_validator(supabase, business_id, location_id, date, business_timezone="UTC"):
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

    rahul_slots = [r for r in result if r["staff_name"] == "Rahul"]
    assert 1 <= len(rahul_slots) <= 3


# ── AIE-43 regression: "now"/"today" must be evaluated in the business's ──
# ── local timezone, not raw UTC, or same-day local times get wrongly ──────
# ── rejected as "already passed".                                    ──────


def test_local_now_matches_real_timezone_offset():
    utc_now = _local_now("UTC")
    toronto_now = _local_now("America/Toronto")
    delta_hours = (utc_now - toronto_now).total_seconds() / 3600
    assert 3.9 <= delta_hours <= 5.1  # Toronto is UTC-4 (EDT) or UTC-5 (EST)


def test_local_now_falls_back_to_utc_on_unknown_timezone():
    result = _local_now("Not/A/Real/Zone")
    utc_now = _local_now("UTC")
    assert abs((result - utc_now).total_seconds()) < 5


def test_validate_booking_datetime_accepts_future_local_time():
    """
    The exact reported bug: a caller asks for a same-day time that is still
    hours away in the business's local time. Must be accepted even though
    business_timezone differs from UTC.
    """
    fixed_local_now = datetime(2099, 1, 1, 9, 0)  # 9:00 AM local
    today = fixed_local_now.strftime("%Y-%m-%d")
    with patch("supabase_helpers._local_now", return_value=fixed_local_now) as mock_local_now, \
         patch("supabase_helpers._fetch_active_custom_schedule", return_value=None), \
         patch("supabase_helpers._fetch_business_hours_for_location", return_value=[
             {"day_of_week": fixed_local_now.strftime("%A").lower(),
              "is_open": True, "open_time": "00:00:00", "close_time": "23:59:00"}
         ]):
        result = _validate_booking_datetime(
            None, "biz", "loc", today, "14:00", business_timezone="America/Toronto",
        )
        mock_local_now.assert_called_with("America/Toronto")
    assert result is None


def test_validate_booking_datetime_rejects_local_past_time():
    fixed_local_now = datetime(2099, 1, 1, 15, 0)  # 3:00 PM local
    today = fixed_local_now.strftime("%Y-%m-%d")
    with patch("supabase_helpers._local_now", return_value=fixed_local_now), \
         patch("supabase_helpers._fetch_active_custom_schedule", return_value=None), \
         patch("supabase_helpers._fetch_business_hours_for_location", return_value=[
             {"day_of_week": fixed_local_now.strftime("%A").lower(),
              "is_open": True, "open_time": "00:00:00", "close_time": "23:59:00"}
         ]):
        result = _validate_booking_datetime(
            None, "biz", "loc", today, "14:00", business_timezone="America/Toronto",
        )
    assert result is not None
    assert "already passed" in result.lower()


def test_compute_available_slots_excludes_before_local_now():
    fixed_local_now = datetime(2099, 1, 1, 10, 30)  # 10:30 AM local
    today = fixed_local_now.strftime("%Y-%m-%d")
    availability = [{
        "day_of_week": fixed_local_now.strftime("%A").lower(),
        "is_available": True, "start_time": "09:00", "end_time": "17:00",
    }]
    with patch("supabase_helpers._local_now", return_value=fixed_local_now):
        slots = _compute_available_slots(
            availability, [], [], today, slot_minutes=60, business_timezone="America/Toronto",
        )
    assert "09:00" not in slots
    assert "10:00" not in slots
    assert "11:00" in slots
