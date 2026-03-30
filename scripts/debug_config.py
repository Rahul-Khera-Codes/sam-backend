#!/usr/bin/env python3
"""
Debug Script 1: Verify all configuration (Twilio + LiveKit)
============================================================
Run from sam-backend root:
  python scripts/debug_config.py
"""
import asyncio
import os
import sys
from dotenv import load_dotenv

load_dotenv("backend/.env")

LIVEKIT_URL    = os.getenv("LIVEKIT_URL", "")
LIVEKIT_KEY    = os.getenv("LIVEKIT_API_KEY", "")
LIVEKIT_SECRET = os.getenv("LIVEKIT_API_SECRET", "")
TWILIO_SID     = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_TOKEN   = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_TRUNK   = os.getenv("TWILIO_TRUNK_SID", "")

OK  = "✅"
ERR = "❌"
WRN = "⚠️ "

def check(label, condition, detail=""):
    sym = OK if condition else ERR
    print(f"  {sym}  {label}", f"  ({detail})" if detail else "")
    return condition


async def check_livekit():
    from livekit import api
    from livekit.protocol.sip import ListSIPInboundTrunkRequest, ListSIPDispatchRuleRequest

    print("\n── LiveKit ──────────────────────────────────────────────")
    # SIP host is from LIVEKIT_SIP_HOST env (Project ID based), NOT derived from URL
    sip_host_env = os.getenv("LIVEKIT_SIP_HOST", "").replace("sip:", "")
    if sip_host_env:
        sip_host = sip_host_env
    else:
        lk_host = LIVEKIT_URL.replace("wss://","").replace("ws://","")
        project_slug = lk_host.split(".")[0]
        sip_host = f"{project_slug}.sip.livekit.cloud"

    check("LIVEKIT_URL set", bool(LIVEKIT_URL), LIVEKIT_URL)
    check("LIVEKIT_API_KEY set", bool(LIVEKIT_KEY), LIVEKIT_KEY[:8]+"..." if LIVEKIT_KEY else "")

    lk = api.LiveKitAPI(url=LIVEKIT_URL, api_key=LIVEKIT_KEY, api_secret=LIVEKIT_SECRET)
    try:
        # Test connection
        try:
            rooms = await lk.room.list_rooms(api.ListRoomsRequest())
            check("LiveKit API reachable", True, f"{len(rooms.rooms)} active rooms")
        except Exception as e:
            check("LiveKit API reachable", False, str(e))
            return

        # Inbound trunks
        trunks_resp = await lk.sip.list_sip_inbound_trunk(ListSIPInboundTrunkRequest())
        trunks = getattr(trunks_resp, "items", [])
        check("Has inbound SIP trunk(s)", len(trunks) > 0, f"{len(trunks)} found")
        for t in trunks:
            print(f"\n     Trunk: {t.sip_trunk_id}  ({t.name})")
            print(f"       numbers:          {list(t.numbers)}")
            print(f"       allowed_addresses: {list(t.allowed_addresses)}")
            print(f"       auth_username:     {t.auth_username!r}")

        # Dispatch rules
        rules_resp = await lk.sip.list_sip_dispatch_rule(ListSIPDispatchRuleRequest())
        rules = getattr(rules_resp, "items", [])
        check("Has dispatch rule(s)", len(rules) > 0, f"{len(rules)} found")
        for r in rules:
            print(f"\n     Rule: {r.sip_dispatch_rule_id}  ({r.name})")
            print(f"       trunk_ids:       {list(r.trunk_ids)}")
            print(f"       inbound_numbers: {list(r.inbound_numbers)}")
            print(f"       attributes:      {dict(r.attributes)}")
            # Check trunk IDs match
            trunk_ids = set(t.sip_trunk_id for t in trunks)
            matched = all(tid in trunk_ids for tid in r.trunk_ids)
            check(f"  Rule trunk_ids point to existing trunks", matched,
                  "missing: " + str(set(r.trunk_ids) - trunk_ids) if not matched else "ok")

        print(f"\n     SIP host: {sip_host}")
        import socket
        try:
            addrs = socket.getaddrinfo(sip_host, 5060, socket.AF_INET)
            ip = addrs[0][4][0]
            check("SIP host resolves", True, ip)
        except Exception as e:
            check("SIP host resolves", False, str(e))

        # TCP port check
        import asyncio
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(sip_host, 5060), timeout=5
            )
            writer.close()
            await writer.wait_closed()
            check("SIP TCP 5060 reachable", True, sip_host)
        except Exception as e:
            check("SIP TCP 5060 reachable", False, str(e))

    finally:
        await lk.aclose()


def check_twilio():
    from twilio.rest import Client
    client = Client(TWILIO_SID, TWILIO_TOKEN)

    print("\n── Twilio ───────────────────────────────────────────────")
    check("TWILIO_ACCOUNT_SID set", bool(TWILIO_SID), TWILIO_SID)
    check("TWILIO_TRUNK_SID set", bool(TWILIO_TRUNK), TWILIO_TRUNK)

    try:
        account = client.api.accounts(TWILIO_SID).fetch()
        check("Twilio API reachable", True, account.friendly_name)
    except Exception as e:
        check("Twilio API reachable", False, str(e))
        return

    # Phone numbers
    try:
        pns = client.incoming_phone_numbers.list()
        check("Has phone numbers", len(pns) > 0, f"{len(pns)} found")
        for pn in pns:
            print(f"\n     Number: {pn.phone_number}  ({pn.sid})")
            print(f"       trunk_sid:  {pn.trunk_sid}")
            check(f"  {pn.phone_number} → trunk", pn.trunk_sid == TWILIO_TRUNK,
                  pn.trunk_sid or "no trunk set")
    except Exception as e:
        print(f"  {ERR}  Could not list phone numbers: {e}")

    # Trunk origination URIs
    sip_host_env2 = os.getenv("LIVEKIT_SIP_HOST", "").replace("sip:", "")
    if sip_host_env2:
        expected_sip_host = sip_host_env2
    else:
        LIVEKIT_URL2 = os.getenv("LIVEKIT_URL","")
        project_slug = LIVEKIT_URL2.replace("wss://","").replace("ws://","").split(".")[0]
        expected_sip_host = f"{project_slug}.sip.livekit.cloud"
    expected_uri = f"sip:{expected_sip_host};transport=tcp"

    try:
        origins = client.trunking.v1.trunks(TWILIO_TRUNK).origination_urls.list()
        check("Trunk has origination URI(s)", len(origins) > 0, f"{len(origins)} found")
        for o in origins:
            print(f"\n     Origination URI: {o.sip_url}  (enabled={o.enabled})")
            correct = expected_sip_host in o.sip_url
            check(f"  URI points to correct LiveKit project", correct,
                  f"expected: {expected_uri}" if not correct else "ok")
    except Exception as e:
        print(f"  {ERR}  Could not fetch origination URIs: {e}")


async def main():
    print("=" * 60)
    print("  SAM Voice Agent — Debug Config Check")
    print("=" * 60)
    await check_livekit()
    check_twilio()
    print()


if __name__ == "__main__":
    asyncio.run(main())
