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


# ── AIE-43 (round 4) regression: silently truncating the slot list left the ──
# ── agent unable to know the real last available time, so it kept reporting ──
# ── the last item of whatever partial batch it saw as "the last available   ──
# ── time" — reproduced verbatim by a real call transcript (Heather AIE,     ──
# ── Tuesday Sept 8: agent said "no later than 3:45", then found more when   ──
# ── asked for afternoon, then again when asked for "3 or 4").               ──


from supabase_helpers import _format_slots_for_speech


def test_format_slots_for_speech_shows_all_when_under_cap():
    result = _format_slots_for_speech("Heather", "2026-09-08", ["09:00", "09:15", "09:30"], cap=8)
    assert result == "Heather is available on 2026-09-08 at: 9:00 AM, 9:15 AM, 9:30 AM."
    assert "more" not in result


def test_format_slots_for_speech_states_true_last_time_when_truncated():
    """
    The core AIE-43 bug: when there are more slots than the spoken sample can
    include, the response must explicitly say what the actual last slot is —
    never leave the model to assume the last *shown* time is the last *available*
    one, since that's exactly how it kept mis-answering "what's the last available
    time" with an early, truncated value.
    """
    # 09:00-17:00 in 15-minute increments = 32 total slots, ending at 16:45.
    slots = []
    h, m = 9, 0
    while (h, m) < (17, 0):
        slots.append(f"{h:02d}:{m:02d}")
        m += 15
        if m == 60:
            m = 0
            h += 1

    result = _format_slots_for_speech("Heather", "2026-09-08", slots, cap=8)

    assert len(slots) == 32
    assert "4:45 PM" in result  # the true last slot (16:45), not the 8th shown one
    assert "the actual last available time that day" in result
    assert "(and 24 more" in result


def test_format_slots_for_speech_reproduces_reported_call():
    """
    Direct reproduction of the reported call: Heather's Tuesday hours are
    02:00-16:00 with a 15-minute consultation slot and no prior bookings, so
    the raw slot list runs 02:00 through 15:45 (56 slots). The old code capped
    display at 8 and said nothing about the rest — which is exactly why the
    agent told the caller "no later than 3:45" (the 8th item) when 3:00-3:45 PM
    slots existed the whole time.
    """
    slots = []
    h, m = 2, 0
    while (h, m) < (16, 0):
        slots.append(f"{h:02d}:{m:02d}")
        m += 15
        if m == 60:
            m = 0
            h += 1

    result = _format_slots_for_speech("Heather AIE", "2026-09-08", slots, cap=8)

    assert len(slots) == 56
    assert "3:45 PM" in result  # true last slot — must never be reported as "3:45 AM"
    assert "the actual last available time that day" in result


def test_format_slots_for_speech_no_slots():
    assert _format_slots_for_speech("Heather", "2026-09-08", []) == "Heather has no available slots on 2026-09-08."


def test_find_next_slots_reports_true_last_time_when_more_than_3():
    """AIE-43: find_next_available_slot must know the day's true last slot too,
    not just the 3 it speaks out loud, for the same reason as get_available_slots."""
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
            slot_minutes=15,  # 32 total slots that day — well over the 3 shown
            from_date=future_monday,
            max_days=5,
        )

    rahul_slots = [r for r in result if r["staff_name"] == "Rahul"]
    assert len(rahul_slots) == 3
    assert all(r["last_time"] == "16:45" for r in rahul_slots)


