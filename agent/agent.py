"""
SAM Voice Agent — LiveKit Agents (Realtime) entrypoint.
Uses the official Voice AI quickstart pattern: AgentServer + AgentSession + OpenAI Realtime.
Reads business_id, location_id, call_id from participant metadata (set by backend token)
and builds a company/location-aware welcome.
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


def build_instructions(business_id: str | None, location_id: str | None) -> str:
    """Build instructions with company name and location when available."""
    company_name = "your company"
    location_phrase = ""
    supabase = _get_supabase()
    if supabase and business_id:
        try:
            r = supabase.table("businesses").select("*").eq("id", business_id).limit(1).execute()
            data = getattr(r, "data", None) or []
            row = data[0] if isinstance(data, list) and data else None
            if isinstance(row, dict) and row.get("name"):
                company_name = row["name"]
        except Exception as e:
            logger.warning("Failed to fetch business: %s", e)
    if supabase and location_id:
        try:
            r = supabase.table("locations").select("*").eq("id", location_id).limit(1).execute()
            data = getattr(r, "data", None) or []
            row = data[0] if isinstance(data, list) and data else None
            if isinstance(row, dict):
                parts = [row.get("name"), row.get("city"), row.get("state"), row.get("country")]
                spoken = ", ".join(p for p in parts if p)
                if spoken:
                    location_phrase = f" in {spoken}"
        except Exception as e:
            logger.warning("Failed to fetch location: %s", e)
    welcome = (
        f"You are the AI phone receptionist for {company_name}{location_phrase}. "
        "Always start the call with a short, friendly welcome that includes the business name"
    )
    if location_phrase:
        welcome += " and the location"
    welcome += (
        ". Example: \"Thank you for calling "
        f"{company_name}{location_phrase}, how can I help you today?\" "
        "Then continue the conversation following these rules:\n"
    )
    return welcome + DEFAULT_INSTRUCTIONS.strip()


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
