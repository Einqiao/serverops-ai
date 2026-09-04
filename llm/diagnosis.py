"""LLM abstraction with a failure-safe OpenAI-compatible implementation."""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Mapping

import requests


@dataclass
class Diagnosis:
    summary: str
    possible_causes: list[str]
    suggestions: list[str]


@dataclass
class DiagnosisReport:
    fault_type: str
    severity: str
    summary: str
    probable_cause: list[str]
    evidence: list[str]
    impact: str
    recommendations: list[str]
    diagnosis_error: str = ""
    raw_response: str = ""


class DiagnosisPromptBuilder:
    """Build a bounded, sanitized prompt from context and rule output."""

    def build(self, context: Any, result: Any) -> str:
        payload = {
            "event_type": getattr(context, "event_type", ""),
            "event_timestamp": getattr(context, "event_timestamp", ""),
            "room_id": getattr(context, "room_id", None),
            "room_name": getattr(context, "room_name", ""),
            "world_id": getattr(context, "world_id", None),
            "server_status": _sanitize(getattr(context, "server_status", {})),
            "recent_logs": list(getattr(context, "recent_logs", []))[-200:],
            "rule_result": {
                "fault_type": getattr(result, "fault_type", "UNKNOWN"),
                "severity": getattr(result, "severity", "INFO"),
                "confidence": getattr(result, "confidence", 0.0),
                "evidence": list(getattr(result, "evidence", [])),
                "matched_logs": list(getattr(result, "matched_logs", []))[:10],
            },
        }
        return (
            "你是 DST ServerOps 故障诊断助手。请只输出合法 JSON，字段必须为 "
            "fault_type、severity、summary、probable_cause、evidence、impact、"
            "recommendations。规则检测结果是辅助证据，不一定完全正确；请结合日志判断，"
            "不要盲目接受规则分类。不要编造未提供的事实。\n"
            + json.dumps(payload, ensure_ascii=False, default=str)
        )


class StructuredLLMProvider(ABC):
    @abstractmethod
    def diagnose(self, prompt: str) -> str:
        """Return a JSON diagnosis response."""


class MockLLMProvider(StructuredLLMProvider):
    def diagnose(self, prompt: str) -> str:
        try:
            payload = json.loads(prompt.rsplit("\n", 1)[-1])
            rule = payload.get("rule_result", {})
        except (json.JSONDecodeError, AttributeError):
            rule = {}
        return json.dumps(
            {
                "fault_type": rule.get("fault_type", "UNKNOWN"),
                "severity": rule.get("severity", "INFO"),
                "summary": "Mock provider diagnosis",
                "probable_cause": ["需要结合完整日志进一步确认。"],
                "evidence": rule.get("evidence", []),
                "impact": "可能影响服务器稳定性。",
                "recommendations": ["检查异常时间段日志并确认进程状态。"],
            },
            ensure_ascii=False,
        )


class SiliconFlowLLMProvider(StructuredLLMProvider):
    """OpenAI-compatible SiliconFlow provider with explicit failure reporting."""

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key_env: str = "SILICONFLOW_API_KEY",
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key_env = api_key_env
        self.timeout = timeout

    def diagnose(self, prompt: str) -> str:
        api_key = os.getenv(self.api_key_env, "")
        if not api_key:
            raise RuntimeError(
                f"SiliconFlow API key is missing from environment variable {self.api_key_env}"
            )
        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Authorization": "Bearer " + api_key,
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "temperature": 0.1,
                    "messages": [{"role": "user", "content": prompt}],
                    "response_format": {"type": "json_object"},
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
            content = payload["choices"][0]["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise RuntimeError("SiliconFlow returned an empty diagnosis response")
            return content
        except requests.RequestException as exc:
            raise RuntimeError(f"SiliconFlow request failed: {exc}") from exc
        except (ValueError, KeyError, TypeError, IndexError) as exc:
            raise RuntimeError(f"Invalid SiliconFlow response: {exc}") from exc


def parse_diagnosis_response(response: str) -> DiagnosisReport:
    raw = response
    if "```" in response:
        response = response.strip()
        if response.startswith("```json"):
            response = response[7:]
        elif response.startswith("```"):
            response = response[3:]
        if response.endswith("```"):
            response = response[:-3]
        response = response.strip()
    try:
        payload = json.loads(response)
    except (json.JSONDecodeError, TypeError) as exc:
        return DiagnosisReport(
            fault_type="UNKNOWN",
            severity="INFO",
            summary="",
            probable_cause=[],
            evidence=[],
            impact="",
            recommendations=[],
            diagnosis_error=f"invalid diagnosis JSON: {exc}",
            raw_response=raw,
        )
    if not isinstance(payload, dict):
        return DiagnosisReport(
            "UNKNOWN", "INFO", "", [], [], "", [],
            diagnosis_error="diagnosis JSON must be an object",
            raw_response=raw,
        )
    return DiagnosisReport(
        fault_type=str(payload.get("fault_type", "UNKNOWN")),
        severity=str(payload.get("severity", "INFO")),
        summary=str(payload.get("summary", "")),
        probable_cause=_string_list(payload.get("probable_cause", [])),
        evidence=_string_list(payload.get("evidence", [])),
        impact=str(payload.get("impact", "")),
        recommendations=_string_list(payload.get("recommendations", [])),
        raw_response=raw,
    )


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if value in (None, ""):
        return []
    return [str(value)]


def _sanitize(value: Any) -> Any:
    if isinstance(value, Mapping):
        blocked = {"password", "token", "secret", "api_key", "authorization"}
        return {
            str(key): _sanitize(item)
            for key, item in value.items()
            if str(key).lower() not in blocked
        }
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    return value


class LLMProvider(ABC):
    @abstractmethod
    def diagnose(self, context: Mapping[str, Any]) -> Diagnosis:
        """Return a diagnosis for an incident context."""


class OpenAICompatibleProvider(LLMProvider):
    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def diagnose(self, context: Mapping[str, Any]) -> Diagnosis:
        fallback = _fallback_diagnosis(context)
        if not self.api_key:
            return fallback
        prompt = (
            "你是 DST ServerOps 运维助手。仅基于给定 JSON 输出 JSON，字段必须为 "
            "summary、severity、possible_causes、suggestions。不要编造事实。\n"
            + json.dumps(context, ensure_ascii=False, default=str)
        )
        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "temperature": 0.1,
                    "messages": [{"role": "user", "content": prompt}],
                    "response_format": {"type": "json_object"},
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            return Diagnosis(
                summary=str(parsed.get("summary", fallback.summary)),
                possible_causes=[str(item) for item in parsed.get("possible_causes", [])],
                suggestions=[str(item) for item in parsed.get("suggestions", [])],
            )
        except (requests.RequestException, ValueError, KeyError, TypeError, IndexError):
            return fallback


def _fallback_diagnosis(context: Mapping[str, Any]) -> Diagnosis:
    incident_type = str(context.get("type", "incident"))
    severity = str(context.get("severity", "unknown"))
    return Diagnosis(
        summary=f"检测到 {incident_type}（{severity}），LLM 诊断不可用，保留规则结果。",
        possible_causes=["需要结合完整日志、房间状态和最近变更进一步确认。"],
        suggestions=["检查异常日志", "确认资源和进程状态", "必要时保留现场后再重启"],
    )
