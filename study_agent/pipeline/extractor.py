"""Stage 1: Event Extractor.

Turns a raw user message into a structured AcademicEvent and NOTHING else.
Does not call tools, does not mutate database/state, and does not generate advice.
Supports fast-path deterministic extraction with optional LLM fallback.
"""

import json
import logging
import os
import re
from typing import Any, Dict, Optional

from study_agent.pipeline.schema import AcademicEvent, EventType

log = logging.getLogger(__name__)

# Regex patterns for fast-path extraction
_LECTURE_RE = re.compile(
    r"(?:caught\s+up\s+on|completed|watched|finished|did|logged|studied)\s+(\d+)\s+([a-zA-Z0-9]+)\s+lectures?",
    re.IGNORECASE,
)
_LECTURE_RE_ALT = re.compile(
    r"(\d+)\s+([a-zA-Z0-9]+)\s+lectures?(?:\s+completed|\s+done)?",
    re.IGNORECASE,
)
_NAME_RE = re.compile(
    r"(?:call\s+me|my\s+name\s+is|preferred\s+name\s+is)\s+([a-zA-Z]+)",
    re.IGNORECASE,
)
_DURATION_ONLY_RE = re.compile(
    r"\b(\d+)\s*(h|hr|hour|hours|min|mins|minute|minutes|m)\b",
    re.IGNORECASE,
)
_HOUR_UNITS = {"h", "hr", "hour", "hours"}
_REVERT_RE = re.compile(
    r"\b(?:revert|undo|rollback|cancel\s+the\s+(?:switch|intervention|change))\b",
    re.IGNORECASE,
)
_CONFIRM_RE = re.compile(
    r"^(?:⚡\s*\[approved|yes\b|confirm\b|apply\s+this|proceed\b|apply\b|sure\b|sounds\s+good|let's\s+do\s+it|ok\b)",
    re.IGNORECASE,
)
_REJECT_RE = re.compile(
    r"^(?:❌\s*\[declined|decline\b|no\b|reject\b|do\s+not\s+apply|cancel\b|not\s+now)",
    re.IGNORECASE,
)
_SHRINK_MODIFY_RE = re.compile(
    r"(?:shrink\s+(?:the\s+session\s+)?to\s+(\d+)\s*(?:min|minute|m\b)|modify.*shrink|modification)",
    re.IGNORECASE,
)
_LEISURE_RE = re.compile(
    r"\b(?:play\s+basketball|play\s+football|go\s+for\s+a\s+run|having\s+lunch|lunch\s+with\s+friends|watch\s+a\s+movie|take\s+a\s+walk|gym)\b",
    re.IGNORECASE,
)
_CHECKIN_RE = re.compile(
    r"\b(?:check\s*in|checking\s*in|what(?:'s|\s+is)\s+best\s+to\s+do|what\s+should\s+i\s+(?:do|work\s+on)|plan\s+my\s+session|don't\s+feel\s+like\s+studying|feeling\s+(?:tired|exhausted|stuck|unmotivated))\b",
    re.IGNORECASE,
)
_COMPLETION_RE = re.compile(
    r"\b(?:completed|finished|done\s+with)\s+(?:(?:my|the|this)\s+)?(?:scheduled\s+|active\s+|current\s+)?(?:study\s+block|sprint|session|task|cw1|cw2|coursework)\b"
    r"|\b(?:finished\s+(?:it|the\s+task|the\s+sprint|the\s+block)|done\s+with|i(?:'ve|\s+have)\s+completed\s+it)\b",
    re.IGNORECASE,
)


