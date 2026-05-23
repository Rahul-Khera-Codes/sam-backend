import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

logging.basicConfig(level=logging.INFO)

from app.core.config import settings
from app.routers import (
    calls,
    settings as settings_router,
    forwarding,
    analytics,
    integrations,
    gmail_integrations,
    phone_numbers,
    support,
    locations,
    custom_schedules,
    roles as roles_router,
    billing as billing_router,
    appointments as appointments_router,
    documents as documents_router,
)
from app.services.scheduler_service import start_scheduler, stop_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(
    title="AI Voice Agent API",
    description="Backend for the AI Employees voice agent — LiveKit + GPT-4o Realtime",
    version="1.0.0",
    lifespan=lifespan,
)

# ── CORS ──────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────

app.include_router(calls.router)
app.include_router(settings_router.router)
app.include_router(forwarding.router)
app.include_router(analytics.router)
app.include_router(integrations.router)
app.include_router(gmail_integrations.router)
app.include_router(phone_numbers.router)
app.include_router(support.router)
app.include_router(locations.router)
app.include_router(custom_schedules.router)
app.include_router(roles_router.router)
app.include_router(billing_router.router)
app.include_router(appointments_router.router)
app.include_router(documents_router.router)


# ── Health check ──────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "service": "ai-voice-agent-api"}


@app.get("/")
async def root():
    return {"message": "AI Voice Agent API — see /docs for endpoints"}
