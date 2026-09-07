import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from fastapi import HTTPException

from app.services.booking_service import _validate_booking, _validate_staff_availability


def _future_date(weekday: int) -> str:
    """Return a far-future date string (year 2099) that falls on the given weekday (0=Mon)."""
    d = datetime(2099, 1, 1)
    days_ahead = (weekday - d.weekday()) % 7
    return (d + timedelta(days=days_ahead)).strftime("%Y-%m-%d")


FUTURE_MONDAY = _future_date(0)
FUTURE_DAY_NAME = datetime.strptime(FUTURE_MONDAY, "%Y-%m-%d").strftime("%A").lower()


class ValidateBookingTests(unittest.TestCase):
    def test_rejects_duration_pushing_past_close(self):
        """Start time within hours must still be rejected if start+duration runs past closing."""
        with patch(
            "app.services.booking_service._fetch_active_custom_schedule", return_value=None
        ), patch(
            "app.services.booking_service._fetch_business_hours",
            return_value=[
                {"day_of_week": FUTURE_DAY_NAME, "is_open": True,
                 "open_time": "09:00:00", "close_time": "17:00:00"}
            ],
        ):
            with self.assertRaises(HTTPException) as ctx:
                _validate_booking("biz", "loc", FUTURE_MONDAY, "16:45", duration_minutes=60)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_accepts_duration_ending_exactly_at_close(self):
        with patch(
            "app.services.booking_service._fetch_active_custom_schedule", return_value=None
        ), patch(
            "app.services.booking_service._fetch_business_hours",
            return_value=[
                {"day_of_week": FUTURE_DAY_NAME, "is_open": True,
                 "open_time": "09:00:00", "close_time": "17:00:00"}
            ],
        ):
            _validate_booking("biz", "loc", FUTURE_MONDAY, "16:00", duration_minutes=60)
            # No exception raised == success.


