"""FastAPI receiver for DMP webhooks."""

from __future__ import annotations

import json
import logging
import threading
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from storage.database import IncidentDatabase
from app.dmp.client import DMPClient
from app.diagnosis.context import DiagnosisContext, collect_diagnosis_context
from app.dashboard import register_dashboard
from detector.rules import DiagnosisResult, detect_context
from llm.diagnosis import (
    DiagnosisPromptBuilder,
    StructuredLLMProvider,
    parse_diagnosis_response,
)

from .handler import handle_event
from .models import DMPWebhookEvent
from .verifier import verify_signature

LOGGER = logging.getLogger(__name__)


def create_app(
    database: IncidentDatabase,
    secret: str,
    verification_enabled: bool = True,
    dmp_client: DMPClient | None = None,
    log_lines: int = 200,
    diagnosis_provider: StructuredLLMProvider | None = None,
) -> FastAPI:
    app = FastAPI(title="ServerOps AI Webhook")
    register_dashboard(app, database)

    @app.post("/webhook/dmp")
    async def receive_dmp_webhook(request: Request) -> JSONResponse:
        body = await request.body()
        signature = request.headers.get("X-DMP-Signature", "")
        if not verify_signature(body, signature, secret, verification_enabled):
            LOGGER.warning("webhook signature verification failed")
            return JSONResponse({"detail": "invalid signature"}, status_code=401)
        LOGGER.info("webhook signature verified")
        try:
            payload: Any = json.loads(body)
            if not isinstance(payload, dict):
                raise ValueError("webhook payload must be a JSON object")
            event = DMPWebhookEvent.from_payload(payload)
            record = handle_event(event, database)
            if (
                event.event_type == "keepalive_triggered"
                and dmp_client is not None
                and diagnosis_provider is not None
            ):
                threading.Thread(
                    target=_collect_context,
                    args=(dmp_client, event, log_lines, diagnosis_provider, database),
                    name="serverops-diagnosis",
                    daemon=True,
                ).start()
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            LOGGER.warning("webhook handler failed: %s", exc)
            return JSONResponse({"detail": "invalid webhook payload"}, status_code=400)
        return JSONResponse({"ok": True, "event_id": record.id})

    return app


def _collect_context(
    client: DMPClient,
    event: DMPWebhookEvent,
    log_lines: int,
    diagnosis_provider: StructuredLLMProvider,
    database: IncidentDatabase,
) -> None:
    try:
        context: DiagnosisContext = collect_diagnosis_context(client, event, log_lines)
        result: DiagnosisResult = detect_context(context)
        prompt = DiagnosisPromptBuilder().build(context, result)
        report = parse_diagnosis_response(diagnosis_provider.diagnose(prompt))
        if report.diagnosis_error:
            LOGGER.error("diagnosis report invalid: %s", report.diagnosis_error)
            return
        try:
            incident_id = database.save_diagnosis_incident(context, report)
            LOGGER.info(
                "incident saved: id=%s fault_type=%s severity=%s status=open",
                incident_id,
                report.fault_type,
                report.severity,
            )
        except Exception as exc:
            LOGGER.error("incident save failed: %s", exc)
            return
        LOGGER.info(
            "DiagnosisContext: event=%s room_id=%s fault=%s severity=%s errors=%d",
            context.event_type,
            context.room_id,
            result.fault_type,
            result.severity,
            len(context.collection_errors),
        )
        print(
            json.dumps(
                {
                    "DiagnosisContext": context.as_dict(),
                    "DiagnosisResult": result.__dict__,
                    "DiagnosisReport": report.__dict__,
                    "Incident": {"id": incident_id, "status": "open"},
                },
                ensure_ascii=False,
            )
        )
    except Exception as exc:
        LOGGER.error("diagnosis context collection failed: %s", exc)
