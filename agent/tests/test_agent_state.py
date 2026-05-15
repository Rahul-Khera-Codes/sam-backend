from unittest.mock import MagicMock, patch
import pytest

from supabase_helpers import _fetch_agent_state


def test_fetch_agent_state_returns_none_when_no_row():
    """No row in DB → returns None (caller treats missing as is_active=True)."""
    mock_supabase = MagicMock()
    mock_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = []
    result = _fetch_agent_state(mock_supabase, "biz-1", "loc-1")
    assert result is None


def test_fetch_agent_state_returns_row_when_found():
    """Row exists → returns the dict."""
    mock_supabase = MagicMock()
    row = {"is_active": False, "toggled_at": "2026-05-15T10:00:00Z", "toggled_by": "user-1"}
    mock_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = [row]
    result = _fetch_agent_state(mock_supabase, "biz-1", "loc-1")
    assert result == row
    assert result["is_active"] is False


def test_fetch_agent_state_returns_none_on_exception():
    """Supabase raises → returns None, does not crash."""
    mock_supabase = MagicMock()
    mock_supabase.table.side_effect = Exception("connection error")
    result = _fetch_agent_state(mock_supabase, "biz-1", "loc-1")
    assert result is None
