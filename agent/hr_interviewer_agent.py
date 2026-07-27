"""
HR AI Interviewer Agent — Emily.

Registered as "hr-interviewer-agent" with LiveKit AgentServer.
Runs voice-first structured AI screening interviews from the published
job-specific interview plan only.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

from dotenv import load_dotenv
from livekit import agents, api
from livekit.agents import Agent, AgentServer, AgentSession, room_io
from livekit.plugins import liveavatar, openai
from openai import AsyncOpenAI

from supabase_helpers import _get_supabase

load_dotenv(".env.local")
logger = logging.getLogger("hr-interviewer-agent")

for _noisy in ("hpack", "hpack.hpack", "hpack.table", "httpx", "httpcore"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

HR_INTERVIEWER_AGENT_NAME = "hr-interviewer-agent"
EMILY_AVATAR_ID = os.environ.get("EMILY_AVATAR_ID", "073b60a9-89a8-45aa-8902-c358f64d2852")
INTERVIEW_SCORING_MODEL = "gpt-4o-mini"
EMILY_INTRO_FALLBACK = "Hi, I'm Emily. I'll guide your structured screening interview today."


server = AgentServer()


async def _publish(room, payload: dict) -> None:
    try:
        await room.local_participant.publish_data(json.dumps(payload).encode(), reliable=True)
    except Exception as exc:
        logger.warning("publish_data failed: %s", exc)


async def _start_egress(room_name: str, session_id: str, business_id: str) -> tuple[str | None, str | None]:
    from livekit.protocol.egress import EncodedFileOutput, EncodedFileType, RoomCompositeEgressRequest, S3Upload

    access_key = os.getenv("SUPABASE_STORAGE_ACCESS_KEY_ID", "")
    secret_key = os.getenv("SUPABASE_STORAGE_SECRET_ACCESS_KEY", "")
    endpoint = os.getenv("SUPABASE_STORAGE_URL", "")
    region = os.getenv("SUPABASE_STORAGE_REGION", "us-east-1")
    bucket = os.getenv("HR_INTERVIEW_RECORDINGS_BUCKET", "hr-interview-recordings")
    if not all([access_key, secret_key, endpoint]):
        logger.warning("S3 credentials not configured; skipping HR interview recording")
        return None, None

    storage_path = f"{business_id}/{session_id}.ogg"
    lk_api = api.LiveKitAPI(
        url=os.getenv("LIVEKIT_URL", ""),
        api_key=os.getenv("LIVEKIT_API_KEY", ""),
        api_secret=os.getenv("LIVEKIT_API_SECRET", ""),
    )
    try:
        info = await lk_api.egress.start_room_composite_egress(
            RoomCompositeEgressRequest(
                room_name=room_name,
                audio_only=True,
                file_outputs=[
                    EncodedFileOutput(
                        file_type=EncodedFileType.OGG,
                        filepath=storage_path,
                        s3=S3Upload(
                            access_key=access_key,
                            secret=secret_key,
                            region=region,
                            endpoint=endpoint,
                            bucket=bucket,
                            force_path_style=True,
                        ),
                    )
                ],
            )
        )
        return info.egress_id, storage_path
    except Exception as exc:
        logger.warning("Failed to start HR interview egress: %s", exc)
        return None, None
    finally:
        await lk_api.aclose()


async def _stop_egress(egress_id: str) -> None:
    from livekit.protocol.egress import StopEgressRequest

    lk_api = api.LiveKitAPI(
        url=os.getenv("LIVEKIT_URL", ""),
        api_key=os.getenv("LIVEKIT_API_KEY", ""),
        api_secret=os.getenv("LIVEKIT_API_SECRET", ""),
    )
    try:
        await lk_api.egress.stop_egress(StopEgressRequest(egress_id=egress_id))
    except Exception as exc:
        logger.warning("Failed to stop HR interview egress %s: %s", egress_id, exc)
    finally:
        await lk_api.aclose()


def _load_session_context(supabase, business_id: str, session_id: str) -> dict[str, Any] | None:
    session_rows = (
        supabase.table("hr_interview_sessions")
        .select("*")
        .eq("business_id", business_id)
        .eq("id", session_id)
        .limit(1)
        .execute()
    ).data or []
    if not session_rows:
        return None
    session = session_rows[0]
    version_rows = (
        supabase.table("hr_interview_bank_versions")
        .select("*")
        .eq("business_id", business_id)
        .eq("id", session.get("active_version_id"))
        .limit(1)
        .execute()
    ).data or []
    job_rows = (
        supabase.table("hr_job_postings")
        .select("*")
        .eq("business_id", business_id)
        .eq("id", session.get("job_posting_id"))
        .limit(1)
        .execute()
    ).data or []
    return {
        "session": session,
        "version": version_rows[0] if version_rows else {},
        "job": job_rows[0] if job_rows else {},
    }


def _instructions(context: dict[str, Any]) -> str:
    session = context["session"]
    snapshot = context["version"].get("snapshot") or {}
    job = context["job"]
    questions = [item for item in (snapshot.get("questions") or []) if item.get("enabled", True)]
    formatted_questions = "\n".join(
        f"{idx + 1}. {item.get('question_text') or ''} "
        f"(question_id={item.get('id') or idx}, max_follow_ups={item.get('max_follow_ups', 0)})"
        for idx, item in enumerate(questions)
    )
    return f"""
