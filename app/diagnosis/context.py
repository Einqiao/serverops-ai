"""Collect a bounded diagnostic snapshot after a DMP webhook event."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from app.dmp.client import DMPAPIError, DMPClient

if TYPE_CHECKING:
    from app.webhook.models import DMPWebhookEvent


@dataclass
class DiagnosisContext:
    event_type: str
    event_timestamp: str
    room_id: int | str | None
    room_name: str
    world_id: str
    collected_at: str
    server_status: dict[str, Any]
    recent_logs: list[str]
    collection_errors: list[str]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def collect_diagnosis_context(
    client: DMPClient,
    event: "DMPWebhookEvent",
    log_lines: int = 200,
) -> DiagnosisContext:
    room_id = event.room_id
    room_id_text = str(room_id) if room_id is not None else ""
    server_status: dict[str, Any] = {}
    recent_logs: list[str] = []
    errors: list[str] = []
    world_id = _find_payload_world_id(event.data)
    world_id_error = ""

    if not room_id_text:
        errors.append("Webhook payload missing roomId")
    else:
        try:
            room_status = client.get_room_status(room_id_text)
            server_status["room"] = _sanitize(room_status)
            if world_id is None:
                world_id, world_id_error = _find_world_id(room_status)
                if world_id_error:
                    errors.append(world_id_error)
        except (DMPAPIError, ValueError, TypeError) as exc:
            errors.append(f"room status: {exc}")

        try:
            system_status = client.get_system_status()
            server_status["system"] = _sanitize(system_status)
        except (DMPAPIError, ValueError, TypeError) as exc:
            errors.append(f"system status: {exc}")

        try:
            players = client.get_online_players(room_id_text)
            server_status["online_players"] = _sanitize(players)
        except (DMPAPIError, ValueError, TypeError) as exc:
            errors.append(f"online players: {exc}")

        if world_id is None:
            errors.append("无法确定目标 world_id，跳过游戏日志采集")
        else:
            try:
                payload = client.get_game_logs(
                    room_id_text,
                    lines=max(1, min(log_lines, 1000)),
                    cursor=world_id,
                )
                recent_logs = _logs(payload)
            except (DMPAPIError, ValueError, TypeError) as exc:
                errors.append(f"game logs: {exc}")

    return DiagnosisContext(
        event_type=event.event_type,
        event_timestamp=event.timestamp,
        room_id=room_id,
        room_name=event.room_name,
        world_id=world_id,
        collected_at=datetime.now(timezone.utc).isoformat(),
        server_status=server_status,
        recent_logs=recent_logs,
        collection_errors=errors,
    )


def _find_payload_world_id(data: Any) -> str | None:
    if isinstance(data, dict):
        for key in ("worldId", "world_id", "worldID"):
            if data.get(key) is not None:
                return str(data[key])
    return None


def _find_world_id(value: Any) -> tuple[str | None, str]:
    if isinstance(value, dict):
        worlds = value.get("worlds")
        if isinstance(worlds, list):
            if len(worlds) == 1 and isinstance(worlds[0], dict):
                for key in ("worldID", "worldId", "id"):
                    if worlds[0].get(key) is not None:
                        return str(worlds[0][key]), ""
            if len(worlds) > 1:
                return None, "room_status 包含多个 world，无法确定 keepalive_triggered 对应的 world_id"
        for key in ("worldID", "worldId", "world_id", "id"):
            if value.get(key) is not None:
                return str(value[key]), ""
        nested = value.get("world")
        if isinstance(nested, dict):
            return _find_world_id(nested)
    return None, ""


def _logs(value: Any) -> list[str]:
    if isinstance(value, str):
        return value.splitlines()
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, dict):
        for key in ("lines", "logs", "items", "data"):
            if key in value:
                return _logs(value[key])
    return []


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        blocked = {"password", "token", "secret", "clusterkey", "jwt"}
        return {
            str(key): _sanitize(item)
            for key, item in value.items()
            if str(key).lower().replace("_", "") not in blocked
        }
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    return value
