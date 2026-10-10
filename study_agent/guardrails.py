"""Governance and safety guardrails for Study Navigator.

Implements multi-layer defenses adapted from DevCamp:
1. Model Armor regional REST API when MODEL_ARMOR_TEMPLATE_ID is configured.
2. Built-in local heuristic sanitization against prompt injection, jailbreaks,
   system prompt extraction, and academic dishonesty when running locally without Cloud credentials.
"""

import logging
import os
import re
import threading
from typing import Any, Optional

import google.auth
import google.auth.transport.requests
import httpx
from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types as genai_types

log = logging.getLogger(__name__)

PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
MA_REGION = os.environ.get("MODEL_ARMOR_REGION", "europe-west2")
MA_TEMPLATE = os.environ.get("MODEL_ARMOR_TEMPLATE_ID", "")

REFUSAL = (
    "I can't help with that request — it was flagged by our safety and content integrity "
    "checks. Happy to help with your academic study schedule instead."
)

_creds = None
_creds_lock = threading.Lock()

# Heuristic patterns for local red-team / injection defense
_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?(previous|prior)\s+instructions", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+(dan|developer\s+mode|jailbroken)", re.IGNORECASE),
    re.compile(r"(print|dump|show|reveal|output)\s+(your\s+)?(full\s+)?system\s+prompt", re.IGNORECASE),
    re.compile(r"how\s+to\s+(cheat|hack|bypass|forge)\s+(on\s+)?(the\s+)?(exam|test|coursework|grades)", re.IGNORECASE),
    re.compile(r"(submit|generate)\s+fake\s+(coursework|marks|grades)", re.IGNORECASE),
]


def _token() -> Optional[str]:
    global _creds
    with _creds_lock:
        try:
            if _creds is None:
                _creds, _ = google.auth.default(
                    scopes=["https://www.googleapis.com/auth/cloud-platform"]
                )
            if not _creds.valid:
                _creds.refresh(google.auth.transport.requests.Request())
            return _creds.token
        except Exception:
            return None


def _headers() -> dict:
    tok = _token()
    headers = {"x-goog-user-project": PROJECT}
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    return headers


def is_flagged_by_local_heuristics(text: str) -> bool:
    """Checks input against known prompt-injection and academic dishonesty patterns."""
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(text):
            return True
    return False


def _sanitize(kind: str, text: str) -> bool:
    """Calls Model Armor if configured, falling back to local heuristics."""
    if is_flagged_by_local_heuristics(text):
        return True

    if not MA_TEMPLATE or not PROJECT:
        return False

    endpoint = (
        f"https://modelarmor.{MA_REGION}.rep.googleapis.com/v1/projects/"
        f"{PROJECT}/locations/{MA_REGION}/templates/{MA_TEMPLATE}:{kind}"
    )
    payload_key = "userPromptData" if kind == "sanitizeUserPrompt" else "modelResponseData"
    try:
        resp = httpx.post(
            endpoint,
            headers=_headers(),
            json={payload_key: {"text": text}},
            timeout=10,
        )
        if resp.status_code == 200:
            result = resp.json().get("sanitizationResult", {})
            filter_results = result.get("filterResults", {})
            for filter_name, wrapper in filter_results.items():
                if kind == "sanitizeModelResponse" and filter_name == "pi_and_jailbreak":
                    continue
                inner = next(iter(wrapper.values()), {}) if isinstance(wrapper, dict) else {}
                if inner.get("matchState") == "MATCH_FOUND":
                    log.warning("Model Armor %s blocked text (filter=%s)", kind, filter_name)
                    return True
    except Exception as e:
        log.warning("Model Armor call skipped due to error: %s", e)

    return False


def _latest_user_text(llm_request: LlmRequest) -> str:
    for content in reversed(llm_request.contents or []):
        if content.role == "user" and content.parts:
            texts = [p.text for p in content.parts if p.text]
            if texts:
                return "\n".join(texts)
    return ""


def guard_input(
    callback_context: CallbackContext, llm_request: LlmRequest
) -> Optional[LlmResponse]:
    """before_model_callback: Screen incoming user prompt at the trust boundary."""
    text = _latest_user_text(llm_request)
    if text and _sanitize("sanitizeUserPrompt", text):
        return LlmResponse(
            content=genai_types.Content(
                role="model", parts=[genai_types.Part.from_text(text=REFUSAL)]
            )
        )
    return None


def guard_output(
    callback_context: CallbackContext, llm_response: LlmResponse
) -> Optional[LlmResponse]:
    """after_model_callback: Screen agent output before delivery."""
    if not llm_response.content or not llm_response.content.parts:
        return None
    texts = [p.text for p in llm_response.content.parts if p.text]
    if texts and _sanitize("sanitizeModelResponse", "\n".join(texts)):
        return LlmResponse(
            content=genai_types.Content(
                role="model", parts=[genai_types.Part.from_text(text=REFUSAL)]
            )
        )
    return None
