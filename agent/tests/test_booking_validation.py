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
