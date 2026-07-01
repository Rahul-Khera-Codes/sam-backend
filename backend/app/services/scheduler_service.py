"""
Scheduler service — hourly cron jobs for reminder and reschedule outbound calls.

Reminder calls (confirmation_reminder_calls feature flag):
  Every hour, find appointments happening in N days where reminder_called_at IS NULL.
  Trigger an outbound call to the customer with the configured message template.

Reschedule calls (reschedule_cancel_appointments feature flag):
  Every hour, find appointments cancelled exactly N days ago where reschedule_called_at IS NULL.
  Trigger an outbound call to offer rebooking.

Both jobs mark the timestamp column immediately before dialling to prevent double-calls
even if the job overlaps or the process restarts.
"""

import logging
from datetime import date, datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.supabase import supabase_admin
from app.services import livekit_service

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(timezone="UTC")

# ── Internal helpers ──────────────────────────────────────────────────────────

async def _trigger_outbound_call(
    *,
    business_id: str,
    location_id: str,
    to_phone: str,
    call_purpose: str,
    message_template: str,
    appointment_id: str,
) -> str | None:
    """
    Create a call record, dispatch the agent, and dial the customer via SIP.
    Returns call_id on success, None on failure.
    Mirrors the logic in POST /calls/outbound but runs in-process (no HTTP).
    """
    # Resolve the outbound trunk for this location
    trunk_row = (
        supabase_admin.table("business_phone_numbers")
        .select("phone_number, livekit_outbound_trunk_id")
        .eq("business_id", business_id)
        .eq("location_id", location_id)
        .eq("is_active", True)
        .neq("livekit_outbound_trunk_id", "")
        .limit(1)
        .execute()
    )
    if not trunk_row.data:
        logger.warning(
            "Scheduler: no outbound trunk for location %s — skipping appointment %s",
            location_id, appointment_id,
        )
        return None

    from_number = trunk_row.data[0]["phone_number"]
    outbound_trunk_id = trunk_row.data[0]["livekit_outbound_trunk_id"]

    try:
        room_id = livekit_service.generate_room_id()
        await livekit_service.create_room(room_id)

        call_row = supabase_admin.table("calls").insert({
            "business_id": business_id,
            "location_id": location_id,
            "caller_phone": to_phone,
            "caller_name": call_purpose,
            "direction": "outbound",
            "status": "initiating",
            "livekit_room_id": room_id,
            "started_at": datetime.now(timezone.utc).isoformat(),
        }).execute()

        if not call_row.data:
            logger.error("Scheduler: failed to create call record for appointment %s", appointment_id)
            return None

        call_id = call_row.data[0]["id"]

        await livekit_service.create_agent_dispatch(
            room_id,
            metadata={
                "call_id": call_id,
                "business_id": business_id,
                "location_id": location_id,
                "call_direction": "outbound",
                "call_purpose": call_purpose,
                "message_template": message_template,
            },
        )

        await livekit_service.create_sip_participant(
            room_id,
            to_number=to_phone,
            from_number=from_number,
            outbound_trunk_id=outbound_trunk_id,
        )

        supabase_admin.table("calls").update({"status": "active"}).eq("id", call_id).execute()
        return call_id

    except Exception as e:
        logger.error(
            "Scheduler: outbound call failed for appointment %s: %s",
            appointment_id, e,
        )
        return None


# ── Cron jobs ─────────────────────────────────────────────────────────────────

