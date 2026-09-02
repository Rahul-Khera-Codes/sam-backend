from datetime import datetime
from unittest.mock import patch, MagicMock
from prompt_builder import build_instructions


def _mock_supabase_minimal():
    """Returns a supabase mock that returns enough data to not crash build_instructions."""
    sb = MagicMock()
    # businesses
    biz_resp = MagicMock()
    biz_resp.data = [{"name": "Test Biz", "phone": "", "email": "", "website": "", "address": "", "business_type": "", "service_area": "", "payment_methods": "", "policies": ""}]
    # everything else returns empty list
    empty = MagicMock()
    empty.data = []
    sb.table.return_value.select.return_value.eq.return_value.execute.return_value = empty
    sb.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = empty
    sb.table.return_value.select.return_value.eq.return_value.is_.return_value.execute.return_value = empty
    sb.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.execute.return_value = empty
    # business fetch specifically
    biz_table = MagicMock()
    biz_table.select.return_value.eq.return_value.limit.return_value.execute.return_value = biz_resp
    sb.table.side_effect = lambda name: biz_table if name == "businesses" else sb.table.return_value
    return sb


def test_build_instructions_default_greeting_contains_example():
    """Without custom_greeting, prompt includes the hardcoded example."""
    with patch("prompt_builder._get_supabase", return_value=_mock_supabase_minimal()):
        result = build_instructions("biz-123", None)
    assert "Thank you for calling" in result
    assert "Always start the call" in result


def test_build_instructions_custom_greeting_replaces_welcome_block():
    """With custom_greeting, the custom text appears and the generic instruction is removed."""
    with patch("prompt_builder._get_supabase", return_value=_mock_supabase_minimal()):
        result = build_instructions("biz-123", None, custom_greeting="Hey, welcome to Test Biz!")
    assert "Hey, welcome to Test Biz!" in result
    assert "Start the call with this greeting" in result
    # Generic instruction should be gone
    assert "Always start the call with a short, friendly welcome" not in result
    assert "Thank you for calling" not in result


def test_build_instructions_empty_custom_greeting_uses_default():
    """Empty string for custom_greeting falls back to default behaviour."""
    with patch("prompt_builder._get_supabase", return_value=_mock_supabase_minimal()):
        result = build_instructions("biz-123", None, custom_greeting="")
    assert "Always start the call" in result
    assert "Thank you for calling" in result


def test_build_instructions_whitespace_custom_greeting_uses_default():
    """Whitespace-only custom_greeting falls back to default behaviour."""
    with patch("prompt_builder._get_supabase", return_value=_mock_supabase_minimal()):
        result = build_instructions("biz-123", None, custom_greeting="   ")
    assert "Always start the call" in result
    assert "Thank you for calling" in result


def test_build_instructions_includes_current_date_grounding():
    """
    AIE-43 regression: the CSE prompt previously never told the LLM what today's
    date/day-of-week is, so it had no anchor to resolve a caller's relative day
    reference (e.g. "this Tuesday afternoon") into the correct calendar date.
    """
    with patch("prompt_builder._get_supabase", return_value=_mock_supabase_minimal()), \
         patch("prompt_builder._local_now", return_value=datetime(2026, 9, 8)):
        result = build_instructions("biz-123", None)
    assert "Current date: today is Tuesday, September 8, 2026" in result
    assert "America/Toronto" in result  # default fallback when business has no timezone set


def test_build_instructions_uses_business_timezone_for_current_date():
    """The current-date grounding line uses the business's own timezone, not the default."""
    sb = _mock_supabase_minimal()
    biz_resp = MagicMock()
    biz_resp.data = [{
        "name": "Test Biz", "timezone": "Asia/Tokyo",
        "phone": "", "email": "", "website": "", "address": "",
        "business_type": "", "service_area": "", "payment_methods": "", "policies": "",
    }]
    biz_table = MagicMock()
    biz_table.select.return_value.eq.return_value.limit.return_value.execute.return_value = biz_resp
    sb.table.side_effect = lambda name: biz_table if name == "businesses" else sb.table.return_value

    with patch("prompt_builder._get_supabase", return_value=sb), \
         patch("prompt_builder._local_now") as mock_local_now:
        mock_local_now.return_value = datetime(2026, 9, 8)
        result = build_instructions("biz-123", None)

    assert "Asia/Tokyo" in result
    mock_local_now.assert_any_call("Asia/Tokyo")


def test_build_instructions_custom_schedule_uses_local_weekday_not_server_clock():
    """
    AIE-43 regression: the active-custom-schedule hours override previously keyed off
    the naive server/UTC clock instead of the business's local day, which could apply
    "today's" override to the wrong row of business hours near the UTC day boundary.
    """
    sb = _mock_supabase_minimal()
    with patch("prompt_builder._get_supabase", return_value=sb), \
         patch("prompt_builder._fetch_active_custom_schedule", return_value={
             "name": "Holiday Hours", "is_agent_disabled": False,
             "open_time": "10:00", "close_time": "14:00",
         }), \
         patch("prompt_builder._local_now") as mock_local_now:
        mock_local_now.return_value = datetime(2026, 9, 8)  # a Tuesday
        result = build_instructions("biz-123", "loc-1")

    mock_local_now.assert_any_call("America/Toronto")
    assert "Today's hours are affected by the active schedule 'Holiday Hours'" in result
