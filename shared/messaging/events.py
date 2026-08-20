"""Versioned, compact BWM semantic event envelope."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from typing import Any, Mapping
from uuid import uuid4

SCHEMA_VERSION = 1
INSTALLATION_ACTIVATION = "installation.activation"


class EventValidationError(ValueError):
    """Raised when an external semantic message is not a valid BWM envelope."""


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class SemanticEvent:
    event_type: str
    origin: str
    payload: Mapping[str, Any]
    id: str = field(default_factory=lambda: str(uuid4()))
    timestamp: str = field(default_factory=_timestamp)
    version: int = SCHEMA_VERSION

    def __post_init__(self):
        if self.version != SCHEMA_VERSION:
            raise EventValidationError(f"Unsupported BWM event version: {self.version!r}")
        if not isinstance(self.id, str) or not self.id.strip():
            raise EventValidationError("Event id must be a non-empty string")
        if not isinstance(self.event_type, str) or not self.event_type.strip():
            raise EventValidationError("Event type must be a non-empty string")
        if not isinstance(self.origin, str) or not self.origin.strip():
            raise EventValidationError("Event origin must be a non-empty string")
        if not isinstance(self.payload, Mapping):
            raise EventValidationError("Event payload must be an object")
        if not isinstance(self.timestamp, str) or not self.timestamp.strip():
            raise EventValidationError("Event timestamp must be a non-empty string")
        try:
            datetime.fromisoformat(self.timestamp.replace("Z", "+00:00"))
        except ValueError as exc:
            raise EventValidationError("Event timestamp must be ISO-8601") from exc

    def to_dict(self) -> dict[str, Any]:
        return {"version": self.version, "id": self.id, "type": self.event_type,
                "origin": self.origin, "timestamp": self.timestamp, "payload": dict(self.payload)}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), separators=(",", ":"), sort_keys=True)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SemanticEvent":
        if not isinstance(data, Mapping):
            raise EventValidationError("Event envelope must be an object")
        required = {"version", "id", "type", "origin", "timestamp", "payload"}
        missing = required.difference(data)
        if missing:
            raise EventValidationError(f"Event envelope is missing: {', '.join(sorted(missing))}")
        unexpected = set(data).difference(required)
        if unexpected:
            raise EventValidationError(f"Event envelope has unsupported fields: {', '.join(sorted(unexpected))}")
        return cls(event_type=data["type"], origin=data["origin"], payload=data["payload"],
                   id=data["id"], timestamp=data["timestamp"], version=data["version"])

    @classmethod
    def from_json(cls, raw: str | bytes) -> "SemanticEvent":
        try:
            return cls.from_dict(json.loads(raw))
        except (TypeError, json.JSONDecodeError) as exc:
            raise EventValidationError("Event payload is not valid JSON") from exc


def installation_activation(origin: str, state: str, **kwargs: Any) -> SemanticEvent:
    if state not in {"active", "inactive"}:
        raise EventValidationError("Installation activation state must be 'active' or 'inactive'")
    return SemanticEvent(INSTALLATION_ACTIVATION, origin, {"state": state}, **kwargs)