async def run_reminder_calls() -> None:
    """
    Trigger reminder calls for appointments happening N days from today.
    Reads per-location config from agent_settings (feature_key=confirmation_reminder_calls).
    """
    logger.info("Scheduler: reminder calls check started")
    today = date.today()

    try:
        cfg_rows = (
            supabase_admin.table("agent_settings")
            .select("business_id, location_id, config_value")
            .eq("feature_key", "confirmation_reminder_calls")
            .eq("is_enabled", True)
            .execute()
        )
    except Exception as e:
        logger.error("Scheduler: failed to fetch reminder call configs: %s", e)
        return

    for cfg in (cfg_rows.data or []):
        business_id = cfg["business_id"]
        location_id = cfg["location_id"]
        if not location_id:
            continue
        config = cfg.get("config_value") or {}
        days = int(config.get("days") or 1)
        template = config.get("message_template") or (
            "Hi, this is a reminder about your upcoming appointment. "
            "We look forward to seeing you!"
        )

        target_date = (today + timedelta(days=days)).isoformat()

        try:
            appts = (
                supabase_admin.table("appointments")
                .select("id, client_phone, client_name, service, appointment_date")
                .eq("business_id", business_id)
                .eq("location_id", location_id)
                .eq("appointment_date", target_date)
                .neq("status", "cancelled")
                .is_("reminder_called_at", "null")
                .execute()
            )
        except Exception as e:
            logger.error(
                "Scheduler: appointment query failed for location %s: %s", location_id, e
            )
            continue

        for appt in (appts.data or []):
            phone = (appt.get("client_phone") or "").strip()
            if not phone:
                logger.info(
                    "Scheduler: skipping reminder for appointment %s — no client phone", appt["id"]
                )
                continue

            # Mark immediately to prevent double-calling on restart/overlap
            try:
                supabase_admin.table("appointments").update({
                    "reminder_called_at": datetime.now(timezone.utc).isoformat(),
                }).eq("id", appt["id"]).execute()
            except Exception as e:
                logger.error("Scheduler: failed to mark reminder_called_at for %s: %s", appt["id"], e)
                continue

            call_id = await _trigger_outbound_call(
                business_id=business_id,
                location_id=location_id,
                to_phone=phone,
                call_purpose="appointment_reminder",
                message_template=template,
                appointment_id=appt["id"],
            )

            if call_id:
                logger.info(
                    "Scheduler: reminder call triggered — appointment=%s call=%s client=%s date=%s",
                    appt["id"], call_id, appt.get("client_name"), target_date,
                )
            else:
                logger.warning(
                    "Scheduler: reminder call failed — appointment=%s", appt["id"]
                )

    logger.info("Scheduler: reminder calls check finished")


async def run_reschedule_calls() -> None:
    """
    Trigger reschedule calls for appointments cancelled exactly N days ago.
    Reads per-location config from agent_settings (feature_key=reschedule_cancel_appointments).
    """
    logger.info("Scheduler: reschedule calls check started")
    today = date.today()

    try:
        cfg_rows = (
            supabase_admin.table("agent_settings")
            .select("business_id, location_id, config_value")
            .eq("feature_key", "reschedule_cancel_appointments")
            .eq("is_enabled", True)
            .execute()
        )
    except Exception as e:
        logger.error("Scheduler: failed to fetch reschedule call configs: %s", e)
        return

    for cfg in (cfg_rows.data or []):
        business_id = cfg["business_id"]
        location_id = cfg["location_id"]
        if not location_id:
            continue
        config = cfg.get("config_value") or {}
        days = int(config.get("days") or 3)
        template = config.get("message_template") or (
            "Hi, we noticed you cancelled your recent appointment. "
            "We'd love to help you reschedule — would any of our available times work for you?"
        )

        target_date = (today - timedelta(days=days)).isoformat()
        window_start = f"{target_date}T00:00:00+00:00"
        window_end   = f"{target_date}T23:59:59+00:00"

        try:
            appts = (
                supabase_admin.table("appointments")
                .select("id, client_phone, client_name, service, appointment_date")
                .eq("business_id", business_id)
                .eq("location_id", location_id)
                .eq("status", "cancelled")
                .gte("updated_at", window_start)
                .lte("updated_at", window_end)
                .is_("reschedule_called_at", "null")
                .execute()
            )
        except Exception as e:
            logger.error(
                "Scheduler: reschedule query failed for location %s: %s", location_id, e
            )
            continue

        for appt in (appts.data or []):
            phone = (appt.get("client_phone") or "").strip()
            if not phone:
                logger.info(
                    "Scheduler: skipping reschedule for appointment %s — no client phone", appt["id"]
                )
                continue

            try:
                supabase_admin.table("appointments").update({
                    "reschedule_called_at": datetime.now(timezone.utc).isoformat(),
                }).eq("id", appt["id"]).execute()
            except Exception as e:
                logger.error("Scheduler: failed to mark reschedule_called_at for %s: %s", appt["id"], e)
                continue

            call_id = await _trigger_outbound_call(
                business_id=business_id,
                location_id=location_id,
                to_phone=phone,
                call_purpose="appointment_reschedule",
                message_template=template,
                appointment_id=appt["id"],
            )

            if call_id:
                logger.info(
                    "Scheduler: reschedule call triggered — appointment=%s call=%s client=%s cancelled_on=%s",
                    appt["id"], call_id, appt.get("client_name"), target_date,
                )
            else:
                logger.warning(
                    "Scheduler: reschedule call failed — appointment=%s", appt["id"]
                )

    logger.info("Scheduler: reschedule calls check finished")


