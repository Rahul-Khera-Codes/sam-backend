import json
import uuid

from livekit.api import LiveKitAPI, AccessToken, VideoGrants
from livekit.protocol import room as proto_room
from livekit.protocol.agent_dispatch import CreateAgentDispatchRequest

from app.core.config import settings

# Agent name — read from settings (must match AGENT_NAME in agent/.env.local)
VOICE_AGENT_NAME = settings.agent_name


def generate_room_id() -> str:
    """Generates a unique LiveKit room name."""
    return f"call-{uuid.uuid4().hex[:12]}"


async def create_room(room_id: str) -> dict:
    """
    Creates a LiveKit room for a call.
    Returns room metadata.
    """
    api = LiveKitAPI(
        url=settings.livekit_url,
        api_key=settings.livekit_api_key,
        api_secret=settings.livekit_api_secret,
    )
    try:
        request = proto_room.CreateRoomRequest(
            name=room_id,
            empty_timeout=300,   # auto-close after 5 min if empty
            max_participants=2,  # caller + AI agent only
        )
        room = await api.room.create_room(request)
        # Log to stdout so it appears in Docker/uvicorn output (app has no logging config)
        print(f"[LiveKit] room created name={room.name} sid={room.sid}", flush=True)
        return {"room_name": room.name, "room_sid": room.sid}
    finally:
        await api.aclose()


async def create_agent_dispatch(
    room_id: str,
    *,
    metadata: dict | None = None,
) -> None:
    """
    Explicitly dispatch the voice-agent to a room.
    Required when using LiveKit Agents with agent_name (no automatic dispatch).
    Call this after creating the room so the agent joins when the user connects.
    """
    api = LiveKitAPI(
        url=settings.livekit_url,
        api_key=settings.livekit_api_key,
        api_secret=settings.livekit_api_secret,
    )
    try:
        req = CreateAgentDispatchRequest(
            agent_name=VOICE_AGENT_NAME,
            room=room_id,
            metadata=json.dumps(metadata) if metadata else "",
        )
        await api.agent_dispatch.create_dispatch(req)
        print(f"[LiveKit] agent dispatch created room={room_id} agent={VOICE_AGENT_NAME}", flush=True)
    finally:
        await api.aclose()


def generate_user_token(
    room_id: str,
    participant_name: str,
    *,
    metadata: dict | None = None,
) -> str:
    """
    Generates a LiveKit access token for the frontend user (caller).
    The frontend uses this token to join the room.
    If metadata is provided (e.g. call_id, business_id, location_id), it is
    set on the token so the LiveKit Agents voice-agent can read participant.metadata.
    """
    token = (
        AccessToken(
            api_key=settings.livekit_api_key,
            api_secret=settings.livekit_api_secret,
        )
        .with_identity(participant_name)
        .with_name(participant_name)
        .with_grants(
            VideoGrants(
                room_join=True,
                room=room_id,
                can_publish=True,
                can_subscribe=True,
                can_update_own_metadata=True,  # match working uni project: metadata on token applies
            )
        )
    )
    if metadata:
        token = token.with_metadata(json.dumps(metadata))
    return token.to_jwt()


def generate_agent_token(room_id: str) -> str:
    """
    Generates a LiveKit access token for the AI agent worker.
    The worker uses this to join the room as a bot participant.
    """
    token = (
        AccessToken(
            api_key=settings.livekit_api_key,
            api_secret=settings.livekit_api_secret,
        )
        .with_identity("ai-agent")
        .with_name("AI Agent")
        .with_grants(
            VideoGrants(
                room_join=True,
                room=room_id,
                can_publish=True,
                can_subscribe=True,
                agent=True,
            )
        )
    )
    return token.to_jwt()


async def create_sip_participant(
    room_id: str,
    to_number: str,
    from_number: str,
    *,
    participant_identity: str | None = None,
) -> dict:
    """
    Dials a PSTN number into an existing LiveKit room via the outbound SIP trunk.
    Returns the SIP participant info dict.
    """
    from livekit.protocol.sip import CreateSIPParticipantRequest

    api = LiveKitAPI(
        url=settings.livekit_url,
        api_key=settings.livekit_api_key,
        api_secret=settings.livekit_api_secret,
    )
    try:
        req = CreateSIPParticipantRequest(
            sip_trunk_id=settings.livekit_sip_outbound_trunk_id,
            sip_call_to=to_number,
            sip_number=from_number,
            room_name=room_id,
            participant_identity=participant_identity or f"sip-{to_number.replace('+', '')}",
            participant_name="Customer",
        )
        participant = await api.sip.create_sip_participant(req)
        print(f"[LiveKit] SIP participant dialled to={to_number} room={room_id}", flush=True)
        return {
            "participant_identity": participant.participant_identity,
            "sip_call_id": getattr(participant, "sip_call_id", ""),
        }
    finally:
        await api.aclose()


async def end_room(room_id: str) -> None:
    """Deletes/closes a LiveKit room."""
    api = LiveKitAPI(
        url=settings.livekit_url,
        api_key=settings.livekit_api_key,
        api_secret=settings.livekit_api_secret,
    )
    try:
        request = proto_room.DeleteRoomRequest(room=room_id)
        await api.room.delete_room(request)
    finally:
        await api.aclose()