def test_find_next_slots_last_time_none_when_not_truncated():
    """When there are 3 or fewer slots total, there's nothing hidden — last_time
    should be None rather than a misleading repeat of the last shown slot."""
    future_monday = _future_date(0)

    with patch("supabase_helpers._validate_booking_date", return_value=None), \
         patch("supabase_helpers._fetch_user_availability", return_value=[
             {"day_of_week": "monday", "is_available": True,
              "start_time": "09:00", "end_time": "10:00"}
         ]), \
         patch("supabase_helpers._fetch_user_overrides", return_value=[]), \
         patch("supabase_helpers._fetch_appointments_on_date", return_value=[]):
        result = _find_next_slots(
            supabase=None,
            business_id="biz",
            location_id="loc",
            user_entries=[{"user_id": "u1", "name": "Rahul"}],
            slot_minutes=60,  # exactly 1 slot that day (09:00-10:00)
            from_date=future_monday,
            max_days=5,
        )

    rahul_slots = [r for r in result if r["staff_name"] == "Rahul"]
    assert len(rahul_slots) == 1
    assert all(r["last_time"] is None for r in rahul_slots)


# ── AIE-56 regression: a standing time-of-day preference ("an afternoon      ──
# ── appointment, any day this week") must filter every day in the scan, not ──
# ── just the first — the agent kept re-offering the same day (or handing    ──
# ── back an unrelated day's morning slots) because after_time only ever     ──
# ── applied to from_date itself (the AIE-43 "later, same day" behavior).    ──