class ValidateStaffAvailabilityTests(unittest.IsolatedAsyncioTestCase):
    """_validate_staff_availability is async (AIE-69: it also checks the staff
    member's connected Google Calendar) — IsolatedAsyncioTestCase (stdlib,
    Python 3.8+) runs these without adding a pytest-asyncio dependency.
    Every existing test patches _get_gcal_token_row to return None (no
    connected calendar), which fails open per fetch_busy_intervals's own
    contract — preserving each test's original, calendar-unaware behavior.
    """

    async def test_skips_when_unconfigured(self):
        with patch(
            "app.services.booking_service._fetch_user_availability", return_value=[]
        ):
            await _validate_staff_availability("user-1", "Alex", FUTURE_MONDAY, "23:45", duration_minutes=60)
            # No exception raised == skipped.

    async def test_rejects_duration_past_employee_end_time(self):
        """The exact reported bug: employee ends at 4pm, request tries to book 4:45pm."""
        with patch(
            "app.services.booking_service._fetch_user_availability",
            return_value=[
                {"day_of_week": FUTURE_DAY_NAME, "is_available": True,
                 "start_time": "09:00", "end_time": "16:00"}
            ],
        ), patch(
            "app.services.booking_service._fetch_user_overrides", return_value=[]
        ), patch(
            "app.services.booking_service._fetch_staff_appointments_on_date", return_value=[]
        ), patch(
            "app.services.booking_service._get_gcal_token_row", return_value=None
        ):
            with self.assertRaises(HTTPException) as ctx:
                await _validate_staff_availability(
                    "user-1", "Alex", FUTURE_MONDAY, "16:45", duration_minutes=30,
                )
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("Alex", ctx.exception.detail)

    async def test_accepts_slot_within_employee_hours(self):
        with patch(
            "app.services.booking_service._fetch_user_availability",
            return_value=[
                {"day_of_week": FUTURE_DAY_NAME, "is_available": True,
                 "start_time": "09:00", "end_time": "17:00"}
            ],
        ), patch(
            "app.services.booking_service._fetch_user_overrides", return_value=[]
        ), patch(
            "app.services.booking_service._fetch_staff_appointments_on_date", return_value=[]
        ), patch(
            "app.services.booking_service._get_gcal_token_row", return_value=None
        ):
            await _validate_staff_availability(
                "user-1", "Alex", FUTURE_MONDAY, "16:00", duration_minutes=60,
            )
            # No exception raised == success.

    async def test_rejects_day_off(self):
        with patch(
            "app.services.booking_service._fetch_user_availability",
            return_value=[
                {"day_of_week": "tuesday", "is_available": True,
                 "start_time": "09:00", "end_time": "17:00"}
            ],
        ):
            with self.assertRaises(HTTPException):
                await _validate_staff_availability(
                    "user-1", "Alex", FUTURE_MONDAY, "10:00", duration_minutes=60,
                )

    async def test_rejects_full_day_override(self):
        with patch(
            "app.services.booking_service._fetch_user_availability",
            return_value=[
                {"day_of_week": FUTURE_DAY_NAME, "is_available": True,
                 "start_time": "09:00", "end_time": "17:00"}
            ],
        ), patch(
            "app.services.booking_service._fetch_user_overrides",
            return_value=[{"is_unavailable": True, "start_time": None, "end_time": None}],
        ), patch(
            "app.services.booking_service._fetch_staff_appointments_on_date", return_value=[]
        ):
            with self.assertRaises(HTTPException):
                await _validate_staff_availability(
                    "user-1", "Alex", FUTURE_MONDAY, "10:00", duration_minutes=60,
                )

    async def test_rejects_overlap_with_existing_booking(self):
        """Overlap detection must work even without an exact start-time match."""
        with patch(
            "app.services.booking_service._fetch_user_availability",
            return_value=[
                {"day_of_week": FUTURE_DAY_NAME, "is_available": True,
                 "start_time": "09:00", "end_time": "17:00"}
            ],
        ), patch(
            "app.services.booking_service._fetch_user_overrides", return_value=[]
        ), patch(
            "app.services.booking_service._fetch_staff_appointments_on_date",
            return_value=[{"id": "existing-1", "appointment_time": "10:00", "duration": "60"}],
        ), patch(
            "app.services.booking_service._get_gcal_token_row", return_value=None
        ):
            with self.assertRaises(HTTPException):
                await _validate_staff_availability(
                    "user-1", "Alex", FUTURE_MONDAY, "10:30", duration_minutes=30,
                )

    async def test_excludes_self_when_rescheduling(self):
        """Rescheduling an appointment to overlap its own prior slot must not self-conflict."""
        with patch(
            "app.services.booking_service._fetch_user_availability",
            return_value=[
                {"day_of_week": FUTURE_DAY_NAME, "is_available": True,
                 "start_time": "09:00", "end_time": "17:00"}
            ],
        ), patch(
            "app.services.booking_service._fetch_user_overrides", return_value=[]
        ), patch(
            "app.services.booking_service._fetch_staff_appointments_on_date",
            return_value=[{"id": "appt-1", "appointment_time": "10:00", "duration": "60"}],
        ), patch(
            "app.services.booking_service._get_gcal_token_row", return_value=None
        ):
            await _validate_staff_availability(
                "user-1", "Alex", FUTURE_MONDAY, "10:15", duration_minutes=60,
                exclude_appointment_id="appt-1",
            )
            # No exception raised == success.

    async def test_rejects_google_calendar_busy_time(self):
        """AIE-69: a personal Google Calendar event overlapping the requested slot
        must block the booking even though the Portal Calendar itself is free."""
        with patch(
            "app.services.booking_service._fetch_user_availability",
            return_value=[
                {"day_of_week": FUTURE_DAY_NAME, "is_available": True,
                 "start_time": "09:00", "end_time": "17:00"}
            ],
        ), patch(
            "app.services.booking_service._fetch_user_overrides", return_value=[]
        ), patch(
            "app.services.booking_service._fetch_staff_appointments_on_date", return_value=[]
        ), patch(
            "app.services.booking_service._get_gcal_token_row", return_value={"access_token": "t"}
        ), patch(
            "app.services.booking_service.google_calendar_service.fetch_busy_intervals",
            return_value=[(datetime(1900, 1, 1, 10, 0), datetime(1900, 1, 1, 11, 0))],
        ):
            with self.assertRaises(HTTPException) as ctx:
                await _validate_staff_availability(
                    "user-1", "Alex", FUTURE_MONDAY, "10:30", duration_minutes=30,
                )
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("Alex", ctx.exception.detail)

    async def test_ignores_google_calendar_when_not_connected(self):
        """No connected calendar must fail open — booking proceeds on Portal
        Calendar availability alone, same as before this fix."""
        with patch(
            "app.services.booking_service._fetch_user_availability",
            return_value=[
                {"day_of_week": FUTURE_DAY_NAME, "is_available": True,
                 "start_time": "09:00", "end_time": "17:00"}
            ],
        ), patch(
            "app.services.booking_service._fetch_user_overrides", return_value=[]
        ), patch(
            "app.services.booking_service._fetch_staff_appointments_on_date", return_value=[]
        ), patch(
            "app.services.booking_service._get_gcal_token_row", return_value=None
        ):
            await _validate_staff_availability(
                "user-1", "Alex", FUTURE_MONDAY, "10:30", duration_minutes=30,
            )
            # No exception raised == success.


if __name__ == "__main__":
    unittest.main()
