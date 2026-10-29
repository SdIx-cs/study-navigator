"""Per-turn trace logging for the 4-Stage Study Navigator Pipeline.

Records per turn:
- raw input
- extracted event(s)
- state diff applied (before vs after + memory bank mutations)
- planner decision
- final output

Dumps to JSON per session under the `traces/` directory.
"""

import dataclasses
import datetime
import json
import logging
import os
import pathlib
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

TRACES_DIR = pathlib.Path(__file__).resolve().parents[2] / "traces"
TRACES_DIR.mkdir(parents=True, exist_ok=True)


def _serialize(obj: Any) -> Any:
    """Helper to convert dataclasses and enums into JSON-serializable types."""
    if dataclasses.is_dataclass(obj):
        return {k: _serialize(v) for k, v in dataclasses.asdict(obj).items()}
    if hasattr(obj, "value"):
        return obj.value
    if isinstance(obj, (list, tuple)):
        return [_serialize(item) for item in obj]
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    return obj


class _TraceTurnEntry(dict):
    """Dict representing a turn entry that automatically re-persists when updated."""

    def __init__(self, logger: "TraceLogger", session_id: str, trace_obj: Dict[str, Any], *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._logger = logger
        self._session_id = session_id
        self._trace_obj = trace_obj

    def __setitem__(self, key: str, value: Any) -> None:
        super().__setitem__(key, value)
        try:
            self._logger.save_trace(self._session_id, self._trace_obj)
        except Exception as e:
            log.warning("Failed to auto-persist updated trace for session %s: %s", self._session_id, e)


class TraceLogger:
    """Logs per-turn pipeline traces and saves them to session-scoped JSON files."""

    def __init__(self, trace_dir: Optional[pathlib.Path] = None):
        self.trace_dir = trace_dir or TRACES_DIR
        self.trace_dir.mkdir(parents=True, exist_ok=True)

    def get_session_file(self, session_id: str) -> pathlib.Path:
        safe_id = "".join(c for c in session_id if c.isalnum() or c in ("-", "_"))
        if not safe_id:
            safe_id = "default_session"
        return self.trace_dir / f"{safe_id}.json"

    def save_trace(self, session_id: str, trace: Dict[str, Any]) -> None:
        path = self.get_session_file(session_id)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(trace, f, indent=2)

    def load_trace(self, session_id: str) -> Dict[str, Any]:
        path = self.get_session_file(session_id)
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                log.warning("Failed to load existing trace for session %s: %s", session_id, e)
        return {"session_id": session_id, "user_id": None, "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(), "turns": []}

    def log_turn(
        self,
        session_id: str,
        user_id: str,
        raw_input: str,
        extracted_event: Any,
        state_before: Dict[str, Any],
        state_after: Dict[str, Any],
        mutations: List[str],
        planner_decision: Any,
        final_output: Any,
    ) -> Dict[str, Any]:
        """Records a single turn into the session trace file."""
        trace = self.load_trace(session_id)
        trace["user_id"] = user_id
        trace["updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()

        turn_index = len(trace.get("turns", [])) + 1

        # Calculate state diff
        state_diff = {
            "mutations": mutations,
            "before": {k: state_before.get(k) for k in ("slice_stage", "active_intervention", "pending_proposal", "approval_status")},
            "after": {k: state_after.get(k) for k in ("slice_stage", "active_intervention", "pending_proposal", "approval_status")},
        }

        turn_entry = _TraceTurnEntry(
            self,
            session_id,
            trace,
            {
                "turn_index": turn_index,
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "raw_input": raw_input,
                "elapsed_time_ms": None,
                "extraction_method": getattr(extracted_event, "extraction_method", None) or "regex",
                "extracted_event": _serialize(extracted_event),
                "state_diff_applied": state_diff,
                "planner_decision": _serialize(planner_decision),
                "final_output": _serialize(final_output),
            },
        )

        trace["turns"].append(turn_entry)
        self.save_trace(session_id, trace)

        return turn_entry


_default_tracer = TraceLogger()


def log_turn_trace(
    session_id: str,
    user_id: str,
    raw_input: str,
    extracted_event: Any,
    state_before: Dict[str, Any],
    state_after: Dict[str, Any],
    mutations: List[str],
    planner_decision: Any,
    final_output: Any,
) -> Dict[str, Any]:
    """Convenience helper to record a turn trace."""
    return _default_tracer.log_turn(
        session_id=session_id,
        user_id=user_id,
        raw_input=raw_input,
        extracted_event=extracted_event,
        state_before=state_before,
        state_after=state_after,
        mutations=mutations,
        planner_decision=planner_decision,
        final_output=final_output,
    )
