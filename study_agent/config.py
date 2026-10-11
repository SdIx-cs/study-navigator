"""Configuration and Agent Runtime detection for Study Navigator (DevCamp Scale Pillar)."""

import logging
import os
import re
from typing import Optional, Dict

log = logging.getLogger(__name__)

_APP_URL_PROJECT_RE = re.compile(r"/projects/([^/]+)/")
_APP_URL_FULL_RE = re.compile(
    r"/projects/(?P<project>[^/]+)/locations/(?P<location>[^/]+)"
    r"/reasoningEngines/(?P<engine>\d+)"
)


def resolve_project() -> str:
    """Derives the Google Cloud project ID/number from environment or Agent Runtime APP_URL."""
    project = os.environ.get("GOOGLE_CLOUD_PROJECT", "").strip() or os.environ.get("PROJECT_ID", "").strip()
    if project:
        return project
    match = _APP_URL_PROJECT_RE.search(os.environ.get("APP_URL", ""))
    return match.group(1) if match else ""


def resolve_agent_engine() -> Optional[Dict[str, str]]:
    """Detects whether running on Agent Runtime; extracts project, location, and engine ID.

    When running on Google Cloud Agent Runtime, APP_URL is injected by the platform.
    Locally, returns None, which triggers fallback to DatabaseSessionService.
    """
    engine = os.environ.get("AGENT_ENGINE_ID", "").strip()
    match = _APP_URL_FULL_RE.search(os.environ.get("APP_URL", ""))
    if not engine and not match:
        return None

    resolved = {
        "project": resolve_project(),
        "location": os.environ.get("AGENT_ENGINE_LOCATION") or (match.group("location") if match else "us-central1"),
        "engine": engine or (match.group("engine") if match else ""),
    }
    return resolved if all(resolved.values()) else None
