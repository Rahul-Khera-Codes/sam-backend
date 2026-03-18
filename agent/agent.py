"""
SAM Voice Agent — LiveKit Agents (Realtime) entrypoint.
Reads business_id, location_id, call_id from participant metadata (set by backend token)
and builds instructions from:
- Business name + location (welcome)
- Global settings (businesses: language, country, date_format, time_format)
- Brand voice (brand_voice_profiles: tone, style, vocabulary, do_not_say, sample_responses)
"""

import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from livekit import agents, rtc
from livekit.agents import AgentServer, AgentSession, Agent, room_io
from livekit.plugins import (
    openai,
    noise_cancellation,
)


load_dotenv(".env.local")

logger = logging.getLogger("voice-agent")

DEFAULT_INSTRUCTIONS = """
You are a helpful AI customer service assistant.
Be friendly, professional, and concise.
If you cannot help with something, offer to transfer the caller to a human agent.
Always confirm any appointments or bookings back to the caller clearly.

Booking and rescheduling: You can help customers book new appointments or reschedule existing ones.
When they want to book: ask for preferred location (if the business has multiple), date, time, and service or staff preference if relevant; repeat back to confirm.
When they want to reschedule: ask for their name or phone so you can look up the appointment, then the new date and time; confirm back.
Do not make up availability—offer to create or update the appointment and, if your system supports it, say you will confirm shortly, or transfer to the front desk to finalize.
"""


def _get_supabase():
    try:
        from supabase import create_client
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        if url and key:
            return create_client(url, key)
    except Exception as e:
        logger.warning("Supabase not available for agent: %s", e)
    return None


def _fetch_business(supabase, business_id: str) -> dict | None:
    """Fetch business row (global settings: language, country, date_format, time_format)."""
    if not supabase or not business_id:
        return None
    try:
        r = supabase.table("businesses").select("*").eq("id", business_id).limit(1).execute()
        data = getattr(r, "data", None) or []
        return data[0] if isinstance(data, list) and data and isinstance(data[0], dict) else None
    except Exception as e:
        logger.warning("Failed to fetch business: %s", e)
        return None


def _fetch_location(supabase, location_id: str) -> dict | None:
    """Fetch location row for spoken address."""
    if not supabase or not location_id:
        return None
    try:
        r = supabase.table("locations").select("*").eq("id", location_id).limit(1).execute()
        data = getattr(r, "data", None) or []
        return data[0] if isinstance(data, list) and data and isinstance(data[0], dict) else None
    except Exception as e:
        logger.warning("Failed to fetch location: %s", e)
        return None


def _fetch_locations(supabase, business_id: str) -> list[dict]:
    """Fetch all active locations for the business (for listing and booking)."""
    if not supabase or not business_id:
        return []
    try:
        r = (
            supabase.table("locations")
            .select("id, name, address, phone")
            .eq("business_id", business_id)
            .execute()
        )
        data = getattr(r, "data", None) or []
        return data if isinstance(data, list) else []
    except Exception as e:
        logger.warning("Failed to fetch locations: %s", e)
        return []


def _fetch_employees_by_location(supabase, business_id: str) -> dict[str, list[str]]:
    """Fetch employees (staff) per location: location_id -> list of display names. Uses user_roles + user_locations + profiles."""
    if not supabase or not business_id:
        return {}
    try:
        ur = supabase.table("user_roles").select("user_id").eq("business_id", business_id).execute()
        user_ids = [row["user_id"] for row in (getattr(ur, "data", None) or []) if isinstance(row, dict) and row.get("user_id")]
        if not user_ids:
            return {}
        ul = supabase.table("user_locations").select("user_id, location_id").in_("user_id", user_ids).execute()
        pairs = [(row["user_id"], row["location_id"]) for row in (getattr(ul, "data", None) or []) if isinstance(row, dict) and row.get("location_id")]
        if not pairs:
            return {}
        pf = supabase.table("profiles").select("id, first_name, last_name").in_("id", user_ids).execute()
        names = {}
        for row in getattr(pf, "data", None) or []:
            if isinstance(row, dict) and row.get("id"):
                first = (row.get("first_name") or "").strip()
                last = (row.get("last_name") or "").strip()
                names[row["id"]] = f"{first} {last}".strip() or "Staff"
        result: dict[str, list[str]] = {}
        for user_id, loc_id in pairs:
            name = names.get(user_id)
            if name and loc_id:
                result.setdefault(loc_id, []).append(name)
        return result
    except Exception as e:
        logger.warning("Failed to fetch employees by location: %s", e)
        return {}


