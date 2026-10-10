"""Study Navigator FastAPI Production Server & Observability Bridge (Milestone 5).

Exposes root_agent to frontends (CopilotKit / web interface) with:
1. OpenTelemetry Cloud Trace & Cloud Logging export when GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY=true.
2. Endpoints for check-in dialogue, human confirmation gate, metrics inspection, and persistent audit history.
"""

import datetime
import json
import logging
import os
import pathlib
import sys
from typing import Any, Dict, Optional

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv
load_dotenv(REPO_ROOT / "study_agent" / ".env", override=True)

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from study_agent.agent import root_agent
from study_agent.db import get_intervention_history, init_db
from study_agent.tools import calculate_study_metrics

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# --- Telemetry Setup (adapted from DevCamp main.py) ---------------------------
if os.environ.get("GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY", "").lower() in ("true", "1"):
    try:
        import google.auth
        from google.adk.telemetry.google_cloud import get_gcp_exporters, get_gcp_resource
        from google.adk.telemetry.setup import maybe_set_otel_providers

        _credentials, _project = google.auth.default()
        maybe_set_otel_providers(
            otel_hooks_to_setup=[
                get_gcp_exporters(
                    enable_cloud_tracing=True,
                    enable_cloud_logging=True,
                    google_auth=(_credentials, _project),
                )
            ],
            otel_resource=get_gcp_resource(_project),
        )
        log.info("Exporting OpenTelemetry traces and logs to Google Cloud")
    except Exception as e:
        log.warning("OpenTelemetry cloud export skipped: %s", e)

# --- FastAPI App --------------------------------------------------------------
app = FastAPI(
    title="Study Navigator Production Service",
    description="Adaptive Study Navigator API with Human Approval Gate and Durable Audit Persistence",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

session_service = InMemorySessionService()
runner = Runner(agent=root_agent, session_service=session_service, app_name="study_navigator")

# Initialize database schema
init_db()


class ChatRequest(BaseModel):
    user_id: str = "student_1"
    session_id: str = "default_session"
    message: str


class ConfirmRequest(BaseModel):
    user_id: str = "student_1"
    session_id: str = "default_session"
    confirmed: bool
    modified_details: Optional[str] = None


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "app_name": "study_navigator",
        "model": os.environ.get("STUDY_AGENT_MODEL", "gemini-3.1-flash-lite"),
        "telemetry_enabled": os.environ.get("GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY", "").lower() in ("true", "1"),
        "guardrails_active": True,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }


@app.get("/api/metrics")
def get_metrics():
    """Returns current deterministic academic metrics."""
    return calculate_study_metrics()


@app.get("/api/interventions")
def list_interventions(limit: int = 20):
    """Returns historical applied interventions from SQLite store."""
    return {"interventions": get_intervention_history(limit=limit)}


@app.post("/api/chat")
async def chat(request: ChatRequest):
    """Processes a user check-in turn through root_agent."""
    session = await session_service.get_session(
        app_name="study_navigator", user_id=request.user_id, session_id=request.session_id
    )
    if not session:
        session = await session_service.create_session(
            app_name="study_navigator", user_id=request.user_id, session_id=request.session_id
        )

    response_text = ""
    tools_called = []

    async for event in runner.run_async(
        user_id=request.user_id,
        session_id=request.session_id,
        new_message=types.Content(role="user", parts=[types.Part(text=request.message)]),
    ):
        if event.content and event.content.parts:
            for part in event.content.parts:
                if part.text:
                    response_text += part.text + "\n"
                if part.function_call:
                    tools_called.append(part.function_call.name)

    updated_session = await session_service.get_session(
        app_name="study_navigator", user_id=request.user_id, session_id=request.session_id
    )
    state = dict(updated_session.state) if updated_session else {}

    return {
        "response": response_text.strip(),
        "tools_called": tools_called,
        "slice_stage": state.get("slice_stage", "evaluating"),
        "pending_proposal": state.get("pending_proposal"),
        "proposal_details": state.get("proposal_details"),
        "active_intervention": state.get("active_intervention"),
        "approval_status": state.get("approval_status"),
    }


@app.post("/api/confirm")
async def confirm(request: ConfirmRequest):
    """Handles the human confirmation boundary response."""
    session = await session_service.get_session(
        app_name="study_navigator", user_id=request.user_id, session_id=request.session_id
    )
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    reply_text = "Yes, please apply this intervention." if request.confirmed else "No, I reject this intervention."
    if request.modified_details:
        reply_text = f"Apply this intervention with modification: {request.modified_details}"

    # Process confirmation through the agent loop
    result = await chat(ChatRequest(
        user_id=request.user_id,
        session_id=request.session_id,
        message=reply_text,
    ))
    return result


# Mount static assets for web UI
STATIC_DIR = REPO_ROOT / "backend" / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
