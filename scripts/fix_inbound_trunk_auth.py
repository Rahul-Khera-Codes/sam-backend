#!/usr/bin/env python3
"""
Fix: Remove SIP digest auth from LiveKit inbound trunk
=======================================================
The inbound trunk was created with auth_username/auth_password, which causes
LiveKit to send a 401 challenge to Twilio. Twilio's origination URL has no
credentials to respond → calls fail with "busy".

This script:
  1. Reads the existing inbound trunk ID from .env
  2. Creates a new inbound trunk (same IP allowlist, NO auth)
  3. Migrates all dispatch rules to point to the new trunk
  4. Deletes the old trunk
  5. Prints the new trunk ID to update in backend/.env and agent/.env.local

Usage:
  cd sam-backend
  python scripts/fix_inbound_trunk_auth.py
"""

import asyncio
import os
import sys

from dotenv import load_dotenv
from livekit import api
from livekit.protocol.sip import (
    SIPInboundTrunkInfo,
    CreateSIPInboundTrunkRequest,
    ListSIPInboundTrunkRequest,
    DeleteSIPTrunkRequest,
    ListSIPDispatchRuleRequest,
    DeleteSIPDispatchRuleRequest,
    CreateSIPDispatchRuleRequest,
    SIPDispatchRule,
    SIPDispatchRuleDirect,
)
from livekit.protocol.room import RoomConfiguration

load_dotenv("backend/.env")

LIVEKIT_URL    = os.getenv("LIVEKIT_URL", "")
LIVEKIT_KEY    = os.getenv("LIVEKIT_API_KEY", "")
LIVEKIT_SECRET = os.getenv("LIVEKIT_API_SECRET", "")
OLD_TRUNK_ID   = os.getenv("LIVEKIT_SIP_INBOUND_TRUNK_ID", "")

if not all([LIVEKIT_URL, LIVEKIT_KEY, LIVEKIT_SECRET]):
    print("❌ Missing LIVEKIT_URL / LIVEKIT_API_KEY / LIVEKIT_API_SECRET in backend/.env")
    sys.exit(1)

if not OLD_TRUNK_ID:
    print("❌ LIVEKIT_SIP_INBOUND_TRUNK_ID not set in backend/.env — nothing to fix")
    sys.exit(1)

# Twilio IP ranges (same as setup script)
TWILIO_IP_RANGES = [
    "54.172.60.0/23",
    "54.244.51.0/24",
    "54.171.127.192/26",
    "35.156.191.128/25",
    "35.152.170.0/25",
    "52.215.127.0/24",
    "3.112.80.0/24",
    "54.65.63.192/26",
]


async def main():
    print("=" * 60)
    print("  Fix: Remove SIP digest auth from inbound trunk")
    print("=" * 60)
    print(f"\n  Old trunk ID: {OLD_TRUNK_ID}")

    lk = api.LiveKitAPI(url=LIVEKIT_URL, api_key=LIVEKIT_KEY, api_secret=LIVEKIT_SECRET)

    try:
        # ── Step 1: Get existing dispatch rules ───────────────────────────────
        print("\n[1/4] Fetching existing dispatch rules...")
        rules_resp = await lk.sip.list_sip_dispatch_rule(ListSIPDispatchRuleRequest())
        rules = getattr(rules_resp, "items", [])
        affected = [r for r in rules if OLD_TRUNK_ID in list(getattr(r, "trunk_ids", []))]
        print(f"      Found {len(rules)} total rules, {len(affected)} using old trunk")

        # ── Step 2: Delete dispatch rules pointing to old trunk ───────────────
        saved_rules = []
        if affected:
            print(f"\n[2/4] Saving and deleting {len(affected)} dispatch rule(s)...")
            import json
            for rule in affected:
                saved_rules.append({
                    "name": rule.name,
                    "inbound_numbers": list(getattr(rule, "inbound_numbers", [])),
                    "attrs": dict(getattr(rule, "attributes", {})),
                })
                await lk.sip.delete_sip_dispatch_rule(
                    DeleteSIPDispatchRuleRequest(sip_dispatch_rule_id=rule.sip_dispatch_rule_id)
                )
                print(f"      🗑  Deleted rule '{rule.name}' ({rule.sip_dispatch_rule_id})")
        else:
            print("\n[2/4] No dispatch rules to migrate")
            import json

        # ── Step 3: Delete old trunk ──────────────────────────────────────────
        print(f"\n[3/4] Deleting old trunk {OLD_TRUNK_ID}...")
        await lk.sip.delete_sip_trunk(DeleteSIPTrunkRequest(sip_trunk_id=OLD_TRUNK_ID))
        print(f"      🗑  Old trunk deleted")

        # ── Step 4: Create new inbound trunk WITHOUT auth ─────────────────────
        print("\n[4/4] Creating new inbound trunk (IP allowlist only, no auth)...")
        new_trunk = await lk.sip.create_sip_inbound_trunk(
            CreateSIPInboundTrunkRequest(
                trunk=SIPInboundTrunkInfo(
                    name="Twilio Inbound",
                    allowed_addresses=TWILIO_IP_RANGES,
                    # auth_username and auth_password intentionally omitted
                )
            )
        )
        new_trunk_id = new_trunk.sip_trunk_id
        print(f"      ✅ New trunk created: {new_trunk_id}")

        # ── Step 5: Recreate dispatch rules with new trunk ID ─────────────────
        for saved in saved_rules:
            new_rule = await lk.sip.create_sip_dispatch_rule(
                CreateSIPDispatchRuleRequest(
                    name=saved["name"],
                    rule=SIPDispatchRule(
                        dispatch_rule_direct=SIPDispatchRuleDirect(
                            room_name="",
                            pin="",
                        )
                    ),
                    trunk_ids=[new_trunk_id],
                    inbound_numbers=saved["inbound_numbers"],
                    attributes=saved["attrs"],
                    room_config=RoomConfiguration(
                        agents=[{"agent_name": "", "metadata": json.dumps(saved["attrs"])}]
                    ),
                )
            )
            print(f"      ✅ Recreated rule '{saved['name']}': {new_rule.sip_dispatch_rule_id}")

    finally:
        await lk.aclose()

    # ── Done ──────────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  ✅ Done — update these in backend/.env and agent/.env.local:")
    print("=" * 60)
    print(f"\nLIVEKIT_SIP_INBOUND_TRUNK_ID={new_trunk_id}\n")
    print("  Also remove (no longer needed):")
    print("    SIP_AUTH_USERNAME=...")
    print("    SIP_AUTH_PASSWORD=...")
    print("\n  Then restart the backend and agent.\n")


if __name__ == "__main__":
    asyncio.run(main())
