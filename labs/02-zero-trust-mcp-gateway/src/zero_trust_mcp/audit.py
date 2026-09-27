"""Redacted audit evidence for the gateway.

One tool call produces several events linked by `decision_id`, so that
"requested", "denied"/"allowed", and "executed" stay separate signals:

    requested -> denied
    requested -> allowed -> executed | downstream_failed

Every event repeats the trusted context and policy provenance so each line
is self-describing. Execution evidence is tri-state:

    downstream_executed=false, execution_status="not_invoked"  gateway never called the tool
    downstream_executed=true,  execution_status="completed"    tool call returned a result
    downstream_executed=null,  execution_status="unknown"      call raised after invocation

"completed" means the downstream returned a response. It does not claim that
a business side effect did or did not happen; the executor's state is the
authority for that.

What is never logged: argument values other than id-shaped order_id /
customer_id and numeric amount_eur; free text (reason, query, notes);
values of spoofed authority fields; downstream results; exception messages.
Caller-controlled strings are format-checked before selected values are
written, which reduces obvious free-text injection into the log. Shape is not
a sensitivity classifier, however: an identifier-shaped value may still be
sensitive. Treat audit storage as sensitive; a production system should bind
resource IDs to trusted state or pseudonymize them rather than assuming a
regex proves that a value is safe.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SAFE_ID_FIELDS = ("order_id", "customer_id")
SAFE_NUMBER_FIELDS = ("amount_cents",)
SPOOFABLE_AUTHORITY_KEYS = frozenset({"role", "is_admin", "human_approved", "principal", "principal_id", "admin"})

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")  # argument key names
_ID_VALUE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")  # order_id / customer_id values
_TOOL_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
MAX_KEYS = 20
MAX_POLICY_TEXT = 200

INVALID_TOOL_NAME = "<invalid_tool_name>"
REDACTED_ID = "<redacted:not_id_shaped>"


def safe_tool_name(tool_name: Any) -> str:
    return tool_name if isinstance(tool_name, str) and _TOOL_NAME.match(tool_name) else INVALID_TOOL_NAME


def clip_policy_text(value: Any) -> str:
    # reason/rule_id come from the PDP, but a broken or hostile PDP could return anything.
    text = value if isinstance(value, str) else str(value)
    return text if len(text) <= MAX_POLICY_TEXT else text[:MAX_POLICY_TEXT] + "…"


def summarize_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    """Key names (identifier-shaped only) plus a tiny allowlist of safe values."""
    listed = sorted(k for k in arguments if isinstance(k, str) and _IDENTIFIER.match(k))
    safe: dict[str, Any] = {}
    for name in SAFE_ID_FIELDS:
        value = arguments.get(name)
        if isinstance(value, str):
            safe[name] = value if _ID_VALUE.match(value) else REDACTED_ID
    for name in SAFE_NUMBER_FIELDS:
        value = arguments.get(name)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            safe[name] = value
    return {
        "argument_keys": listed[:MAX_KEYS],
        "unlisted_argument_key_count": len(arguments) - min(len(listed), MAX_KEYS),
        # Key names only: shows spoofing was attempted without recording the claimed values.
        "spoofed_authority_keys": sorted(k for k in listed if k in SPOOFABLE_AUTHORITY_KEYS),
        "arguments_summary": safe,
    }


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
