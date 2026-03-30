#!/usr/bin/env python3
"""
Step 0 — One-time SIP Trunk Setup
===================================
Run this ONCE to wire Twilio Elastic SIP Trunking to LiveKit SIP.

What it does:
  1. Creates LiveKit inbound SIP trunk  (Twilio → LiveKit, for inbound PSTN calls)
  2. Creates LiveKit outbound SIP trunk (LiveKit → Twilio → PSTN, for outbound calls)
  3. Creates Twilio Elastic SIP Trunk
  4. Adds LiveKit SIP endpoint as origination URI on the Twilio trunk
  5. Creates a Twilio credential list + credential for outbound auth
  6. Assigns credential list to Twilio trunk termination
  7. Prints all IDs → copy them into backend/.env and agent/.env.local

Usage:
  cd sam-backend
  pip install twilio livekit-api python-dotenv
  python scripts/setup_sip_trunks.py

Required env vars (set in backend/.env before running):
  LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET
  TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN
"""

import asyncio
import os
import secrets
import string
import sys

from dotenv import load_dotenv
from livekit import api
from livekit.protocol.sip import (
    SIPInboundTrunkInfo,
    CreateSIPInboundTrunkRequest,
)
from twilio.rest import Client as TwilioClient

load_dotenv("backend/.env")

# ── Validate required env vars ─────────────────────────────────────────────────

REQUIRED = [
    "LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET",
    "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN",
]

missing = [k for k in REQUIRED if not os.getenv(k)]
if missing:
    print(f"\n❌ Missing env vars: {', '.join(missing)}")
    print("   Add them to backend/.env then re-run.\n")
    sys.exit(1)

LIVEKIT_URL    = os.getenv("LIVEKIT_URL", "")
LIVEKIT_KEY    = os.getenv("LIVEKIT_API_KEY", "")
LIVEKIT_SECRET = os.getenv("LIVEKIT_API_SECRET", "")
TWILIO_SID     = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_TOKEN   = os.getenv("TWILIO_AUTH_TOKEN", "")

# Guard: don't re-run if trunks already exist
if os.getenv("LIVEKIT_SIP_INBOUND_TRUNK_ID") or os.getenv("TWILIO_TRUNK_SID"):
    print("\n⚠️  It looks like trunks are already configured in backend/.env.")
    print("   Delete LIVEKIT_SIP_INBOUND_TRUNK_ID and TWILIO_TRUNK_SID if you want to re-run.\n")
    sys.exit(0)

# Derive LiveKit SIP host from project URL
# wss://ai-front-desk-tvtw766q.livekit.cloud → ai-front-desk-tvtw766q.sip.livekit.cloud
_lk_host = LIVEKIT_URL.replace("wss://", "").replace("ws://", "")
_project_slug = _lk_host.split(".")[0]
LIVEKIT_SIP_HOST = f"{_project_slug}.sip.livekit.cloud"


def _gen_password(length: int = 24) -> str:
    """Generate a secure random password for SIP auth."""
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    return "".join(secrets.choice(alphabet) for _ in range(length))


