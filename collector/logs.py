"""Incremental recent-log collection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from app.dmp.client import DMPClient


@dataclass
class LogBatch:
    room_id: str
    lines: list[str]
    captured_at: str
    cursor: Optional[str] = None


class LogCollector:
    def __init__(
        self, client: DMPClient, room_id: str, world_id: str = "", recent_lines: int = 200
    ) -> None:
        self.client = client
        self.room_id = room_id
        self.world_id = world_id
        self.recent_lines = max(1, recent_lines)
        self._previous: list[str] = []
        self._cursor: Optional[str] = None

    @staticmethod
    def _normalize(payload: Any) -> tuple[list[str], Optional[str]]:
        cursor = None
        value = payload
        if isinstance(payload, dict):
            cursor = payload.get("next_cursor") or payload.get("cursor")
            value = payload.get("lines", payload.get("logs", payload.get("items", payload)))
        if isinstance(value, str):
            return value.splitlines(), cursor
        if isinstance(value, list):
            return [str(item) for item in value], cursor
        return [], cursor

    def collect_once(self) -> LogBatch:
        payload = self.client.get_game_logs(
            self.room_id, lines=self.recent_lines, cursor=self.world_id
        )
        current, cursor = self._normalize(payload)
        current = current[-self.recent_lines :]
        new_lines = current
        if self._previous:
            # The API usually returns a sliding window. Remove its overlapping suffix.
            for size in range(min(len(self._previous), len(current)), 0, -1):
                if self._previous[-size:] == current[:size]:
                    new_lines = current[size:]
                    break
        self._previous = current
        self._cursor = cursor or self._cursor
        return LogBatch(
            room_id=self.room_id,
            lines=new_lines,
            captured_at=datetime.now(timezone.utc).isoformat(),
            cursor=self._cursor,
        )
