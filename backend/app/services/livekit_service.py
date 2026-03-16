import uuid

from livekit.api import LiveKitAPI, AccessToken, VideoGrants
from livekit.protocol import room as proto_room

from app.core.config import settings


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


def generate_user_token(room_id: str, participant_name: str) -> str:
    """
    Generates a LiveKit access token for the frontend user (caller).
    The frontend uses this token to join the room.
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
            )
        )
    )
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
