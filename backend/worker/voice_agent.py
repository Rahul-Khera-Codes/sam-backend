"""
Voice Agent Worker
──────────────────
This runs as a separate process per active call.
It joins the LiveKit room as a bot participant,
streams audio through GPT-4o Realtime API,
captures transcripts, and uploads recordings on call end.

Usage:
  python -m worker.voice_agent --call-id <uuid> --room-id <room>
"""

import asyncio
import logging
import argparse
import json
from datetime import datetime, timezone

from openai import AsyncOpenAI
from livekit import rtc
from livekit.api import AccessToken, VideoGrants

from app.core.config import settings
from app.core.supabase import supabase_admin

logger = logging.getLogger(__name__)

# ── GPT-4o System Prompt ──────────────────────
# TODO: replace with business-specific prompt loaded from DB

SYSTEM_PROMPT = """
You are a helpful AI customer service assistant.
Be friendly, professional, and concise.
If you cannot help with something, offer to transfer the caller to a human agent.
Always confirm any appointments or bookings back to the caller clearly.
"""


class VoiceAgentWorker:
    def __init__(self, call_id: str, room_id: str, business_id: str):
        self.call_id = call_id
        self.room_id = room_id
        self.business_id = business_id
        self.openai = AsyncOpenAI(api_key=settings.openai_api_key)
        self.transcript: list[dict] = []
        self.sequence = 0
        self.room = None
        self.audio_source = None

    # ── LiveKit ───────────────────────────────

    def _get_agent_token(self) -> str:
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
                    room=self.room_id,
                    can_publish=True,
                    can_subscribe=True,
                    agent=True,
                )
            )
        )
        return token.to_jwt()

    def _prepare_room_and_token(self):
        """Creates room and token; does NOT connect. Caller must register handlers before connect."""
        self.room = rtc.Room()
        return self._get_agent_token()

    # ── Transcript ────────────────────────────

    async def save_utterance(self, speaker: str, text: str, timestamp_s: float):
        """Writes a single transcript utterance to Supabase."""
        self.sequence += 1
        entry = {
            "call_id": self.call_id,
            "business_id": self.business_id,
            "speaker": speaker,
            "text": text,
            "timestamp_seconds": round(timestamp_s, 2),
            "sequence_order": self.sequence,
        }
        self.transcript.append(entry)

        supabase_admin.table("transcripts").insert(entry).execute()
        logger.info(f"[Transcript] {speaker}: {text[:60]}...")

    # ── Post-call ─────────────────────────────

    async def generate_summary(self):
        """Asks GPT-4o to summarize the transcript after the call ends."""
        if not self.transcript:
            return

        transcript_text = "\n".join(
            f"{u['speaker'].upper()}: {u['text']}"
            for u in self.transcript
        )

        response = await self.openai.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": "Summarize this call transcript. Return JSON with keys: summary_text (string), key_topics (array of strings), sentiment (positive/neutral/negative)."
                },
                {"role": "user", "content": transcript_text}
            ],
            response_format={"type": "json_object"},
        )

        try:
            result = json.loads(response.choices[0].message.content)

            # Save summary
            supabase_admin.table("call_summaries").insert({
                "call_id": self.call_id,
                "business_id": self.business_id,
                "summary_text": result.get("summary_text"),
                "key_topics": result.get("key_topics", []),
                "insights": {"sentiment_from_summary": result.get("sentiment")},
            }).execute()

            # Update call sentiment
            supabase_admin.table("calls").update({
                "sentiment": result.get("sentiment", "neutral")
            }).eq("id", self.call_id).execute()

            logger.info(f"[Worker] Summary saved for call {self.call_id}")

        except Exception as e:
            logger.error(f"[Worker] Failed to save summary: {e}")

    async def finalize_call(self, duration_seconds: int):
        """Marks the call as completed and triggers post-call processing."""
        supabase_admin.table("calls").update({
            "status": "completed",
            "ended_at": datetime.now(timezone.utc).isoformat(),
            "duration_seconds": duration_seconds,
        }).eq("id", self.call_id).execute()

        await self.generate_summary()
        logger.info(f"[Worker] Call {self.call_id} finalized.")

    # ── Main GPT-4o Realtime Loop ─────────────

    async def run(self):
        """
        Main audio loop:
        1. Listens for audio from the LiveKit room (caller's voice)
        2. Streams audio to GPT-4o Realtime API
        3. Gets back audio + transcript from GPT-4o
        4. Plays response audio back into the LiveKit room
        5. Saves transcript utterances to Supabase
        """
        token = self._prepare_room_and_token()
        start_time = datetime.now(timezone.utc)

        # Build a business-aware system prompt so the agent can greet with
        # the company name and location.
        system_prompt = SYSTEM_PROMPT
        try:
            company_name = "your company"
            location_phrase = ""

            biz_result = (
                supabase_admin.table("businesses")
                .select("*")
                .eq("id", self.business_id)
                .limit(1)
                .execute()
            )
            biz_data = getattr(biz_result, "data", None) or []
            biz = biz_data[0] if isinstance(biz_data, list) and biz_data else None
            if isinstance(biz, dict) and biz.get("name"):
                company_name = biz["name"]

            call_result = (
                supabase_admin.table("calls")
                .select("location_id")
                .eq("id", self.call_id)
                .limit(1)
                .execute()
            )
            call_data = getattr(call_result, "data", None) or []
            call_row = call_data[0] if isinstance(call_data, list) and call_data else None
            location_id = call_row.get("location_id") if isinstance(call_row, dict) else None

            if location_id:
                loc_result = (
                    supabase_admin.table("locations")
                    .select("*")
                    .eq("id", location_id)
                    .limit(1)
                    .execute()
                )
                loc_data = getattr(loc_result, "data", None) or []
                loc = loc_data[0] if isinstance(loc_data, list) and loc_data else None
                if isinstance(loc, dict):
                    parts = [
                        loc.get("name"),
                        loc.get("city"),
                        loc.get("state"),
                        loc.get("country"),
                    ]
                    spoken = ", ".join([p for p in parts if p])
                    if spoken:
                        location_phrase = f" in {spoken}"

            system_prompt = f"""
You are the AI phone receptionist for {company_name}{location_phrase}.
Always start the call with a short, friendly welcome that includes the business name{', and the location if helpful' if location_phrase else ''}.
Example: \"Thank you for calling {company_name}{location_phrase}, how can I help you today?\"

Then continue the conversation following these rules:
{SYSTEM_PROMPT}
"""
        except Exception as e:
            logger.warning(f"[Worker] Failed to build business-aware prompt, falling back to default: {e}")

        try:
            # Open GPT-4o Realtime WebSocket first so we can register room handlers before connecting
            async with self.openai.realtime.connect(
                model="gpt-4o-realtime-preview-2024-12-17"
            ) as connection:

                # Configure the session (type required by API for custom instructions)
                await connection.session.update(
                    session={
                        "type": "realtime",
                        "instructions": system_prompt,
                        # Let the model use its default voice; explicit 'voice'
                        # is rejected on this Realtime model version.
                        "input_audio_format": "pcm16",
                        "output_audio_format": "pcm16",
                        "input_audio_transcription": {"model": "gpt-4o-transcribe"},
                        "turn_detection": {
                            "type": "server_vad",
                            "threshold": 0.5,
                            "silence_duration_ms": 800,
                        },
                    }
                )

                logger.info(f"[Worker] GPT-4o Realtime session opened for call {self.call_id}")

                # OpenAI Realtime expects 24 kHz mono PCM16; browser/LiveKit often sends 48 kHz.
                OPENAI_RATE = 24000
                OPENAI_CH = 1
                _streaming_track_sid = None  # prevent double-streaming same track
                _frames_sent = 0
                _first_audio_out = False

                import base64
                import numpy as np

                async def stream_audio(track):
                    nonlocal _streaming_track_sid, _frames_sent
                    track_sid = getattr(track, "sid", None) or id(track)
                    if _streaming_track_sid is not None:
                        logger.info(f"[Worker] Skipping duplicate stream for track {track_sid}")
                        return
                    _streaming_track_sid = track_sid
                    logger.info(f"[Worker] Starting to stream audio from track {track_sid} to GPT")
                    try:
                        audio_stream = rtc.AudioStream(track)
                        async for frame_event in audio_stream:
                            frame = frame_event.frame
                            if _frames_sent == 0:
                                logger.info(
                                    f"[Worker] First LK frame: rate={frame.sample_rate} ch={frame.num_channels} "
                                    f"samples={frame.samples_per_channel} data_bytes={len(bytes(frame.data))}"
                                )
                            if frame.sample_rate != OPENAI_RATE or frame.num_channels != OPENAI_CH:
                                frame = frame.remix_and_resample(OPENAI_RATE, OPENAI_CH)
                            pcm_bytes = bytes(frame.data)
                            if len(pcm_bytes) == 0:
                                continue
                            encoded = base64.b64encode(pcm_bytes).decode()
                            await connection.input_audio_buffer.append(audio=encoded)
                            _frames_sent += 1
                            if _frames_sent in (1, 50, 200):
                                logger.info(f"[Worker] Sent {_frames_sent} audio frames to GPT ({len(pcm_bytes)} bytes each)")
                    except asyncio.CancelledError:
                        logger.info("[Worker] stream_audio cancelled")
                        raise
                    except Exception as e:
                        if "ConnectionClosed" in type(e).__name__ or "1000" in str(e):
                            logger.info("[Worker] stream_audio: connection closed normally")
                            return
                        logger.warning(
                            "[Worker] stream_audio ended (caller audio stopped). Agent will not hear until rejoin: %s",
                            e,
                        )

                def on_track_subscribed(track, publication, participant):
                    if track.kind == rtc.TrackKind.KIND_AUDIO:
                        asyncio.ensure_future(stream_audio(track))
                        logger.info(f"[Worker] Subscribed to audio track from {participant.identity}")

                self.room.on("track_subscribed", on_track_subscribed)

                def on_disconnected(reason=None, error=None):
                    logger.warning("[Worker] LiveKit room disconnected: reason=%s error=%s", reason, error)

                def on_reconnecting():
                    logger.info("[Worker] LiveKit reconnecting…")

                self.room.on("disconnected", on_disconnected)
                self.room.on("reconnecting", on_reconnecting)

                await self.room.connect(settings.livekit_url, token)
                logger.info(f"[Worker] Connected to LiveKit room: {self.room_id}")

                self.audio_source = rtc.AudioSource(sample_rate=24000, num_channels=1)
                agent_track = rtc.LocalAudioTrack.create_audio_track("agent-voice", self.audio_source)
                options = rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
                await self.room.local_participant.publish_track(agent_track, options)
                logger.info("[Worker] Agent audio track published")

                # Trigger an immediate welcome so the agent speaks first (company name + location)
                await connection.response.create()
                logger.info("[Worker] Requested initial welcome response")

                # Start streaming existing tracks (only if on_track_subscribed didn't already)
                for participant in self.room.participants.values():
                    for pub in participant.tracks.values():
                        track = getattr(pub, "track", None)
                        if track is not None and track.kind == rtc.TrackKind.KIND_AUDIO:
                            asyncio.ensure_future(stream_audio(track))
                            logger.info(f"[Worker] Streaming existing audio from {participant.identity}")

                call_start = asyncio.get_event_loop().time()
                _event_counts: dict[str, int] = {}

                async def handle_gpt_events():
                    nonlocal _first_audio_out
                    async for event in connection:
                        etype = getattr(event, "type", None)
                        if etype is None and isinstance(event, dict):
                            etype = event.get("type")

                        # Log first 5 of each event type
                        _event_counts[etype] = _event_counts.get(etype, 0) + 1
                        if _event_counts[etype] <= 5:
                            logger.info(f"[Worker] GPT event: {etype} (#{_event_counts[etype]})")

                        if etype in ("response.audio.delta", "response.output_audio.delta"):
                            delta = getattr(event, "delta", None)
                            if not delta:
                                logger.warning("[Worker] audio delta with no delta attr")
                                continue
                            audio_bytes = base64.b64decode(delta)
                            if len(audio_bytes) == 0:
                                continue
                            pcm = np.frombuffer(audio_bytes, dtype=np.int16)
                            if len(pcm) == 0:
                                continue
                            if not _first_audio_out:
                                logger.info(f"[Worker] First agent audio: {len(pcm)} samples")
                                _first_audio_out = True
                            frame = rtc.AudioFrame(
                                data=pcm.tobytes(),
                                sample_rate=24000,
                                num_channels=1,
                                samples_per_channel=len(pcm),
                            )
                            await self.audio_source.capture_frame(frame)

                        elif etype in ("response.audio_transcript.done", "response.output_audio_transcript.done"):
                            ts = asyncio.get_event_loop().time() - call_start
                            text = getattr(event, "transcript", None) or getattr(event, "text", "")
                            if text:
                                await self.save_utterance("agent", text, ts)

                        elif etype == "conversation.item.input_audio_transcription.completed":
                            ts = asyncio.get_event_loop().time() - call_start
                            await self.save_utterance("customer", event.transcript, ts)

                        elif etype == "session.updated":
                            logger.info("[Worker] Session configured successfully (session.updated received)")

                        elif etype == "error":
                            err = getattr(event, "error", event)
                            logger.error(f"[Worker] GPT error event: {err}")

                await asyncio.gather(
                    handle_gpt_events(),
                    asyncio.Future(),  # keeps gather alive
                )

        except Exception as e:
            logger.error(f"[Worker] Error in audio loop: {e}")
            supabase_admin.table("calls").update({"status": "failed"}).eq("id", self.call_id).execute()

        finally:
            # Calculate duration and finalize
            duration = int((datetime.now(timezone.utc) - start_time).total_seconds())
            await self.finalize_call(duration)

            if self.room:
                await self.room.disconnect()


# ── Entry Point ───────────────────────────────

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--call-id", required=True)
    parser.add_argument("--room-id", required=True)
    parser.add_argument("--business-id", required=True)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    worker = VoiceAgentWorker(
        call_id=args.call_id,
        room_id=args.room_id,
        business_id=args.business_id,
    )
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
