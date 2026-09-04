"""Collection of room, system, and player status."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.dmp.client import DMPClient


@dataclass
class StatusSnapshot:
    room_id: str
    world_id: str
    room_status: Any
    system_status: Any
    online_players: Any
    captured_at: str

    def as_context(self) -> dict[str, Any]:
        return {
            "room_id": self.room_id,
            "world_id": self.world_id,
            "room_status": self.room_status,
            "system_status": self.system_status,
            "online_players": self.online_players,
            "captured_at": self.captured_at,
        }


class StatusCollector:
    def __init__(self, client: DMPClient, room_id: str) -> None:
        self.client = client
        self.room_id = room_id

    @staticmethod
    def _world_id(status: Any) -> str:
        if isinstance(status, dict):
            worlds = status.get("worlds")
            if isinstance(worlds, list) and worlds and isinstance(worlds[0], dict):
                for key in ("worldID", "worldId", "id"):
                    if worlds[0].get(key) is not None:
                        return str(worlds[0][key])
            for key in ("world_id", "worldId", "id"):
                if status.get(key) is not None:
                    return str(status[key])
            nested = status.get("world")
            if isinstance(nested, dict) and nested.get("id") is not None:
                return str(nested["id"])
        return ""

    def collect_once(self) -> StatusSnapshot:
        room_status = self.client.get_room_status(self.room_id)
        return StatusSnapshot(
            room_id=self.room_id,
            world_id=self._world_id(room_status),
            room_status=room_status,
            system_status=self.client.get_system_status(),
            online_players=self.client.get_online_players(self.room_id),
            captured_at=datetime.now(timezone.utc).isoformat(),
        )