async def setup_livekit_trunks(sip_username: str, sip_password: str) -> tuple[str, str]:
    """Create LiveKit inbound + outbound SIP trunks. Returns (inbound_id, outbound_id)."""
    lk = api.LiveKitAPI(
        url=LIVEKIT_URL,
        api_key=LIVEKIT_KEY,
        api_secret=LIVEKIT_SECRET,
    )
    try:
        # ── Inbound trunk (Twilio → LiveKit) ──────────────────────────────────
        print("\n[1/2] Setting up LiveKit inbound SIP trunk...")

        # Reuse existing trunk named "Twilio Inbound" if already created
        from livekit.protocol.sip import ListSIPInboundTrunkRequest
        existing = await lk.sip.list_sip_inbound_trunk(ListSIPInboundTrunkRequest())
        existing_trunks = getattr(existing, "items", [])
        existing_trunk = next((t for t in existing_trunks if t.name == "Twilio Inbound"), None)

        if existing_trunk:
            inbound_id = existing_trunk.sip_trunk_id
            print(f"   ♻️  Reusing existing inbound trunk: {inbound_id}")
        else:
            inbound = await lk.sip.create_sip_inbound_trunk(
                CreateSIPInboundTrunkRequest(
                    trunk=SIPInboundTrunkInfo(
                        name="Twilio Inbound",
                        # numbers: leave empty → accepts calls to any number on this trunk
                        # Twilio's IP ranges (allows SIP INVITEs only from Twilio)
                        allowed_addresses=[
                            "54.172.60.0/23",
                            "54.244.51.0/24",
                            "54.171.127.192/26",
                            "35.156.191.128/25",
                            "35.152.170.0/25",
                            "52.215.127.0/24",
                            "3.112.80.0/24",
                            "54.65.63.192/26",
                        ],
                        # SIP digest auth as second factor
                        auth_username=sip_username,
                        auth_password=sip_password,
                    )
                )
            )
            inbound_id = inbound.sip_trunk_id
            print(f"   ✅ Inbound trunk created: {inbound_id}")

        # ── Outbound trunk (LiveKit → Twilio → PSTN) ──────────────────────────
        # NOTE: LiveKit requires at least one number on the outbound trunk.
        # This trunk is created automatically when the first business phone
        # number is provisioned (scripts/provision_phone_number.py or Step 2 backend).
        # Skipping for now — set LIVEKIT_SIP_OUTBOUND_TRUNK_ID after first provision.
        print("\n[2/2] Outbound trunk — skipped (created during first number provision)")
        outbound_id = ""
    finally:
        await lk.aclose()

    return inbound_id, outbound_id


def setup_twilio_trunk(livekit_sip_host: str, term_domain: str,
                       twilio_term_user: str, twilio_term_pass: str) -> str:
    """Create Twilio Elastic SIP Trunk with origination URI + credential list. Returns trunk_sid."""

    twilio = TwilioClient(TWILIO_SID, TWILIO_TOKEN)

    # ── Create Twilio SIP Trunk ────────────────────────────────────────────────
    print("\n[3/4] Creating Twilio Elastic SIP Trunk...")
    trunk = twilio.trunking.v1.trunks.create(
        friendly_name="SAM Voice Agent",
        domain_name=term_domain,
    )
    trunk_sid = trunk.sid
    print(f"   ✅ Twilio trunk created: {trunk_sid}")
    print(f"   Termination domain: {term_domain}")

    # ── Add LiveKit as origination URI (inbound: Twilio → LiveKit) ────────────
    print("\n[4/4] Adding LiveKit SIP endpoint as origination URI + credential list...")
    livekit_sip_uri = f"sip:{livekit_sip_host};transport=tcp"
    twilio.trunking.v1.trunks(trunk_sid).origination_urls.create(
        weight=1,
        priority=1,
        enabled=True,
        friendly_name="LiveKit SIP",
        sip_url=livekit_sip_uri,
    )
    print(f"   ✅ Origination URI added: {livekit_sip_uri}")

    # ── Create credential list for Twilio auth of inbound SIP ─────────────────
    # (Twilio sends this when calling LiveKit; LiveKit verifies it on inbound trunk)
    print("   Creating Twilio credential list for outbound SIP auth...")
    cred_list = twilio.sip.credential_lists.create(
        friendly_name="LiveKit Outbound Auth"
    )
    # LiveKit uses these creds when calling Twilio for outbound PSTN calls
    twilio.sip.credential_lists(cred_list.sid).credentials.create(
        username=twilio_term_user,
        password=twilio_term_pass,
    )
    # Assign credential list to trunk (so Twilio uses these creds when calling LiveKit)
    twilio.trunking.v1.trunks(trunk_sid).credentials_lists.create(
        credential_list_sid=cred_list.sid
    )
    print(f"   ✅ Credential list created + assigned: {cred_list.sid}")

    return trunk_sid