class EventExtractor:
    """Extracts structured AcademicEvent from raw user message."""

    def __init__(self, use_llm_fallback: bool = False):
        self.use_llm_fallback = use_llm_fallback

    def extract(self, message: str, context: Optional[Dict[str, Any]] = None) -> AcademicEvent:
        """Parses a user message into a single structured AcademicEvent."""
        text = (message or "").strip()
        ctx = context or {}
        active_interv = ctx.get("active_intervention") or {}
        target_mod = active_interv.get("target_module") or ""

        # 1. Lecture Progress (Must explicitly mention lecture/lectures)
        m = _LECTURE_RE.search(text)
        if m:
            delta = int(m.group(1))
            module = m.group(2).upper()
            return AcademicEvent(
                type=EventType.LECTURE_PROGRESS,
                module=module,
                delta=delta,
                raw_text=text,
            )
        m = _LECTURE_RE_ALT.search(text)
        if m and "lecture" in text.lower():
            delta = int(m.group(1))
            module = m.group(2).upper()
            return AcademicEvent(
                type=EventType.LECTURE_PROGRESS,
                module=module,
                delta=delta,
                raw_text=text,
            )

        # 2. Revert intervention
        if _REVERT_RE.search(text):
            return AcademicEvent(
                type=EventType.INTERVENTION_REVERTED,
                reason=text,
                raw_text=text,
            )
        # 
        if ctx.get("slice_stage") == "awaiting_confirmation":
            dm = _DURATION_ONLY_RE.search(text)
            if dm  and not re.search(r"\d+\.\d+", text):
                amount = int(dm.group(1))
                unit = dm.group(2).lower()
                minutes = amount * 60 if unit in _HOUR_UNITS else amount
                return AcademicEvent(
                    type=EventType.INTERVENTION_MODIFIED,
                    modified_details=f"SHRINK the session to {minutes} minutes",
                    raw_text=text,
                )

        # 3. Modification / Confirmation / Rejection
        sm = _SHRINK_MODIFY_RE.search(text)
        if sm:
            dur = sm.group(1) if sm.groups() and sm.group(1) else "30"
            return AcademicEvent(
                type=EventType.INTERVENTION_MODIFIED,
                modified_details=f"SHRINK the session to {dur} minutes",
                raw_text=text,
            )
        if _CONFIRM_RE.search(text):
            return AcademicEvent(
                type=EventType.INTERVENTION_CONFIRMED,
                raw_text=text,
            )
        if _REJECT_RE.search(text):
            return AcademicEvent(
                type=EventType.INTERVENTION_REJECTED,
                raw_text=text,
            )

        # 4. Preferences (e.g. name)
        pm = _NAME_RE.search(text)
        if pm:
            return AcademicEvent(
                type=EventType.PREFERENCE_UPDATED,
                key="preferred_name",
                value=pm.group(1).capitalize(),
                raw_text=text,
            )

        # 5. Coursework / Task completion
        if _COMPLETION_RE.search(text) or text.lower() in ("done", "finished", "it's done"):
            # Extract module if mentioned in text, otherwise fall back to active intervention
            mod = "AI" if "ai" in text.lower() else "DB" if "db" in text.lower() else (
                "AI" if "ai" in target_mod.lower() else "DB" if "db" in target_mod.lower() else target_mod
            )
            item = "cw1" if "cw1" in text.lower() or "1" in text or "coursework 1" in text.lower() else (
                "cw2" if "cw2" in text.lower() or "2" in text else "cw1"
            )
            return AcademicEvent(
                type=EventType.COURSEWORK_COMPLETED,
                module=mod.upper() if mod else None,
                item=item,
                notes=text,
                raw_text=text,
            )

        # 6. Casual conversation / leisure
        if _LEISURE_RE.search(text):
            return AcademicEvent(
                type=EventType.CASUAL_CONVERSATION,
                notes=text,
                raw_text=text,
            )

        # 7. Checkin / Workload decision request
        if _CHECKIN_RE.search(text):
            return AcademicEvent(
                type=EventType.CHECKIN_REQUESTED,
                reason=text,
                raw_text=text,
            )

        # 8. LLM Extraction Fallback if enabled
        if self.use_llm_fallback and len(text) > 3:
            llm_event = self._extract_via_llm(text, ctx)
            if llm_event:
                return llm_event

        # 9. Fallback: General query or task
        return AcademicEvent(
            type=EventType.GENERAL_QUERY,
            raw_text=text,
        )

    def _extract_via_llm(self, text: str, context: Dict[str, Any]) -> Optional[AcademicEvent]:
        """Calls Gemini with strict schema to extract structured JSON event."""
        try:
            from google import genai
            from google.genai import types

            api_key = os.environ.get("GEMINI_API_KEY")
            if not api_key:
                return None

            client = genai.Client()
            model_name = os.environ.get("STUDY_AGENT_MODEL", "gemini-2.5-flash")
            
            prompt = (
                "You are an Academic Event Extractor. Extract a single structured JSON event from the student's message.\n"
                "Allowed types: 'lecture_progress_updated', 'coursework_completed', 'task_added', 'preference_updated', "
                "'checkin_requested', 'casual_conversation', 'intervention_reverted', 'general_query'.\n\n"
                f"Student message: \"{text}\"\n\n"
                "Return ONLY a JSON object with keys: type, module, item, delta, key, value, notes, reason."
            )

            resp = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.0,
                ),
            )
            if resp.text:
                data = json.loads(resp.text)
                etype_str = data.get("type", "general_query")
                try:
                    etype = EventType(etype_str)
                except ValueError:
                    etype = EventType.GENERAL_QUERY

                return AcademicEvent(
                    type=etype,
                    module=data.get("module"),
                    item=data.get("item"),
                    delta=data.get("delta"),
                    key=data.get("key"),
                    value=data.get("value"),
                    notes=data.get("notes"),
                    reason=data.get("reason"),
                    raw_text=text,
                )
        except Exception as e:
            log.debug("LLM extraction skipped or failed: %s", e)
        return None


def extract_event(message: str, context: Optional[Dict[str, Any]] = None, use_llm_fallback: bool = False) -> AcademicEvent:
    """Convenience helper to extract an event."""
    return EventExtractor(use_llm_fallback=use_llm_fallback).extract(message, context)