async def run_noshow_calls() -> None:
    """
    Trigger follow-up calls for appointments marked no_show N days ago.
    Reads per-location config from agent_settings (feature_key=noshow_followup).
    """
    logger.info("Scheduler: no-show calls check started")
    today = date.today()

    try:
        cfg_rows = (
            supabase_admin.table("agent_settings")
            .select("business_id, location_id, config_value")
            .eq("feature_key", "noshow_followup")
            .eq("is_enabled", True)
            .execute()
        )
    except Exception as e:
        logger.error("Scheduler: failed to fetch no-show call configs: %s", e)
        return

    for cfg in (cfg_rows.data or []):
        business_id = cfg["business_id"]
        location_id = cfg["location_id"]
        if not location_id:
            continue
        config = cfg.get("config_value") or {}
        days = int(config.get("days") or 1)
        template = config.get("message_template") or (
            "Hi, we noticed you missed your recent appointment. "
            "We'd love to help you reschedule — would any of our available times work for you?"
        )

        target_date = (today - timedelta(days=days)).isoformat()

        try:
            appts = (
                supabase_admin.table("appointments")
                .select("id, client_phone, client_name, service, appointment_date")
                .eq("business_id", business_id)
                .eq("location_id", location_id)
                .eq("status", "no_show")
                .eq("appointment_date", target_date)
                .is_("noshow_called_at", "null")
                .execute()
            )
        except Exception as e:
            logger.error(
                "Scheduler: no-show query failed for location %s: %s", location_id, e
            )
            continue

        for appt in (appts.data or []):
            phone = (appt.get("client_phone") or "").strip()
            if not phone:
                logger.info(
                    "Scheduler: skipping no-show call for appointment %s — no client phone", appt["id"]
                )
                continue

            # Mark immediately to prevent double-calling on restart/overlap
            try:
                supabase_admin.table("appointments").update({
                    "noshow_called_at": datetime.now(timezone.utc).isoformat(),
                }).eq("id", appt["id"]).execute()
            except Exception as e:
                logger.error("Scheduler: failed to mark noshow_called_at for %s: %s", appt["id"], e)
                continue

            call_id = await _trigger_outbound_call(
                business_id=business_id,
                location_id=location_id,
                to_phone=phone,
                call_purpose="noshow_followup",
                message_template=template,
                appointment_id=appt["id"],
            )

            if call_id:
                logger.info(
                    "Scheduler: no-show call triggered — appointment=%s call=%s client=%s date=%s",
                    appt["id"], call_id, appt.get("client_name"), target_date,
                )
            else:
                logger.warning(
                    "Scheduler: no-show call failed — appointment=%s", appt["id"]
                )

    logger.info("Scheduler: no-show calls check finished")


# ── Scheduler lifecycle ───────────────────────────────────────────────────────

def start_scheduler() -> None:
    scheduler.add_job(
        run_reminder_calls,
        trigger="interval",
        hours=1,
        id="reminder_calls",
        replace_existing=True,
        misfire_grace_time=300,  # allow up to 5 min late start
    )
    scheduler.add_job(
        run_reschedule_calls,
        trigger="interval",
        hours=1,
        id="reschedule_calls",
        replace_existing=True,
        misfire_grace_time=300,
    )
    scheduler.add_job(
        run_noshow_calls,
        trigger="interval",
        hours=1,
        id="noshow_calls",
        replace_existing=True,
        misfire_grace_time=300,
    )
    scheduler.start()
    logger.info("Scheduler started — reminder + reschedule + no-show calls run every hour")


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
