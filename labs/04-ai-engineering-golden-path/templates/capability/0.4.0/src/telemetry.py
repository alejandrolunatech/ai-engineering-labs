"""OpenTelemetry-STYLE structured telemetry for this capability.

This is not an OpenTelemetry SDK, exporter or backend. It produces small
span-like records (name, trace id, parent, duration, status, attributes,
events) that follow OTel concepts, validates every record against
platform/telemetry-record.schema.json, and hands it to a local sink.

Three concerns are kept separate:
  capability outcome   decided by capability.run; telemetry never changes it
  record validity      TelemetryContractError: a programming error, raised loudly
  record delivery      TelemetryDeliveryError: a sink failed to write. It is
                       collected in `delivery_failures` and never raised into
                       the capability flow, so it can never cause a model retry
                       or make a model call look like it failed.

Bridging to OpenTelemetry later (NOT implemented): an OTelSink.emit(record)
could call tracer.start_span(record["name"], start_time=record["start_time_unix_ns"],
attributes={k: v for k, v in record["attributes"].items() if v is not None})
and end it at start + duration. OTel attributes cannot be null, so unknown
values would be omitted, and the explicit *.status attributes carry the
"unknown". usage.* could map to the gen_ai.usage.* semantic conventions.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator, Protocol, TextIO

from contracts import PROJECT_ROOT, describe_errors, parse_json_strict

TELEMETRY_SCHEMA_FILE = "platform/telemetry-record.schema.json"

_IDENTIFIER = re.compile(r"[A-Za-z0-9._:-]{1,128}")
_MODEL_LABEL = re.compile(r"[A-Za-z0-9._:/@-]{1,128}")


class TelemetryContractError(Exception):
    """A telemetry record violated the telemetry contract. A programming error."""


class TelemetryDeliveryError(Exception):
    """A sink could not deliver a record. Never changes the capability outcome."""


def new_identifier() -> str:
    return uuid.uuid4().hex


def is_valid_identifier(value: Any) -> bool:
    return isinstance(value, str) and _IDENTIFIER.fullmatch(value) is not None


def safe_model_label(value: Any) -> str:
    """Adapter-reported labels are untrusted; anything unexpected is not recorded."""
    return value if isinstance(value, str) and _MODEL_LABEL.fullmatch(value) else "unrecognized"


class Clock(Protocol):
    def monotonic_ns(self) -> int: ...

    def time_ns(self) -> int: ...


class SystemClock:
    def monotonic_ns(self) -> int:
        return time.perf_counter_ns()

    def time_ns(self) -> int:
        return time.time_ns()


class Sink(Protocol):
    def emit(self, record: dict) -> None: ...


class NullSink:
    """Discards records. Used only when a library caller passes no telemetry."""

    def emit(self, record: dict) -> None:
        pass


class InMemorySink:
    def __init__(self) -> None:
        self.records: list[dict] = []

    def emit(self, record: dict) -> None:
        self.records.append(record)


class JsonlSink:
    """Writes one JSON object per line to an already-open text stream."""

    def __init__(self, stream: TextIO):
        self._stream = stream

    def emit(self, record: dict) -> None:
        try:
            self._stream.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
            self._stream.flush()
        except (OSError, ValueError) as exc:  # ValueError: write to a closed stream
            raise TelemetryDeliveryError(f"telemetry sink write failed: {type(exc).__name__}") from None


class Span:
    def __init__(self, name: str, span_id: str, parent_span_id: str | None):
        self.name = name
        self.span_id = span_id
        self.parent_span_id = parent_span_id
        self.status = "ok"
        self.attributes: dict[str, Any] = {}
        self.events: list[dict] = []
        self.declared_max_latency_ms: int | None = None

    def set(self, key: str, value: Any) -> None:
        self.attributes[key] = value

    def set_all(self, attributes: dict[str, Any]) -> None:
        self.attributes.update(attributes)

    def event(self, name: str, attributes: dict[str, Any]) -> None:
        self.events.append({"name": name, "attributes": dict(attributes)})

    def fail(self, error_type: str) -> None:
        self.status = "error"
        self.attributes["error.type"] = error_type


class Telemetry:
    """One instance per capability run (one trace)."""

    def __init__(
        self,
        sink: Sink,
        *,
        correlation_id: str,
        base_attributes: dict[str, Any] | None = None,
        clock: Clock | None = None,
        new_trace_id: Callable[[], str] = new_identifier,
        root: Path = PROJECT_ROOT,
    ):
        if not is_valid_identifier(correlation_id):
            raise TelemetryContractError("correlation id must match [A-Za-z0-9._:-]{1,128}")
        self.sink = sink
        self.correlation_id = correlation_id
        self.trace_id = new_trace_id()
        self.clock = clock or SystemClock()
        self.delivery_failures: list[TelemetryDeliveryError] = []
        self._base_attributes = dict(base_attributes or {})
        self._schema = parse_json_strict((root / TELEMETRY_SCHEMA_FILE).read_text(encoding="utf-8"))
        self._next_span = 0

    @contextmanager
    def span(self, name: str, parent: Span | None = None) -> Iterator[Span]:
        self._next_span += 1
        span = Span(name, str(self._next_span), parent.span_id if parent else None)
        if parent is None:
            span.set_all(self._base_attributes)
        start_wall = self.clock.time_ns()
        start = self.clock.monotonic_ns()
        try:
            yield span
        except BaseException as exc:
            if span.status == "ok":
                span.fail(type(exc).__name__)
            raise
        finally:
            duration_ms = (self.clock.monotonic_ns() - start) / 1_000_000
            if span.declared_max_latency_ms is not None:
                span.set("latency.over_declared_max", duration_ms > span.declared_max_latency_ms)
            self._finish(
                {
                    "record": "span",
                    "name": span.name,
                    "trace_id": self.trace_id,
                    "span_id": span.span_id,
                    "parent_span_id": span.parent_span_id,
                    "correlation_id": self.correlation_id,
                    "start_time_unix_ns": start_wall,
                    "duration_ms": round(duration_ms, 3),
                    "status": span.status,
                    "attributes": span.attributes,
                    "events": span.events,
                }
            )

    def _finish(self, record: dict) -> None:
        problems = describe_errors(self._schema, record, limit=20)
        if problems:
            raise TelemetryContractError(f"record violates {TELEMETRY_SCHEMA_FILE}: {problems}")
        try:
            self.sink.emit(record)
        except TelemetryDeliveryError as exc:
            self.delivery_failures.append(exc)