def _fetch_brand_voice(supabase, business_id: str) -> dict | None:
    """Fetch active brand voice profile (tone, style, vocabulary, do_not_say, sample_responses)."""
    if not supabase or not business_id:
        return None
    try:
        r = (
            supabase.table("brand_voice_profiles")
            .select("*")
            .eq("business_id", business_id)
            .eq("is_active", True)
            .limit(1)
            .execute()
        )
        data = getattr(r, "data", None) or []
        return data[0] if isinstance(data, list) and data and isinstance(data[0], dict) else None
    except Exception as e:
        logger.warning("Failed to fetch brand voice: %s", e)
        return None


def _format_global_settings(business: dict) -> str:
    """Format global settings (language, region, date/time format) for instructions."""
    parts = []
    lang = business.get("language")
    country = business.get("country")
    date_fmt = business.get("date_format")
    time_fmt = business.get("time_format")
    if lang or country:
        locale = " and ".join(p for p in [lang, country] if p)
        if locale:
            parts.append(f"Use the business language and region: {locale}. Speak in that language unless the caller uses another.")
    if date_fmt:
        parts.append(f"When stating dates use this format: {date_fmt}.")
    if time_fmt:
        parts.append(f"When stating times use {time_fmt} format.")
    if not parts:
        return ""
    return "Global settings: " + " ".join(parts) + "\n\n"


def _format_brand_voice(profile: dict) -> str:
    """Format brand voice (tone, style, vocabulary, do_not_say, sample_responses) for instructions."""
    parts = []
    tone = profile.get("tone")
    style = profile.get("style")
    if tone:
        parts.append(f"Tone: {tone}.")
    if style:
        parts.append(f"Style: {style}.")

    vocabulary = profile.get("vocabulary")
    if vocabulary is not None:
        if isinstance(vocabulary, str):
            try:
                vocabulary = json.loads(vocabulary)
            except json.JSONDecodeError:
                vocabulary = None
        if isinstance(vocabulary, list) and vocabulary:
            preferred = []
            avoid = []
            for item in vocabulary:
                if isinstance(item, dict):
                    if item.get("preferred"):
                        preferred.append(str(item["preferred"]))
                    if item.get("avoid"):
                        avoid.append(str(item["avoid"]))
            if preferred:
                parts.append(f"Prefer saying: {', '.join(preferred)}.")
            if avoid:
                parts.append(f"Avoid saying: {', '.join(avoid)}.")

    do_not_say = profile.get("do_not_say")
    if do_not_say and isinstance(do_not_say, list):
        phrases = [str(p) for p in do_not_say if p]
        if phrases:
            parts.append(f"Never say these words or phrases: {', '.join(phrases)}.")

    sample_responses = profile.get("sample_responses")
    if sample_responses is not None:
        if isinstance(sample_responses, str):
            try:
                sample_responses = json.loads(sample_responses)
            except json.JSONDecodeError:
                sample_responses = None
        if isinstance(sample_responses, list) and sample_responses:
            examples = []
            for item in sample_responses[:3]:
                if isinstance(item, dict) and item.get("scenario") and item.get("response"):
                    examples.append(f"Example ({item.get('scenario')}): \"{item.get('response')}\"")
            if examples:
                parts.append("Follow the style of these example responses: " + "; ".join(examples) + ".")

    if not parts:
        return ""
    return "Brand voice: " + " ".join(parts) + "\n\n"


