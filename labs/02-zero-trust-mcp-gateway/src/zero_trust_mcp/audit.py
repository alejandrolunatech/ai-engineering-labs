"""Redacted audit events for the gateway.

One tool call produces several events linked by `decision_id`, so that
"requested", "denied"/"allowed", and "executed" stay separate signals:

    requested -> denied
    requested -> allowed -> executed | downstream_failed

Arguments are NOT logged in full. Only argument names are recorded, plus a
small allowlist of short identifier/amount fields. Free-text fields such as
`reason` and `query` may carry PII or injected text and are never logged.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SAFE_ARGUMENT_FIELDS = ("order_id", "customer_id", "amount_eur")
MAX_TEXT = 64
MAX_KEYS = 20


def _clip(value: str) -> str:
    return value if len(value) <= MAX_TEXT else value[:MAX_TEXT] + "…"


def summarize_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    keys = sorted(_clip(str(k)) for k in arguments)[:MAX_KEYS]
    safe: dict[str, Any] = {}
    for field in SAFE_ARGUMENT_FIELDS:
        value = arguments.get(field)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            safe[field] = value
        elif isinstance(value, str):
            safe[field] = _clip(value)
    return {"argument_keys": keys, "arguments_summary": safe}


class AuditLog:
    """Append-only event list, optionally mirrored to a JSONL file. Never writes to stdout."""

    def __init__(self, path: Path | None = None) -> None:
        self.events: list[dict[str, Any]] = []
        self._path = path

    def record(self, event: str, decision_id: str, **fields: Any) -> None:
        entry = {
            "event": event,
            "decision_id": decision_id,
            "timestamp": datetime.now(UTC).isoformat(),
            **fields,
        }
        self.events.append(entry)
        if self._path is not None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, default=str) + "\n")
