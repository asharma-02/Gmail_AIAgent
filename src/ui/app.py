"""
FastAPI application for the Secure AI Executive Assistant UI.

Serves the single-page frontend and exposes REST API endpoints
that wrap the AgentOrchestrator and supporting components.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from src.ui.routes import auth, agent, audit, schedule, tone

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Secure AI Executive Assistant",
    description="Safety-first AI agent for managing email workflows",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# API routers
# ---------------------------------------------------------------------------

app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])
app.include_router(agent.router, prefix="/api/agent", tags=["Agent"])
app.include_router(audit.router, prefix="/api/audit", tags=["Audit"])
app.include_router(schedule.router, prefix="/api/schedule", tags=["Scheduling"])
app.include_router(tone.router, prefix="/api/tone", tags=["Tone Profiles"])

# ---------------------------------------------------------------------------
# Static files & SPA fallback
# ---------------------------------------------------------------------------

_STATIC_DIR = Path(__file__).parent / "static"

app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


@app.get("/", include_in_schema=False)
async def serve_index() -> FileResponse:
    return FileResponse(str(_STATIC_DIR / "index.html"))


@app.get("/health")
async def health() -> dict:
    from src.ui.state import orchestrator
    llm_ready = orchestrator._llm_client is not None
    return {"status": "ok", "service": "secure-ai-executive-assistant", "llm_ready": llm_ready}
