"""Convert DMP webhook events into persisted ServerOps records."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from storage.database import IncidentDatabase

from .models import DMPWebhookEvent

LOGGER = logging.getLogger(__name__)

SEVERITIES = {
    "game_start": "info",
    "game_stop": "info",
    "room_activated": "info",
    "room_deactivated": "warning",
    "keepalive_triggered": "warning",
    "online_player_updated": "info",
}


@dataclass(frozen=True)
class WebhookRecord:
    id: str
    source: str
    event_type: str
    room_id: int | str | None
    room_name: str
    timestamp: str
    severity: str
    summary: str
    raw_payload: dict[str, Any]
    created_at: str


def handle_event(event: DMPWebhookEvent, database: IncidentDatabase) -> WebhookRecord:
    severity = SEVERITIES.get(event.event_type, "info")
    timestamp = event.timestamp or datetime.now(timezone.utc).isoformat()
    event_id = f"dmp-webhook-{event.room_id}-{event.event_type}-{timestamp}"
    summary = event.event_zh or event.event_en or event.event_type or "未知 DMP 事件"
    record = WebhookRecord(
        id=event_id,
        source="dmp_webhook",
        event_type=event.event_type or "unknown",
        room_id=event.room_id,
        room_name=event.room_name,
        timestamp=timestamp,
        severity=severity,
        summary=summary,
        raw_payload=event.raw_payload,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    database.save_webhook_event(record)
    LOGGER.info(
        "webhook handled: event_type=%s room_id=%s room_name=%s",
        record.event_type,
        record.room_id,
        record.room_name,
    )
    return record
