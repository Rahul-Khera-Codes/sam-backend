#!/usr/bin/env python3
"""
Debug Script 2: Send a raw SIP INVITE directly to LiveKit
==========================================================
Keeps the connection open to receive the FINAL SIP response
(100 Processing, then 180 Ringing / 200 OK / 486 Busy / etc.)

Run from sam-backend root (while agent is running in Docker):
  python scripts/debug_sip_invite.py [called_number] [calling_number]
"""
import asyncio
import os
import socket
import sys
import uuid
from dotenv import load_dotenv

load_dotenv("backend/.env")

LIVEKIT_URL = os.getenv("LIVEKIT_URL", "")
# SIP host comes from LiveKit Cloud dashboard → Project Settings → SIP URI
# It uses the Project ID (not the URL slug) e.g. 2r3ulnu25ia.sip.livekit.cloud
SIP_HOST = os.getenv("LIVEKIT_SIP_HOST", "").replace("sip:", "")
if not SIP_HOST:
    # fallback: derive from URL (may be wrong if project ID differs from URL slug)
    project_slug = LIVEKIT_URL.replace("wss://","").replace("ws://","").split(".")[0]
    SIP_HOST = f"{project_slug}.sip.livekit.cloud"
SIP_PORT = 5060

CALLED  = sys.argv[1] if len(sys.argv) > 1 else "+14152555624"
CALLING = sys.argv[2] if len(sys.argv) > 2 else "+14788126881"


def build_sip_invite(called: str, calling: str, sip_host: str, local_ip: str):
    call_id = f"{uuid.uuid4().hex}@{local_ip}"
    branch  = f"z9hG4bK{uuid.uuid4().hex[:10]}"
    tag     = uuid.uuid4().hex[:8]

    sdp = (
        f"v=0\r\n"
        f"o=debug 1 1 IN IP4 {local_ip}\r\n"
        f"s=SAM Debug\r\n"
        f"c=IN IP4 {local_ip}\r\n"
        f"t=0 0\r\n"
        f"m=audio 10000 RTP/AVP 0 8\r\n"
        f"a=rtpmap:0 PCMU/8000\r\n"
        f"a=rtpmap:8 PCMA/8000\r\n"
        f"a=sendrecv\r\n"
    ).encode()

    msg = (
        f"INVITE sip:{called}@{sip_host} SIP/2.0\r\n"
        f"Via: SIP/2.0/TCP {local_ip}:5090;rport;branch={branch}\r\n"
        f"Max-Forwards: 70\r\n"
        f"From: <sip:{calling}@{local_ip}>;tag={tag}\r\n"
        f"To: <sip:{called}@{sip_host}>\r\n"
        f"Call-ID: {call_id}\r\n"
        f"CSeq: 1 INVITE\r\n"
        f"Contact: <sip:{calling}@{local_ip}:5090;transport=tcp>\r\n"
        f"Content-Type: application/sdp\r\n"
        f"Content-Length: {len(sdp)}\r\n"
        f"\r\n"
    ).encode() + sdp

    return msg, call_id, branch, tag


async def send_invite_and_wait(called: str, calling: str, timeout: int = 40):
    print(f"{'='*60}")
    print(f"  SIP INVITE Test — waiting up to {timeout}s for final response")
    print(f"{'='*60}")
    print(f"  SIP host: {SIP_HOST}:{SIP_PORT}")
    print(f"  Called:   {called}")
    print(f"  Calling:  {calling}")

    # Local IP
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
    except Exception:
        local_ip = "127.0.0.1"
    finally:
        s.close()
    print(f"  Local IP: {local_ip}\n")

    invite, call_id, branch, from_tag = build_sip_invite(called, calling, SIP_HOST, local_ip)

    # Resolve SIP host
    addrs = socket.getaddrinfo(SIP_HOST, SIP_PORT, socket.AF_INET, socket.SOCK_STREAM)
    sip_ip = addrs[0][4][0]

    reader, writer = await asyncio.wait_for(
        asyncio.open_connection(sip_ip, SIP_PORT), timeout=10
    )
    print(f"  ✅ TCP connected to {sip_ip}:{SIP_PORT}")

    writer.write(invite)
    await writer.drain()
    print(f"  ✅ INVITE sent\n")

    # Read all SIP messages until we get a final response (2xx/4xx/5xx/6xx)
    buf = b""
    deadline = asyncio.get_event_loop().time() + timeout
    final_code = None
    seen_codes = []

    print(f"── SIP Responses ────────────────────────────────────────")
    while asyncio.get_event_loop().time() < deadline:
        remaining = deadline - asyncio.get_event_loop().time()
        try:
            chunk = await asyncio.wait_for(reader.read(8192), timeout=min(remaining, 2))
            buf += chunk
        except asyncio.TimeoutError:
            continue

        # Parse SIP messages from buffer
        while b"\r\n\r\n" in buf:
            # Find end of headers
            hdr_end = buf.index(b"\r\n\r\n") + 4
            headers_raw = buf[:hdr_end].decode(errors="replace")
            first_line = headers_raw.split("\r\n")[0]

            # Get Content-Length to advance past body
            content_length = 0
            for line in headers_raw.split("\r\n"):
                if line.lower().startswith("content-length:"):
                    try:
                        content_length = int(line.split(":",1)[1].strip())
                    except ValueError:
                        pass

            msg_end = hdr_end + content_length
            if len(buf) < msg_end:
                break  # wait for more data

            buf = buf[msg_end:]

            # Parse response code
            if first_line.startswith("SIP/2.0"):
                parts = first_line.split(" ", 2)
                code = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
                reason = parts[2] if len(parts) > 2 else ""
                seen_codes.append(code)

                print(f"\n  [{asyncio.get_event_loop().time():.1f}s] {first_line}")

                if code == 100:
                    print(f"    → Provisional: LiveKit is processing (trunk+rule matched ✅)")
                elif code == 180:
                    print(f"    → Ringing")
                elif code == 200:
                    print(f"    → SUCCESS — call answered! ✅")
                    final_code = code
                    break
                elif code == 401:
                    print(f"    → UNAUTHORIZED — auth_username is set on inbound trunk ❌")
                    final_code = code
                    break
                elif code == 403:
                    print(f"    → FORBIDDEN ❌")
                    final_code = code
                    break
                elif code == 404:
                    print(f"    → NOT FOUND — no trunk/dispatch rule match ❌")
                    final_code = code
                    break
                elif code == 480:
                    print(f"    → TEMPORARILY UNAVAILABLE — no agent worker available ❌")
                    final_code = code
                    break
                elif code == 486:
                    print(f"    → BUSY HERE — LiveKit flood protection / no match ❌")
                    final_code = code
                    break
                elif code >= 400:
                    print(f"    → FAILURE ({code}) ❌")
                    final_code = code
                    break
            else:
                # Could be a SIP request (e.g., OPTIONS)
                print(f"\n  [request] {first_line}")

        if final_code is not None:
            break

    writer.close()
    try:
        await writer.wait_closed()
    except Exception:
        pass

    print(f"\n{'─'*60}")
    print(f"  Seen codes: {seen_codes}")
    if final_code is None:
        print(f"  ⚠️  No final response within {timeout}s")
        print(f"  → LiveKit accepted the call (100) but agent didn't answer in time")
        print(f"  → Check agent logs for errors when handling SIP job")
    print()


if __name__ == "__main__":
    asyncio.run(send_invite_and_wait(CALLED, CALLING))
