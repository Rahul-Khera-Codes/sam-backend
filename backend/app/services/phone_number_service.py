"""
Phone Number Service
====================
Handles Twilio number search/provisioning and LiveKit dispatch rule lifecycle.

All provisioning is done with the service-role Supabase client (bypasses RLS).
"""

import os
import logging
from typing import Optional

from livekit import api
from livekit.protocol.sip import (
    SIPDispatchRule,
    SIPDispatchRuleIndividual,
    SIPInboundTrunkInfo,
    CreateSIPDispatchRuleRequest,
    CreateSIPInboundTrunkRequest,
    DeleteSIPDispatchRuleRequest,
    DeleteSIPTrunkRequest,
    ListSIPDispatchRuleRequest,
    ListSIPInboundTrunkRequest,
)
from livekit.protocol.room import RoomConfiguration
from livekit.protocol.agent_dispatch import RoomAgentDispatch
from twilio.rest import Client as TwilioClient

from app.core.config import settings
from app.core.supabase import supabase_admin

logger = logging.getLogger(__name__)

# ── Twilio client (lazy singleton) ────────────────────────────────────────────

_twilio: Optional[TwilioClient] = None


def _get_twilio() -> TwilioClient:
    global _twilio
    if _twilio is None:
        _twilio = TwilioClient(settings.twilio_account_sid, settings.twilio_auth_token)
    return _twilio


# ── Number search ─────────────────────────────────────────────────────────────

def search_available_numbers(
    area_code: Optional[str] = None,
    country: str = "US",
    limit: int = 10,
) -> list[dict]:
    """
    Returns available Twilio phone numbers for purchase.
    Each item: { phone_number, friendly_name, locality, region, iso_country }
    """
    twilio = _get_twilio()
    kwargs: dict = {"limit": limit, "voice_enabled": True}
    if area_code:
        kwargs["area_code"] = area_code

    numbers = twilio.available_phone_numbers(country).local.list(**kwargs)
    return [
        {
            "phone_number": n.phone_number,
            "friendly_name": n.friendly_name,
            "locality": n.locality,
            "region": n.region,
            "iso_country": n.iso_country,
        }
        for n in numbers
    ]


# ── Provisioning ──────────────────────────────────────────────────────────────

async def provision_phone_number(
    business_id: str,
    location_id: Optional[str],
    phone_number: str,
) -> dict:
    """
    Full provisioning flow:
      1. Purchase Twilio number and assign to shared trunk
      2. Create LiveKit dispatch rule for this number
      3. Create/update LiveKit outbound trunk to include this number (first provision only)
      4. Insert row in business_phone_numbers

    Returns the new business_phone_numbers row dict.
    """
    twilio = _get_twilio()

    # Step 1: Purchase Twilio number
    logger.info(f"[provision] Purchasing Twilio number {phone_number} for business {business_id}")
    purchased = twilio.incoming_phone_numbers.create(
        phone_number=phone_number,
        trunk_sid=settings.twilio_trunk_sid,
    )
    twilio_number_sid = purchased.sid
    logger.info(f"[provision] Twilio number purchased: {twilio_number_sid}")

    # Step 2 & 3: LiveKit — dispatch rule + outbound trunk
    lk = api.LiveKitAPI(
        url=settings.livekit_url,
        api_key=settings.livekit_api_key,
        api_secret=settings.livekit_api_secret,
    )
    inbound_trunk_id: str = ""
    dispatch_rule_id: str = ""
    try:
        # Create per-number inbound trunk (numbers=[phone_number] satisfies LiveKit security)
        inbound_trunk_id = await _create_inbound_trunk(lk, phone_number)
        logger.info(f"[provision] Inbound trunk created: {inbound_trunk_id}")

        # Create dispatch rule for this number
        dispatch_rule_id = await _create_dispatch_rule(lk, phone_number, business_id, inbound_trunk_id)
        logger.info(f"[provision] Dispatch rule created: {dispatch_rule_id}")

        # Create or update outbound SIP trunk
        await _ensure_outbound_trunk(lk, phone_number)
    finally:
        await lk.aclose()

    # Step 4: Persist to DB
    row = {
        "business_id": business_id,
        "location_id": location_id,
        "phone_number": phone_number,
        "twilio_number_sid": twilio_number_sid,
        "twilio_trunk_sid": settings.twilio_trunk_sid,
        "livekit_inbound_trunk_id": inbound_trunk_id,
        "livekit_dispatch_rule_id": dispatch_rule_id,
        "is_active": True,
    }
    result = supabase_admin.table("business_phone_numbers").insert(row).execute()
    logger.info(f"[provision] DB row created: {result.data[0]['id']}")
    return result.data[0]


async def _create_inbound_trunk(lk: api.LiveKitAPI, phone_number: str) -> str:
    """Creates a per-number LiveKit inbound SIP trunk. Returns the trunk ID."""
    trunk = await lk.sip.create_sip_inbound_trunk(
        CreateSIPInboundTrunkRequest(
            trunk=SIPInboundTrunkInfo(
                name=f"SAM Inbound — {phone_number}",
                numbers=[phone_number],  # security: only accept calls to this number
            )
        )
    )
    return trunk.sip_trunk_id