async def main():
    print("=" * 60)
    print("  SAM Voice Agent — SIP Trunk Setup")
    print("=" * 60)
    print(f"\n  LiveKit project:  {_project_slug}")
    print(f"  LiveKit SIP host: {LIVEKIT_SIP_HOST}")
    print(f"  Twilio account:   {TWILIO_SID}")

    # ── Generate credentials ──────────────────────────────────────────────────
    # SIP digest auth — used between Twilio and LiveKit inbound trunk
    sip_username = "sam-sip-user"
    sip_password = _gen_password(28)

    # Twilio termination domain — where LiveKit sends outbound SIP INVITEs
    # Format: <anything-unique>.pstn.twilio.com
    # The subdomain can be any label you choose; Twilio routes by Account SID
    term_domain_label = f"sam-{_project_slug}"
    term_domain = f"{term_domain_label}.pstn.twilio.com"

    # Credential list for LiveKit → Twilio outbound auth
    twilio_term_user = "sam-outbound-user"
    twilio_term_pass = _gen_password(28)

    print(f"\n  Generated SIP username (inbound):  {sip_username}")
    print(f"  Generated SIP password (inbound):  {sip_password}")
    print(f"  Twilio termination domain:         {term_domain}")
    print(f"  Twilio outbound SIP user:          {twilio_term_user}")
    print(f"  Twilio outbound SIP pass:          {twilio_term_pass}")

    # ── Run setup ────────────────────────────────────────────────────────────
    try:
        inbound_id, outbound_id = await setup_livekit_trunks(
            sip_username, sip_password,
        )
    except Exception as e:
        print(f"\n❌ LiveKit trunk creation failed: {e}")
        print("   Check LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET in backend/.env")
        sys.exit(1)

    try:
        trunk_sid = setup_twilio_trunk(
            LIVEKIT_SIP_HOST,
            term_domain, twilio_term_user, twilio_term_pass,
        )
    except Exception as e:
        print(f"\n❌ Twilio trunk creation failed: {e}")
        print("   Check TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN in backend/.env")
        print(f"\n   LiveKit trunks were already created:")
        print(f"     Inbound:  {inbound_id}")
        print(f"     Outbound: {outbound_id}")
        print("   Delete them from LiveKit dashboard before retrying.")
        sys.exit(1)

    # ── Print results ─────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  ✅ ALL DONE — copy these into backend/.env and agent/.env.local")
    print("=" * 60)
    print(f"""
# ── Twilio Phone / SIP ────────────────────────────────────
TWILIO_ACCOUNT_SID={TWILIO_SID}
TWILIO_AUTH_TOKEN={TWILIO_TOKEN}
TWILIO_TRUNK_SID={trunk_sid}

# ── LiveKit SIP Trunks ────────────────────────────────────
LIVEKIT_SIP_INBOUND_TRUNK_ID={inbound_id}
LIVEKIT_SIP_OUTBOUND_TRUNK_ID={outbound_id}

# ── SIP Auth (keep secret, used internally only) ──────────
SIP_AUTH_USERNAME={sip_username}
SIP_AUTH_PASSWORD={sip_password}
TWILIO_TERM_SIP_USERNAME={twilio_term_user}
TWILIO_TERM_SIP_PASSWORD={twilio_term_pass}
TWILIO_TERM_DOMAIN={term_domain}
""")

    print("  Next steps:")
    print("  1. Copy the block above into backend/.env")
    print("  2. Also add TWILIO_ACCOUNT_SID + TWILIO_AUTH_TOKEN to agent/.env.local")
    print("  3. Run the Step 1 migration in Supabase (business_phone_numbers table)")
    print("  4. Start building Step 2 — phone number provisioning service\n")


if __name__ == "__main__":
    asyncio.run(main())
