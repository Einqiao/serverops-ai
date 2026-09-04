"""Incident draft construction, kept separate from persistence."""

from __future__ import annotations

import json
import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .rules import RuleMatch


@dataclass
class IncidentDraft:
    id: str
    room_id: str
    world_id: str
    type: str
    severity: str
    detected_at: str
    trigger: str
    evidence: list[str]
    summary: str = ""
    possible_causes: list[str] | dict[str, Any] = None
    suggestions: list[str] | dict[str, Any] = None
    status: str = "open"

    @property
    def fingerprint(self) -> str:
        evidence = sorted(
            {
                re.sub(r"^\s*\[[^\]]+\]\s*:\s*", "", str(line)).strip().lower()
                for line in self.evidence
            }
        )
        value = "|".join((str(self.room_id), str(self.world_id), self.type, *evidence))
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def as_record(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "room_id": self.room_id,
            "world_id": self.world_id,
            "type": self.type,
            "severity": self.severity,
            "detected_at": self.detected_at,
            "trigger": self.trigger,
            "evidence": json.dumps(self.evidence, ensure_ascii=False),
            "summary": self.summary,
            "possible_causes": json.dumps(self.possible_causes or [], ensure_ascii=False),
            "suggestions": json.dumps(self.suggestions or [], ensure_ascii=False),
            "status": self.status,
            "fingerprint": self.fingerprint,
            "occurrence_count": 1,
            "last_seen": self.detected_at,
        }


def build_incident(room_id: str, world_id: str, match: RuleMatch) -> IncidentDraft:
    detected_at = datetime.now(timezone.utc).isoformat()
    incident_id = f"{room_id}-{match.type}-{detected_at}"
    return IncidentDraft(
        id=incident_id,
        room_id=room_id,
        world_id=world_id,
        type=match.type,
        severity=match.severity,
        detected_at=detected_at,
        trigger=match.trigger,
        evidence=match.evidence,
        possible_causes=[],
        suggestions=[],
    )