async def _create_dispatch_rule(
    lk: api.LiveKitAPI,
    phone_number: str,
    business_id: str,
    inbound_trunk_id: str,
) -> str:
    """Creates a LiveKit SIP dispatch rule for the given phone number. Returns the rule ID."""
    resp = await lk.sip.create_sip_dispatch_rule(
        CreateSIPDispatchRuleRequest(
            name=f"SAM — {phone_number}",
            rule=SIPDispatchRule(
                dispatch_rule_individual=SIPDispatchRuleIndividual(room_prefix="call-", pin="")
            ),
            trunk_ids=[inbound_trunk_id],
            attributes={"business_id": business_id},
            room_config=RoomConfiguration(
                agents=[RoomAgentDispatch(agent_name=settings.agent_name)],
            ),
        )
    )
    return resp.sip_dispatch_rule_id


async def _ensure_outbound_trunk(lk: api.LiveKitAPI, phone_number: str) -> None:
    """
    Creates the LiveKit outbound SIP trunk if it doesn't exist yet (first number provision),
    or adds the new number to the existing outbound trunk.
    """
    from livekit.protocol.sip import (
        SIPOutboundTrunkInfo,
        CreateSIPOutboundTrunkRequest,
        GetSIPOutboundTrunkRequest,
        UpdateSIPOutboundTrunkRequest,
    )

    outbound_trunk_id = settings.livekit_sip_outbound_trunk_id

    if not outbound_trunk_id:
        # First number — create the outbound trunk
        logger.info("[provision] Creating LiveKit outbound SIP trunk (first number)...")
        trunk = await lk.sip.create_sip_outbound_trunk(
            CreateSIPOutboundTrunkRequest(
                trunk=SIPOutboundTrunkInfo(
                    name="SAM Outbound",
                    address=settings.twilio_term_domain,
                    numbers=[phone_number],
                    auth_username=settings.twilio_term_sip_username,
                    auth_password=settings.twilio_term_sip_password,
                )
            )
        )
        new_id = trunk.sip_trunk_id
        logger.info(f"[provision] Outbound trunk created: {new_id}")
        logger.warning(
            f"[provision] IMPORTANT: Set LIVEKIT_SIP_OUTBOUND_TRUNK_ID={new_id} in backend/.env"
        )
    else:
        # Add number to existing outbound trunk
        logger.info(f"[provision] Adding {phone_number} to existing outbound trunk {outbound_trunk_id}")
        existing = await lk.sip.get_sip_outbound_trunk(
            GetSIPOutboundTrunkRequest(sip_trunk_id=outbound_trunk_id)
        )
        updated_numbers = list(existing.trunk.numbers) + [phone_number]
        await lk.sip.update_sip_outbound_trunk(
            UpdateSIPOutboundTrunkRequest(
                trunk=SIPOutboundTrunkInfo(
                    sip_trunk_id=outbound_trunk_id,
                    numbers=updated_numbers,
                )
            )
        )
        logger.info(f"[provision] Outbound trunk updated with {phone_number}")


# ── Release ───────────────────────────────────────────────────────────────────

async def release_phone_number(phone_number_id: str) -> dict:
    """
    Release flow:
      1. Look up DB row
      2. Delete LiveKit dispatch rule
      3. Release Twilio number
      4. Soft-delete DB row (set is_active=False, released_at=now)

    Returns the updated DB row.
    """
    # Fetch row
    result = (
        supabase_admin.table("business_phone_numbers")
        .select("*")
        .eq("id", phone_number_id)
        .eq("is_active", True)
        .single()
        .execute()
    )
    if not result.data:
        raise ValueError(f"Phone number {phone_number_id} not found or already released")
    row = result.data

    # Delete LiveKit dispatch rule + inbound trunk
    if row.get("livekit_dispatch_rule_id") or row.get("livekit_inbound_trunk_id"):
        lk = api.LiveKitAPI(
            url=settings.livekit_url,
            api_key=settings.livekit_api_key,
            api_secret=settings.livekit_api_secret,
        )
        try:
            if row.get("livekit_dispatch_rule_id"):
                await lk.sip.delete_sip_dispatch_rule(
                    DeleteSIPDispatchRuleRequest(sip_dispatch_rule_id=row["livekit_dispatch_rule_id"])
                )
                logger.info(f"[release] Dispatch rule deleted: {row['livekit_dispatch_rule_id']}")
            if row.get("livekit_inbound_trunk_id"):
                await lk.sip.delete_sip_trunk(
                    DeleteSIPTrunkRequest(sip_trunk_id=row["livekit_inbound_trunk_id"])
                )
                logger.info(f"[release] Inbound trunk deleted: {row['livekit_inbound_trunk_id']}")
        except Exception as e:
            logger.warning(f"[release] Could not delete LiveKit SIP resources: {e}")
        finally:
            await lk.aclose()

    # Release Twilio number
    if row.get("twilio_number_sid"):
        try:
            _get_twilio().incoming_phone_numbers(row["twilio_number_sid"]).delete()
            logger.info(f"[release] Twilio number released: {row['twilio_number_sid']}")
        except Exception as e:
            logger.warning(f"[release] Could not release Twilio number: {e}")

    # Soft-delete in DB
    from datetime import datetime, timezone
    updated = (
        supabase_admin.table("business_phone_numbers")
        .update({"is_active": False, "released_at": datetime.now(timezone.utc).isoformat()})
        .eq("id", phone_number_id)
        .execute()
    )
    return updated.data[0]


# ── Query helpers ─────────────────────────────────────────────────────────────

def get_phone_numbers_for_business(business_id: str) -> list[dict]:
    """Returns all active phone numbers for a business."""
    result = (
        supabase_admin.table("business_phone_numbers")
        .select("*")
        .eq("business_id", business_id)
        .eq("is_active", True)
        .order("created_at", desc=False)
        .execute()
    )
    return result.data or []
