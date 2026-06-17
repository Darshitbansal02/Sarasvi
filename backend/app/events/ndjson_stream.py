"""
NDJSON Stream — Line-delimited JSON serialization/deserialization.

RULE 1: NDJSON ONLY — never stream raw JSON arrays.
Each event is independently parsable as a single line.
"""

from __future__ import annotations

from typing import Any, AsyncIterator

import json
import orjson

from app.events.event_protocol import TimelineEventData


def serialize_event(event: TimelineEventData) -> bytes:
    """Serialize a TimelineEvent to a single NDJSON line (bytes)."""
    return json.dumps(event.model_dump(), sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"


def serialize_event_str(event: TimelineEventData) -> str:
    """Serialize a TimelineEvent to a single NDJSON line (string)."""
    return json.dumps(event.model_dump(), sort_keys=True, separators=(",", ":")) + "\n"


def serialize_dict(data: dict[str, Any]) -> bytes:
    """Serialize a dict to a single NDJSON line (bytes)."""
    return json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"


def remove_circular_references(obj, seen=None):
    """Recursively replace circular references with '[Circular]'."""
    if seen is None:
        seen = set()
    obj_id = id(obj)
    if obj_id in seen:
        return "[Circular]"
    if isinstance(obj, dict):
        seen.add(obj_id)
        res = {k: remove_circular_references(v, seen) for k, v in obj.items()}
        seen.remove(obj_id)
        return res
    elif isinstance(obj, (list, tuple)):
        seen.add(obj_id)
        res = [remove_circular_references(x, seen) for x in obj]
        seen.remove(obj_id)
        return res
    return obj


def serialize_dict_str(data: dict[str, Any]) -> str:
    """Serialize a dict to a single NDJSON line (string)."""
    try:
        return json.dumps(data, sort_keys=True, separators=(",", ":")) + "\n"
    except ValueError as e:
        import structlog
        structlog.get_logger(__name__).error(
            "json_serialization_failed_retrying_safe",
            error=str(e),
            keys=list(data.keys()) if isinstance(data, dict) else "not_a_dict",
        )
        safe_data = remove_circular_references(data)
        return json.dumps(safe_data, sort_keys=True, separators=(",", ":")) + "\n"


def deserialize_line(line: str | bytes) -> dict[str, Any]:
    """Deserialize a single NDJSON line to a dict."""
    if isinstance(line, str):
        line = line.strip()
        if not line:
            return {}
        return orjson.loads(line.encode("utf-8"))
    else:
        line = line.strip()
        if not line:
            return {}
        return orjson.loads(line)


def parse_event(line: str | bytes) -> TimelineEventData:
    """Parse a single NDJSON line into a TimelineEventData object."""
    data = deserialize_line(line)
    return TimelineEventData(**data)


async def ndjson_stream(
    events: list[TimelineEventData],
) -> AsyncIterator[str]:
    """Stream a list of events as NDJSON lines."""
    for event in events:
        yield serialize_event_str(event)


def batch_serialize(events: list[TimelineEventData]) -> str:
    """Serialize a batch of events to NDJSON string."""
    return "".join(serialize_event_str(e) for e in events)


def batch_deserialize(ndjson_text: str) -> list[dict[str, Any]]:
    """Deserialize a batch of NDJSON lines to list of dicts."""
    results = []
    for line in ndjson_text.strip().split("\n"):
        line = line.strip()
        if line:
            results.append(orjson.loads(line.encode("utf-8")))
    return results
