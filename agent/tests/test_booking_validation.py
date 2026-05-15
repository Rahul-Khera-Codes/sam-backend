from datetime import datetime, timezone, timedelta
from unittest.mock import patch
import pytest

from supabase_helpers import _validate_booking_datetime


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
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with patch("supabase_helpers._fetch_active_custom_schedule", return_value=None), \
         patch("supabase_helpers._fetch_business_hours_for_location", return_value=[
             {"day_of_week": datetime.now(timezone.utc).strftime("%A").lower(),
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

    rahul_slots = [r for r in result if r["staff_name"] == "Rahul"]
    assert 1 <= len(rahul_slots) <= 3
