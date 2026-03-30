#!/usr/bin/env python3
"""
Debug Script 3: Create a LiveKit room and verify the agent picks it up
=======================================================================
Creates a real room in the LiveKit project and waits to see if the agent
worker automatically joins. This verifies agent dispatch without SIP.

Run from sam-backend root (while agent is running):
  python scripts/debug_agent_dispatch.py
"""
import asyncio
import os
import time
from dotenv import load_dotenv

load_dotenv("backend/.env")

LK_URL    = os.getenv("LIVEKIT_URL", "")
LK_KEY    = os.getenv("LIVEKIT_API_KEY", "")
LK_SECRET = os.getenv("LIVEKIT_API_SECRET", "")

TEST_ROOM = f"debug-room-{int(time.time())}"


async def main():
    from livekit import api

    print("=" * 60)
    print("  Agent Dispatch Debug")
    print("=" * 60)
    print(f"  LiveKit: {LK_URL}")
    print(f"  Room:    {TEST_ROOM}")
    print()

    lk = api.LiveKitAPI(url=LK_URL, api_key=LK_KEY, api_secret=LK_SECRET)
    try:
        # Create test room
        room = await lk.room.create_room(api.CreateRoomRequest(name=TEST_ROOM))
        print(f"  ✅ Room created: {room.name} ({room.sid})")
        print(f"  Waiting 10s for agent to join...\n")

        # Poll for participants
        for i in range(10):
            await asyncio.sleep(1)
            participants = await lk.room.list_participants(
                api.ListParticipantsRequest(room=TEST_ROOM)
            )
            plist = getattr(participants, "participants", [])
            agent_participants = [p for p in plist if p.kind == 3 or p.identity.startswith("agent")]
            if agent_participants:
                print(f"  ✅ Agent joined after {i+1}s!")
                for p in agent_participants:
                    print(f"     Agent: {p.identity} ({p.sid}) kind={p.kind}")
                break
            else:
                all_p = [p.identity for p in plist]
                print(f"  [{i+1}s] Participants: {all_p or 'none'}")
        else:
            print(f"\n  ❌ Agent did NOT join within 10s")
            print(f"     → Agent worker may not be running or connected to this project")
            print(f"     → Check agent logs for 'registered worker' with url={LK_URL}")

    finally:
        # Clean up
        try:
            await lk.room.delete_room(api.DeleteRoomRequest(room=TEST_ROOM))
            print(f"\n  🗑  Room deleted")
        except Exception:
            pass
        await lk.aclose()


if __name__ == "__main__":
    asyncio.run(main())