def _format_locations_and_employees(
    locations: list[dict],
    employees_by_location: dict[str, list[str]],
) -> str:
    """Format locations and staff per location for booking/reschedule context."""
    if not locations:
        return ""
    lines = []
    for loc in locations:
        loc_id = loc.get("id")
        name = loc.get("name") or "Unknown"
        address = loc.get("address") or ""
        phone = loc.get("phone") or ""
        parts = [f"Location: {name}"]
        if address:
            parts.append(f"address: {address}")
        if phone:
            parts.append(f"phone: {phone}")
        staff = (employees_by_location.get(loc_id) if loc_id else []) or []
        if staff:
            parts.append(f"staff: {', '.join(staff)}")
        lines.append("; ".join(parts))
    return "Locations and staff (use for booking and rescheduling): " + " | ".join(lines) + "\n\n"


def build_instructions(business_id: str | None, location_id: str | None) -> str:
    """Build instructions from business, location, global settings, and brand voice."""
    company_name = "your company"
    location_phrase = ""
    global_block = ""
    brand_block = ""
    locations_block = ""
    supabase = _get_supabase()

    business = _fetch_business(supabase, business_id) if business_id else None
    if business and business.get("name"):
        company_name = business["name"]
        global_block = _format_global_settings(business)
    brand = _fetch_brand_voice(supabase, business_id) if business_id else None
    if brand:
        brand_block = _format_brand_voice(brand)
    if business_id:
        locations = _fetch_locations(supabase, business_id)
        employees_by_location = _fetch_employees_by_location(supabase, business_id)
        locations_block = _format_locations_and_employees(locations, employees_by_location)

    if supabase and location_id:
        loc = _fetch_location(supabase, location_id)
        if loc:
            parts = [loc.get("name"), loc.get("city"), loc.get("state"), loc.get("country")]
            spoken = ", ".join(p for p in parts if p)
            if spoken:
                location_phrase = f" in {spoken}"

    welcome = (
        f"You are the AI phone receptionist for {company_name}{location_phrase}. "
        "Always start the call with a short, friendly welcome that includes the business name"
    )
    if location_phrase:
        welcome += " and the location"
    welcome += (
        ". Example: \"Thank you for calling "
        f"{company_name}{location_phrase}, how can I help you today?\" "
        "Then continue the conversation following these rules:\n\n"
    )
    return welcome + global_block + brand_block + locations_block + DEFAULT_INSTRUCTIONS.strip()


class Assistant(Agent):
    def __init__(self, instructions: str = DEFAULT_INSTRUCTIONS) -> None:
        super().__init__(instructions=instructions)


server = AgentServer()


# No agent_name = automatic dispatch (like uni-livekit-cloud-voice-agent).
# When a participant joins the room, LiveKit dispatches this agent automatically.
@server.rtc_session()
async def voice_agent(ctx: agents.JobContext):
    await ctx.connect(auto_subscribe=agents.AutoSubscribe.AUDIO_ONLY)
    participant = await ctx.wait_for_participant()
    logger.info("Participant connected: %s", participant.identity)

    instructions = DEFAULT_INSTRUCTIONS
    raw_meta = participant.metadata
    if isinstance(raw_meta, str) and raw_meta:
        try:
            meta = json.loads(raw_meta)
            business_id = meta.get("business_id")
            location_id = meta.get("location_id")
            call_id = meta.get("call_id")
            if business_id or location_id:
                instructions = build_instructions(business_id, location_id)
                logger.info("Using business-aware instructions (call_id=%s)", call_id)
        except json.JSONDecodeError:
            logger.warning("Invalid participant metadata: %s", participant.metadata)

    session = AgentSession(
        llm=openai.realtime.RealtimeModel(),
        preemptive_generation=True,
    )
    assistant = Assistant(instructions=instructions)
    await session.start(
        room=ctx.room,
        agent=assistant,
        room_options=room_io.RoomOptions(
            audio_input=room_io.AudioInputOptions(
                noise_cancellation=lambda params: noise_cancellation.BVCTelephony() 
                    if params.participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP 
                    else noise_cancellation.BVC(),
                ),
        ),
    )
    await session.generate_reply()


if __name__ == "__main__":
    agents.cli.run_app(server)
