from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.routers import calls, settings as settings_router, forwarding, analytics

app = FastAPI(
    title="AI Voice Agent API",
    description="Backend for the AI Employees voice agent — LiveKit + GPT-4o Realtime",
    version="1.0.0",
)

# ── CORS ──────────────────────────────────────
# Allow requests from the Lovable frontend

app.add_middleware(
    CORSMiddleware,
    # allow_origins=settings.cors_origins_list,
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


# ── Health check ──────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "service": "ai-voice-agent-api"}


@app.get("/")
async def root():
    return {"message": "AI Voice Agent API — see /docs for endpoints"}