def test_find_next_slots_min_time_applies_across_every_day():
    """Monday only has morning availability; Tuesday has afternoon availability.
    Asking for min_time="12:00" starting Monday must skip Monday's non-matching
    morning slots and return Tuesday's afternoon slots — not stop on Monday with
    slots that don't actually match what the caller asked for."""
    monday = _future_date(0)
    tuesday = (datetime.strptime(monday, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")

    with patch("supabase_helpers._validate_booking_date", return_value=None), \
         patch("supabase_helpers._fetch_user_availability", return_value=[
             {"day_of_week": "monday", "is_available": True,
              "start_time": "09:00", "end_time": "12:00"},
             {"day_of_week": "tuesday", "is_available": True,
              "start_time": "13:00", "end_time": "17:00"},
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
            min_time="12:00",
        )

    assert len(result) > 0
    assert all(r["date"] == tuesday for r in result)
    assert all(r["time"] >= "12:00" for r in result)


def test_find_next_slots_after_time_does_not_leak_into_later_days():
    """after_time (the AIE-43 "later today" resume) must stay scoped to from_date
    only — a later day's earlier slots are new offers the caller hasn't heard yet,
    not something to re-hide. This is exactly why min_time had to be a separate
    parameter rather than reusing after_time across the whole scan."""
    monday = _future_date(0)
    tuesday = (datetime.strptime(monday, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")

    with patch("supabase_helpers._validate_booking_date", return_value=None), \
         patch("supabase_helpers._fetch_user_availability", return_value=[
             {"day_of_week": "monday", "is_available": True,
              "start_time": "09:00", "end_time": "10:00"},
             {"day_of_week": "tuesday", "is_available": True,
              "start_time": "09:00", "end_time": "10:00"},
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
            after_time="15:00",  # later than Monday's only slot, so Monday is skipped
        )

    assert len(result) > 0
    assert all(r["date"] == tuesday for r in result)  # Tuesday's 09:00 slot isn't hidden


# ── AIE-56 regression #2: "what's your latest appointment this week?" was    ──
# ── answered by re-stating the first (soonest) matching day's own last time  ──
# ── as if it were the whole week's latest — reproduced verbatim by call id   ──
# ── 13eef36c-98ef-4227-bcc4-672f1d00a3e3 (Heather AIE): agent said Tuesday   ──
# ── 3:00 PM was "the latest available... during the week", then immediately ──
# ── found a 5:45 PM Thursday slot once asked about Thursday by name.        ──
# ── _find_next_slots structurally cannot answer this — it stops at the      ──
# ── first matching day and never compares later days. _find_latest_slot     ──
# ── scans the whole window and keeps the true max (date, time).             ──


from supabase_helpers import _find_latest_slot


def test_find_latest_slot_picks_max_across_days_not_first_match():
    """Monday and Tuesday both have matching slots, but Thursday has a later one.
    Must return Thursday's slot, not stop at the first day that matches."""
    monday = _future_date(0)
    thursday = (datetime.strptime(monday, "%Y-%m-%d") + timedelta(days=3)).strftime("%Y-%m-%d")

    with patch("supabase_helpers._validate_booking_date", return_value=None), \
         patch("supabase_helpers._fetch_user_availability", return_value=[
             {"day_of_week": "monday", "is_available": True,
              "start_time": "13:00", "end_time": "15:00"},
             {"day_of_week": "tuesday", "is_available": True,
              "start_time": "13:00", "end_time": "15:00"},
             {"day_of_week": "thursday", "is_available": True,
              "start_time": "13:00", "end_time": "18:00"},
         ]), \
         patch("supabase_helpers._fetch_user_overrides", return_value=[]), \
         patch("supabase_helpers._fetch_appointments_on_date", return_value=[]):
        result = _find_latest_slot(
            supabase=None,
            business_id="biz",
            location_id="loc",
            user_entries=[{"user_id": "u1", "name": "Heather AIE"}],
            slot_minutes=15,
            from_date=monday,
            within_days=7,
        )

    assert result is not None
    assert result["date"] == thursday
    assert result["time"] == "17:45"  # last 15-min slot before 18:00 close
    assert result["staff_name"] == "Heather AIE"


def test_find_latest_slot_respects_min_time_floor():
    """min_time still applies on every day scanned — asking for the latest
    afternoon slot must not return an even-later morning-only day."""
    monday = _future_date(0)
    tuesday = (datetime.strptime(monday, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")

    with patch("supabase_helpers._validate_booking_date", return_value=None), \
         patch("supabase_helpers._fetch_user_availability", return_value=[
             {"day_of_week": "monday", "is_available": True,
              "start_time": "13:00", "end_time": "15:00"},
             {"day_of_week": "tuesday", "is_available": True,
              "start_time": "06:00", "end_time": "08:00"},
         ]), \
         patch("supabase_helpers._fetch_user_overrides", return_value=[]), \
         patch("supabase_helpers._fetch_appointments_on_date", return_value=[]):
        result = _find_latest_slot(
            supabase=None,
            business_id="biz",
            location_id="loc",
            user_entries=[{"user_id": "u1", "name": "Rahul"}],
            slot_minutes=60,
            from_date=monday,
            within_days=7,
            min_time="12:00",
        )

    assert result is not None
    assert result["date"] == monday  # Tuesday's slot is earlier in the day and filtered out
    assert result["time"] == "14:00"


def test_find_latest_slot_within_days_bounds_the_search():
    """A later slot outside the within_days window must not be returned."""
    monday = _future_date(0)

    with patch("supabase_helpers._validate_booking_date", return_value=None), \
         patch("supabase_helpers._fetch_user_availability", return_value=[
             {"day_of_week": "monday", "is_available": True,
              "start_time": "13:00", "end_time": "15:00"},
             {"day_of_week": "wednesday", "is_available": True,
              "start_time": "13:00", "end_time": "18:00"},
         ]), \
         patch("supabase_helpers._fetch_user_overrides", return_value=[]), \
         patch("supabase_helpers._fetch_appointments_on_date", return_value=[]):
        result = _find_latest_slot(
            supabase=None,
            business_id="biz",
            location_id="loc",
            user_entries=[{"user_id": "u1", "name": "Rahul"}],
            slot_minutes=60,
            from_date=monday,
            within_days=2,  # only Monday and Tuesday — Wednesday's later slot is out of range
        )

    assert result is not None
    assert result["date"] == monday
    assert result["time"] == "14:00"


def test_find_latest_slot_returns_none_when_nothing_matches():
    with patch("supabase_helpers._validate_booking_date", return_value="closed"), \
         patch("supabase_helpers._fetch_user_availability", return_value=[]):
        result = _find_latest_slot(
            supabase=None,
            business_id="biz",
            location_id="loc",
            user_entries=[{"user_id": "u1", "name": "Rahul"}],
            slot_minutes=60,
            from_date=_future_date(0),
            within_days=7,
        )
    assert result is None
