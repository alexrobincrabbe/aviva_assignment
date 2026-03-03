# app/domain/actions_log.py

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from app.domain.models import ThreadTriageResult


def _system_action_for(result: ThreadTriageResult) -> str:
    """
    Map triage classification to a system action.
    This is the "actions taken per email" required by the brief.
    """
    if result.classification == "action_required":
        return "queue_for_handler"
    if result.classification == "informational_archive":
        return "archive"
    if result.classification == "irrelevant":
        return "ignore"
    # Should never happen if schema is enforced
    return "unknown"


def build_actions_log(
    triage_results: List[ThreadTriageResult],
    run_id: str | None = None,
) -> List[Dict[str, Any]]:
    """
    Build per-thread action log records (JSONL-ready).
    """
    ts = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    records: List[Dict[str, Any]] = []
    for r in triage_results:
        system_action = _system_action_for(r)

        # A short reason string for audit/debug (deterministic)
        reason_parts = [r.classification]
        if r.classification == "action_required":
            reason_parts.append(r.priority)
        if r.due_by:
            reason_parts.append(f"due:{r.due_by}")

        record: Dict[str, Any] = {
            "thread_id": r.thread_id,
            "system_action": system_action,
            "classification": r.classification,
            "priority": r.priority,
            "due_by": r.due_by,
            "topic": r.topic,
            "required_actions": r.required_actions,
            "confidence": r.confidence,
            "reason": " ".join(reason_parts),
            "timestamp_utc": ts,
        }
        if run_id:
            record["run_id"] = run_id

        records.append(record)

    return records
