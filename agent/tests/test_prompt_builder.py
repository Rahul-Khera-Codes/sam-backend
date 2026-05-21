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
