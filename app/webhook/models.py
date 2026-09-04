"""Models for the DMP webhook contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class DMPWebhookEvent:
    event_type: str
    event_zh: str
    event_en: str
    timestamp: str
    room_id: int | str | None
    room_name: str
    name: str
    data: dict[str, Any]
    raw_payload: dict[str, Any]

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "DMPWebhookEvent":
        event = payload.get("event")
        if not isinstance(event, Mapping):
            raise ValueError("webhook payload.event must be an object")
        data = payload.get("data", {})
        if not isinstance(data, dict):
            raise ValueError("webhook payload.data must be an object")
        return cls(
            event_type=str(event.get("type", "")),
            event_zh=str(event.get("zh", "")),
            event_en=str(event.get("en", "")),
            timestamp=str(payload.get("timestamp", "")),
            room_id=payload.get("roomId"),
            room_name=str(payload.get("roomName", "")),
            name=str(payload.get("name", "")),
            data=data,
            raw_payload=dict(payload),
        )