You are Emily, an AI interviewer for AI Employees.

Candidate: {session.get('candidate_name') or 'Candidate'}
Job title: {job.get('title') or 'this role'}

Use ONLY the published interview questions below. Do not create unrelated interview questions.
Ask questions in this exact order. You may ask brief clarification/follow-up questions only when the listed max_follow_ups allows it.

Opening script:
{snapshot.get('opening_message') or EMILY_INTRO_FALLBACK}

Published questions:
{formatted_questions}

Closing script:
{snapshot.get('closing_message') or 'Thank you for your time. A recruiter will review your interview and follow up.'}

Rules:
- Keep the session structured, calm, and professional.
- Do not ask about protected characteristics, salary history, family status, medical history, age, religion, race, national origin, disability, marital status, pregnancy, sexual orientation, union membership, or citizenship beyond lawful work authorization.
- Do not make a hire/no-hire decision to the candidate.
- At the end, thank the candidate and say a recruiter will review the interview.
"""


async def _score_and_store(supabase, business_id: str, session_id: str, context: dict[str, Any]) -> None:
    transcript = (
        supabase.table("hr_interview_transcript_turns")
        .select("speaker,text,question_id,question_order,sequence_order")
        .eq("business_id", business_id)
        .eq("session_id", session_id)
        .order("sequence_order")
        .execute()
    ).data or []
    if not transcript:
        return

    snapshot = context["version"].get("snapshot") or {}
    client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY", ""), timeout=45.0, max_retries=1)
    response = await client.chat.completions.create(
        model=INTERVIEW_SCORING_MODEL,
        temperature=0.2,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": (
                    "Create an advisory structured interview outcome packet. Return JSON only. "
                    "Do not infer protected traits. Recommendations are human-reviewed and not final decisions."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "rubric": snapshot.get("rubric") or [],
                        "questions": snapshot.get("questions") or [],
                        "transcript": transcript,
                        "schema": {
                            "total_score": 0,
                            "recommendation": "review",
                            "summary": "",
                            "strengths": [],
                            "concerns": [],
                            "criterion_scores": [],
                        },
                    }
                ),
            },
        ],
    )
    payload = json.loads(response.choices[0].message.content or "{}")
    recommendation = str(payload.get("recommendation") or "review").lower().replace(" ", "_")
    if recommendation not in {"strong_hire", "hire", "review", "no_hire"}:
        recommendation = "review"
    row = {
        "business_id": business_id,
        "session_id": session_id,
        "model": INTERVIEW_SCORING_MODEL,
        "total_score": max(0, min(100, float(payload.get("total_score") or 0))),
        "recommendation": recommendation,
        "summary": str(payload.get("summary") or ""),
        "strengths": payload.get("strengths") if isinstance(payload.get("strengths"), list) else [],
        "concerns": payload.get("concerns") if isinstance(payload.get("concerns"), list) else [],
        "criterion_scores": payload.get("criterion_scores") if isinstance(payload.get("criterion_scores"), list) else [],
    }
    existing = (
        supabase.table("hr_interview_outcomes")
        .select("id")
        .eq("business_id", business_id)
        .eq("session_id", session_id)
        .limit(1)
        .execute()
    ).data or []
    if existing:
        supabase.table("hr_interview_outcomes").update(row).eq("id", existing[0]["id"]).execute()
    else:
        supabase.table("hr_interview_outcomes").insert(row).execute()


class EmilyInterviewAgent(Agent):
    pass


@server.rtc_session(agent_name=HR_INTERVIEWER_AGENT_NAME)
async def hr_interviewer_agent(ctx: agents.JobContext):
    await ctx.connect(auto_subscribe=agents.AutoSubscribe.AUDIO_ONLY)
    participant = await ctx.wait_for_participant()

    business_id: str | None = None
    session_id: str | None = None
    avatar_enabled = True
    raw_meta = participant.metadata
    if isinstance(raw_meta, str) and raw_meta:
        try:
            meta = json.loads(raw_meta)
            business_id = meta.get("business_id")
            session_id = meta.get("session_id")
        except json.JSONDecodeError:
            logger.warning("Invalid participant metadata: %s", raw_meta)
    raw_job = getattr(ctx.job, "metadata", None)
    if isinstance(raw_job, str) and raw_job:
        try:
            job_meta = json.loads(raw_job)
            business_id = business_id or job_meta.get("business_id")
            session_id = session_id or job_meta.get("session_id")
            avatar_enabled = bool(job_meta.get("avatar_enabled", True))
        except json.JSONDecodeError:
            logger.warning("Invalid job metadata: %s", raw_job)

    if not business_id or not session_id:
        logger.error("Emily started without business_id/session_id")
        return

    supabase = _get_supabase()
    if not supabase:
        logger.error("Emily cannot start without Supabase")
        return

    context = _load_session_context(supabase, business_id, session_id)
    if not context:
        logger.error("Emily could not load session context: %s", session_id)
        return

    assistant = EmilyInterviewAgent(instructions=_instructions(context))
    session = AgentSession(
        llm=openai.realtime.RealtimeModel(voice=os.getenv("EMILY_OPENAI_VOICE", "shimmer"), temperature=0.25),
        preemptive_generation=True,
    )

    avatar: liveavatar.AvatarSession | None = None
    if avatar_enabled and EMILY_AVATAR_ID:
        try:
            avatar = liveavatar.AvatarSession(avatar_id=EMILY_AVATAR_ID)
            await avatar.start(session, room=ctx.room)
            logger.info("Emily HeyGen LiveAvatar started — avatar_id=%s", EMILY_AVATAR_ID)
        except Exception as exc:
            logger.warning("Emily LiveAvatar failed; continuing voice-only: %s", exc)
    else:
        reason = "avatar disabled by user" if EMILY_AVATAR_ID else "EMILY_AVATAR_ID not set"
        logger.info("Emily running without avatar — %s", reason)

    transcript_log: list[dict[str, Any]] = []
    seq_counter = 0
    started_at = datetime.now(timezone.utc)

    @session.on("conversation_item_added")
    def _on_item_added(ev) -> None:
        nonlocal seq_counter
        try:
            item = getattr(ev, "item", ev)
            role = getattr(item, "role", None)
            if role not in ("user", "assistant"):
                return
            text = ""
            if hasattr(item, "text_content"):
                text = item.text_content or ""
            elif hasattr(item, "content"):
                for block in item.content:
                    if hasattr(block, "text") and block.text:
                        text += block.text
            text = text.strip()
            if not text:
                return
            seq_counter += 1
            row = {
                "business_id": business_id,
                "session_id": session_id,
                "speaker": "candidate" if role == "user" else "interviewer",
                "text": text,
                "sequence_order": seq_counter,
            }
            transcript_log.append(row)
            asyncio.ensure_future(_publish(ctx.room, {"type": "transcript_turn", **row}))
        except Exception as exc:
            logger.warning("Emily transcript capture failed: %s", exc)

    @ctx.room.on("data_received")
    def _on_data(data_packet) -> None:
        try:
            payload = json.loads(bytes(data_packet.data).decode())
            if payload.get("type") == "stop_avatar":
                async def _stop_avatar() -> None:
                    nonlocal avatar
                    if avatar is None:
                        await _publish(ctx.room, {"type": "avatar_stopped"})
                        return
                    try:
                        await avatar.aclose()
                    except Exception as exc:
                        logger.warning("Emily avatar stop failed: %s", exc)
                    finally:
                        avatar = None
                        await _publish(ctx.room, {"type": "avatar_stopped"})

                asyncio.ensure_future(_stop_avatar())
        except Exception as exc:
            logger.warning("Emily data handler failed: %s", exc)

    await session.start(room=ctx.room, agent=assistant, room_options=room_io.RoomOptions())
    await _publish(ctx.room, {"type": "interviewer_state", "state": "started", "name": "Emily"})

    egress_id, storage_path = await _start_egress(ctx.room.name, session_id, business_id)
    if egress_id and storage_path:
        supabase.table("hr_interview_recordings").insert({
            "business_id": business_id,
            "session_id": session_id,
            "storage_bucket": os.getenv("HR_INTERVIEW_RECORDINGS_BUCKET", "hr-interview-recordings"),
            "storage_path": storage_path,
            "status": "processing",
            "livekit_egress_id": egress_id,
            "started_at": started_at.isoformat(),
        }).execute()

    await session.generate_reply(instructions="Start the interview now using the opening script, then proceed through the published questions.")

    candidate_left = asyncio.Event()

    @ctx.room.on("participant_disconnected")
    def _on_participant_disconnected(p) -> None:
        if p.identity == participant.identity:
            candidate_left.set()

    try:
        await candidate_left.wait()
    finally:
        if egress_id:
            await _stop_egress(egress_id)
        duration_s = int((datetime.now(timezone.utc) - started_at).total_seconds())
        if transcript_log:
            try:
                supabase.table("hr_interview_transcript_turns").insert(transcript_log).execute()
            except Exception as exc:
                logger.warning("Emily transcript insert failed: %s", exc)
        if egress_id and storage_path:
            supabase.table("hr_interview_recordings").update({
                "status": "ready",
                "duration_seconds": duration_s,
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }).eq("business_id", business_id).eq("session_id", session_id).eq("livekit_egress_id", egress_id).execute()
        supabase.table("hr_interview_sessions").update({
            "status": "completed",
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "greenhouse_sync_status": "mocked",
        }).eq("business_id", business_id).eq("id", session_id).execute()
        try:
            await _score_and_store(supabase, business_id, session_id, context)
        except Exception as exc:
            logger.warning("Emily scoring failed: %s", exc)
        try:
            supabase.table("hr_interview_greenhouse_sync_events").insert({
                "business_id": business_id,
                "session_id": session_id,
                "action": "stage_update",
                "status": "mocked",
                "request_payload": {
                    "note": "Greenhouse stage mapping is prepared for Harvest validation.",
                    "target_stage": "AI Screen Completed",
                },
            }).execute()
        except Exception as exc:
            logger.warning("Emily Greenhouse sync event insert failed: %s", exc)
        if avatar:
            try:
                await avatar.aclose()
            except Exception:
                pass


if __name__ == "__main__":
    agents.cli.run_app(server)
