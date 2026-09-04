"""Minimal SQLite storage; JSON-valued fields are stored as TEXT."""

from __future__ import annotations

import json
import hashlib
import re
import sqlite3
import threading
import uuid
from pathlib import Path
from typing import Any


class IncidentDatabase:
    def __init__(self, path: str) -> None:
        self.path = Path(path)
        if str(self.path.parent) not in ("", "."):
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._memory_uri = ""
        self._memory_anchor = None
        if path == ":memory:":
            self._memory_uri = f"file:serverops-{id(self)}?mode=memory&cache=shared"
            self._memory_anchor = sqlite3.connect(self._memory_uri, uri=True, timeout=30)
        self._initialize_schema()

    @property
    def connection(self) -> sqlite3.Connection:
        connection = getattr(self._local, "connection", None)
        if connection is None:
            if self._memory_uri:
                connection = sqlite3.connect(self._memory_uri, uri=True, timeout=30)
            else:
                connection = sqlite3.connect(self.path, timeout=30)
            connection.row_factory = sqlite3.Row
            self._local.connection = connection
        return connection

    def _initialize_schema(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS incidents (
                id TEXT PRIMARY KEY,
                room_id TEXT NOT NULL,
                world_id TEXT,
                type TEXT NOT NULL,
                severity TEXT NOT NULL,
                detected_at TEXT NOT NULL,
                trigger TEXT NOT NULL,
                evidence TEXT NOT NULL,
                summary TEXT NOT NULL,
                possible_causes TEXT NOT NULL,
                suggestions TEXT NOT NULL,
                status TEXT NOT NULL,
                fingerprint TEXT,
                occurrence_count INTEGER NOT NULL DEFAULT 1,
                last_seen TEXT
            );
            CREATE TABLE IF NOT EXISTS webhook_events (
                id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                event_type TEXT NOT NULL,
                room_id TEXT,
                room_name TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                severity TEXT NOT NULL,
                summary TEXT NOT NULL,
                raw_payload TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        columns = {
            row["name"]
            for row in self.connection.execute("PRAGMA table_info(incidents)").fetchall()
        }
        for name, definition in (
            ("event_type", "TEXT"),
            ("fault_type", "TEXT"),
            ("probable_cause", "TEXT"),
            ("impact", "TEXT"),
            ("recommendations", "TEXT"),
            ("fingerprint", "TEXT"),
            ("occurrence_count", "INTEGER NOT NULL DEFAULT 1"),
            ("last_seen", "TEXT"),
        ):
            if name not in columns:
                self.connection.execute(f"ALTER TABLE incidents ADD COLUMN {name} {definition}")
        legacy_rows = self.connection.execute(
            "SELECT id, room_id, world_id, type, fault_type, evidence, fingerprint, last_seen "
            "FROM incidents WHERE fingerprint IS NULL"
        ).fetchall()
        for row in legacy_rows:
            self.connection.execute(
                "UPDATE incidents SET fingerprint = ?, last_seen = COALESCE(last_seen, detected_at), "
                "occurrence_count = COALESCE(occurrence_count, 1) WHERE id = ?",
                (_incident_fingerprint(dict(row)), row["id"]),
            )
        self.connection.commit()

    def save_incident(self, incident: Any) -> None:
        record = incident.as_record() if hasattr(incident, "as_record") else dict(incident)
        record.setdefault("fingerprint", _incident_fingerprint(record))
        record.setdefault("occurrence_count", 1)
        record.setdefault("last_seen", record.get("detected_at"))
        existing = self.connection.execute(
            "SELECT id FROM incidents WHERE fingerprint = ? AND status = 'open'",
            (record["fingerprint"],),
        ).fetchone()
        if existing:
            self.connection.execute(
                """
                UPDATE incidents
                SET occurrence_count = COALESCE(occurrence_count, 1) + 1,
                    last_seen = ?
                WHERE id = ?
                """,
                (record["last_seen"], existing["id"]),
            )
            self.connection.commit()
            return
        self.connection.execute(
            """
            INSERT OR REPLACE INTO incidents
            (id, room_id, world_id, type, severity, detected_at, trigger, evidence,
             summary, possible_causes, suggestions, status, fingerprint,
             occurrence_count, last_seen)
            VALUES (:id, :room_id, :world_id, :type, :severity, :detected_at, :trigger,
                    :evidence, :summary, :possible_causes, :suggestions, :status,
                    :fingerprint, :occurrence_count, :last_seen)
            """,
            record,
        )
        self.connection.commit()

    def save_diagnosis_incident(self, context: Any, report: Any) -> str:
        event_type = str(context.event_type)
        fault_type = str(report.fault_type)
        severity = str(report.severity)
        summary = str(report.summary)
        probable_cause = json.dumps(report.probable_cause, ensure_ascii=False)
        evidence = json.dumps(report.evidence, ensure_ascii=False)
        recommendations = json.dumps(report.recommendations, ensure_ascii=False)
        detected_at = str(context.collected_at)
        room_id = str(context.room_id) if context.room_id is not None else None
        world_id = str(context.world_id) if context.world_id is not None else None
        fingerprint = _diagnosis_fingerprint(room_id, world_id, fault_type, report.evidence)
        existing = self.connection.execute(
            "SELECT id FROM incidents WHERE fingerprint = ? AND status = 'open'",
            (fingerprint,),
        ).fetchone()
        if existing:
            self.connection.execute(
                """
                UPDATE incidents
                SET occurrence_count = COALESCE(occurrence_count, 1) + 1,
                    last_seen = ?
                WHERE id = ?
                """,
                (detected_at, existing["id"]),
            )
            self.connection.commit()
            return str(existing["id"])
        incident_id = f"INC-{uuid.uuid4().hex[:12].upper()}"
        record = {
            "id": incident_id,
            "room_id": room_id,
            "world_id": world_id,
            "event_type": event_type,
            "fault_type": fault_type,
            "severity": severity,
            "summary": summary,
            "probable_cause": probable_cause,
            "evidence": evidence,
            "impact": str(report.impact),
            "recommendations": recommendations,
            "detected_at": detected_at,
            "status": "open",
            "type": fault_type,
            "trigger": event_type,
            "possible_causes": probable_cause,
            "suggestions": recommendations,
            "fingerprint": fingerprint,
            "occurrence_count": 1,
            "last_seen": detected_at,
        }
        self.connection.execute(
            """
            INSERT INTO incidents
            (id, room_id, world_id, type, severity, detected_at, trigger, evidence,
             summary, possible_causes, suggestions, status, event_type, fault_type,
             probable_cause, impact, recommendations, fingerprint,
             occurrence_count, last_seen)
            VALUES
            (:id, :room_id, :world_id, :type, :severity, :detected_at, :trigger, :evidence,
             :summary, :possible_causes, :suggestions, :status, :event_type, :fault_type,
             :probable_cause, :impact, :recommendations, :fingerprint,
             :occurrence_count, :last_seen)
            """,
            record,
        )
        self.connection.commit()
        return incident_id

    def save_webhook_event(self, event: Any) -> None:
        record = {
            "id": event.id,
            "source": event.source,
            "event_type": event.event_type,
            "room_id": str(event.room_id) if event.room_id is not None else None,
            "room_name": event.room_name,
            "timestamp": event.timestamp,
            "severity": event.severity,
            "summary": event.summary,
            "raw_payload": json.dumps(event.raw_payload, ensure_ascii=False),
            "created_at": event.created_at,
        }
        self.connection.execute(
            """
            INSERT OR REPLACE INTO webhook_events
            (id, source, event_type, room_id, room_name, timestamp, severity, summary,
             raw_payload, created_at)
            VALUES (:id, :source, :event_type, :room_id, :room_name, :timestamp, :severity,
                    :summary, :raw_payload, :created_at)
            """,
            record,
        )
        self.connection.commit()

    def list_incidents(
        self,
        limit: int = 20,
        status: str | None = None,
        severity: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        parameters: list[Any] = []
        if status:
            clauses.append("status = ?")
            parameters.append(status)
        if severity:
            clauses.append("severity = ?")
            parameters.append(severity)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        parameters.append(max(1, min(limit, 500)))
        rows = self.connection.execute(
            f"SELECT * FROM incidents{where} ORDER BY detected_at DESC LIMIT ?", parameters
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            for key in (
                "evidence",
                "possible_causes",
                "suggestions",
                "probable_cause",
                "recommendations",
            ):
                if key in item and item[key] is not None:
                    try:
                        item[key] = json.loads(item[key])
                    except (TypeError, json.JSONDecodeError):
                        pass
            result.append(item)
        return result

    def get_incident(self, incident_id: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT * FROM incidents WHERE id = ?", (incident_id,)
        ).fetchone()
        if row is None:
            return None
        item = dict(row)
        for key in ("evidence", "possible_causes", "suggestions", "probable_cause", "recommendations"):
            if key in item and item[key] is not None:
                try:
                    item[key] = json.loads(item[key])
                except (TypeError, json.JSONDecodeError):
                    pass
        return item

    def incident_summary(self) -> dict[str, int]:
        row = self.connection.execute(
            """
            SELECT COUNT(*) AS incident_count,
                   COALESCE(SUM(CASE WHEN UPPER(severity) IN ('HIGH', 'CRITICAL')
                                     THEN 1 ELSE 0 END), 0) AS high_risk_count
            FROM incidents
            """
        ).fetchone()
        return {
            "incident_count": int(row["incident_count"]),
            "high_risk_count": int(row["high_risk_count"]),
        }

    def incident_trend(self, days: int = 7) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """
            SELECT substr(detected_at, 1, 10) AS day, COUNT(*) AS count
            FROM incidents
            GROUP BY day
            ORDER BY day DESC
            LIMIT ?
            """,
            (max(1, min(days, 30)),),
        ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def close(self) -> None:
        connection = getattr(self._local, "connection", None)
        if connection is not None:
            connection.close()
            self._local.connection = None
        if self._memory_anchor is not None:
            self._memory_anchor.close()
            self._memory_anchor = None


def _normalize_evidence(value: Any) -> list[str]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            value = [value]
    if not isinstance(value, list):
        value = [value]
    return sorted(
        {
            re.sub(r"^\s*\[[^\]]+\]\s*:\s*", "", str(item)).strip().lower()
            for item in value
        }
    )


def _incident_fingerprint(record: dict[str, Any]) -> str:
    evidence = _normalize_evidence(record.get("evidence", []))
    value = "|".join(
        (str(record.get("room_id", "")), str(record.get("world_id", "")),
         str(record.get("fault_type") or record.get("type", "")), *evidence)
    )
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _diagnosis_fingerprint(
    room_id: Any, world_id: Any, fault_type: Any, evidence: Any
) -> str:
    return _incident_fingerprint(
        {
            "room_id": room_id,
            "world_id": world_id,
            "fault_type": fault_type,
            "evidence": evidence,
        }
    )
