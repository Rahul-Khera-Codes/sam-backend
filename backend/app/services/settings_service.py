"""
Shared agent_settings feature-flag lookup for backend routers/services.
Mirrors the location-scoped semantics used by app/routers/settings.py
(_apply_location_filter) and the voice agent's own
agent/supabase_helpers.py::_is_feature_enabled_for_location.
"""
import logging

from app.core.supabase import supabase_admin

logger = logging.getLogger(__name__)


def is_feature_enabled(
    business_id: str,
    location_id: str | None,
    feature_key: str,
    default: bool = True,
) -> bool:
    """Check an agent_settings feature flag for a specific location. No fallback to business level."""
    if not business_id:
        return default
    try:
        query = (
            supabase_admin.table("agent_settings")
            .select("is_enabled")
            .eq("business_id", business_id)
            .eq("feature_key", feature_key)
        )
        if location_id:
            query = query.eq("location_id", location_id)
        else:
            query = query.is_("location_id", "null")
        result = query.limit(1).execute()
        data = result.data or []
        if data:
            return bool(data[0].get("is_enabled", default))
    except Exception as e:
        logger.warning("Could not check feature flag %s: %s", feature_key, e)
    return default
