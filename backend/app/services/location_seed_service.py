"""
Location Seed Service
=====================
When a new location is created, copies business-wide data into
location-specific rows so the location starts fully configured.

This is a ONE-TIME copy. After seeding, the location's data is
independent — changes to one location don't affect another.

NOTE: brand_voice_profiles is NOT seeded — it stays business-wide (Global Settings).
"""

import logging
from app.core.supabase import supabase_admin

logger = logging.getLogger(__name__)


async def seed_location_data(business_id: str, location_id: str) -> dict:
    """
    Copy business-wide defaults into location-specific rows for a newly
    created location. Returns a summary of what was seeded.

    Call this immediately after inserting a new row into the `locations` table.
    """
    summary = {
        "business_hours": 0,
        "agent_settings": 0,
        "agent_state": 0,
        "communication_settings": 0,
        "location_services": 0,
        "knowledge_base": 0,
    }

    # ── business_hours ───────────────────────────────────────────────────
    try:
        bh = (
            supabase_admin.table("business_hours")
            .select("business_id, day_of_week, is_open, open_time, close_time")
            .eq("business_id", business_id)
            .is_("location_id", "null")
            .execute()
        )
        if bh.data:
            rows = [
                {**row, "location_id": location_id}
                for row in bh.data
            ]
            for row in rows:
                row.pop("id", None)
            supabase_admin.table("business_hours").insert(rows).execute()
            summary["business_hours"] = len(rows)
    except Exception as e:
        logger.warning("Seed business_hours failed: %s", e)

    # ── agent_settings ───────────────────────────────────────────────────
    try:
        asettings = (
            supabase_admin.table("agent_settings")
            .select("business_id, feature_key, is_enabled, config_value, updated_by")
            .eq("business_id", business_id)
            .is_("location_id", "null")
            .execute()
        )
        if asettings.data:
            rows = [
                {**row, "location_id": location_id}
                for row in asettings.data
            ]
            for row in rows:
                row.pop("id", None)
            supabase_admin.table("agent_settings").insert(rows).execute()
            summary["agent_settings"] = len(rows)
    except Exception as e:
        logger.warning("Seed agent_settings failed: %s", e)

    # ── agent_state ──────────────────────────────────────────────────────
    try:
        astate = (
            supabase_admin.table("agent_state")
            .select("business_id, is_active, toggled_at, toggled_by")
            .eq("business_id", business_id)
            .is_("location_id", "null")
            .execute()
        )
        if astate.data:
            row = {**astate.data[0], "location_id": location_id}
            row.pop("id", None)
            supabase_admin.table("agent_state").insert(row).execute()
            summary["agent_state"] = 1
        else:
            supabase_admin.table("agent_state").insert({
                "business_id": business_id,
                "location_id": location_id,
                "is_active": True,
            }).execute()
            summary["agent_state"] = 1
    except Exception as e:
        logger.warning("Seed agent_state failed: %s", e)

    # ── communication_settings ───────────────────────────────────────────
    try:
        cs = (
            supabase_admin.table("communication_settings")
            .select("business_id, channel, type, is_enabled, days_offset, script, updated_by")
            .eq("business_id", business_id)
            .is_("location_id", "null")
            .execute()
        )
        if cs.data:
            rows = [
                {**row, "location_id": location_id}
                for row in cs.data
            ]
            for row in rows:
                row.pop("id", None)
            supabase_admin.table("communication_settings").insert(rows).execute()
            summary["communication_settings"] = len(rows)
    except Exception as e:
        logger.warning("Seed communication_settings failed: %s", e)

    # ── location_services (copy all active services) ─────────────────────
    try:
        services = (
            supabase_admin.table("services")
            .select("id")
            .eq("business_id", business_id)
            .eq("is_active", True)
            .execute()
        )
        if services.data:
            rows = [
                {
                    "location_id": location_id,
                    "service_id": svc["id"],
                    "business_id": business_id,
                    "is_active": True,
                }
                for svc in services.data
            ]
            supabase_admin.table("location_services").insert(rows).execute()
            summary["location_services"] = len(rows)
    except Exception as e:
        logger.warning("Seed location_services failed: %s", e)

    # ── knowledge_base ───────────────────────────────────────────────────
    try:
        kb = (
            supabase_admin.table("knowledge_base")
            .select("business_id, title, text_content, content_type")
            .eq("business_id", business_id)
            .eq("content_type", "text")
            .is_("location_id", "null")
            .execute()
        )
        if kb.data:
            rows = [
                {**row, "location_id": location_id}
                for row in kb.data
            ]
            for row in rows:
                row.pop("id", None)
            supabase_admin.table("knowledge_base").insert(rows).execute()
            summary["knowledge_base"] = len(rows)
    except Exception as e:
        logger.warning("Seed knowledge_base failed: %s", e)

    logger.info(
        "Location %s seeded from business %s: %s",
        location_id, business_id, summary,
    )
    return summary
