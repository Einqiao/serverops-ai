"""Conservative, explainable rules for common DST operational failures."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Any


@dataclass(frozen=True)
class Rule:
    type: str
    severity: str
    patterns: tuple[str, ...]


@dataclass(frozen=True)
class RuleMatch:
    type: str
    severity: str
    trigger: str
    evidence: list[str]


@dataclass(frozen=True)
class DiagnosisResult:
    fault_type: str
    severity: str
    confidence: float
    evidence: list[str]
    matched_logs: list[str]


RULES = (
    Rule("CRASH", "critical", (r"\bcrash(?:ed|ing)?\b", r"segmentation fault", r"\bfatal\b", r"\bkilled\b")),
    Rule("LUA_ERROR", "high", (r"stack traceback", r"\blua(?: error|:)\b", r"attempt to .+ nil")),
    Rule("RESOURCE", "high", (r"out of memory", r"no space left", r"disk full", r"memory usage")),
    Rule("ERROR", "medium", (r"\berror\b", r"\bexception\b", r"\bfailed\b")),
    Rule("WARNING", "low", (r"\bwarn(?:ing)?\b", r"\bdeprecated\b")),
)

DIAGNOSIS_RULES = (
    ("CRASH", "CRITICAL", 0.98, ("segmentation fault", "crash", "fatal error")),
    ("LUA_ERROR", "HIGH", 0.92, ("lua error", "stack traceback", "lua_error")),
    ("MOD_ERROR", "HIGH", 0.90, ("mod error", "modmain.lua", "modworldgenmain.lua", "failed to load mod")),
    ("CONNECTION", "MEDIUM", 0.85, ("connection timeout", "timed out", "connection lost")),
    ("WARNING", "LOW", 0.65, ("warning", "warn")),
)


def detect_lines(lines: Iterable[str]) -> list[RuleMatch]:
    lines = list(lines)
    matches: list[RuleMatch] = []
    for rule in RULES:
        evidence = [
            line for line in lines if any(re.search(pattern, line, re.IGNORECASE) for pattern in rule.patterns)
        ]
        if evidence:
            matches.append(
                RuleMatch(
                    type=rule.type,
                    severity=rule.severity,
                    trigger=f"{rule.type} rule matched {len(evidence)} line(s)",
                    evidence=evidence[-20:],
                )
            )
    return matches


def detect_context(context: Any, max_matched_logs: int = 10) -> DiagnosisResult:
    """Analyze a DiagnosisContext without mutating it."""
    lines = [str(line) for line in getattr(context, "recent_logs", [])]
    matches: dict[str, tuple[str, float, list[str], list[str]]] = {}
    for fault_type, severity, confidence, patterns in DIAGNOSIS_RULES:
        evidence: list[str] = []
        matched_logs: list[str] = []
        for line in lines:
            lowered = line.lower()
            matched = [pattern for pattern in patterns if pattern in lowered]
            if matched:
                evidence.extend(matched)
                matched_logs.append(line)
        if evidence:
            matches[fault_type] = (
                severity,
                confidence,
                list(dict.fromkeys(evidence)),
                list(dict.fromkeys(matched_logs)),
            )

    if not matches:
        return DiagnosisResult("UNKNOWN", "INFO", 0.1, [], [])

    if "CRASH" in matches:
        selected = "CRASH"
    elif "MOD_ERROR" in matches and "LUA_ERROR" in matches:
        selected = "MOD_ERROR"
    else:
        selected = next(
            rule[0] for rule in DIAGNOSIS_RULES if rule[0] in matches
        )
    severity, confidence, _, _ = matches[selected]
    evidence: list[str] = []
    for fault_type, _, _, _ in DIAGNOSIS_RULES:
        if fault_type in matches:
            evidence.extend(f"{fault_type}: {item}" for item in matches[fault_type][2])
    matched_logs = list(dict.fromkeys(line for item in matches.values() for line in item[3]))
    return DiagnosisResult(
        fault_type=selected,
        severity=severity,
        confidence=confidence,
        evidence=list(dict.fromkeys(evidence)),
        matched_logs=matched_logs[:max(1, max_matched_logs)],
    )


def detect_resources(status: object, thresholds: object) -> list[RuleMatch]:
    values = _numbers(status)
    limits = {
        "cpu": float(getattr(thresholds, "cpu", 90.0)),
        "memory": float(getattr(thresholds, "memory", 90.0)),
        "disk": float(getattr(thresholds, "disk", 90.0)),
    }
    matches: list[RuleMatch] = []
    for name, limit in limits.items():
        value = values.get(name)
        if value is not None and value >= limit:
            matches.append(
                RuleMatch(
                    type="RESOURCE",
                    severity="high",
                    trigger=f"{name}={value:.1f}% >= {limit:.1f}%",
                    evidence=[f"{name}: {value:.1f}%"],
                )
            )
    return matches


def _numbers(value: object) -> dict[str, float]:
    result: dict[str, float] = {}
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).lower().replace("_", "")
            if normalized in {"cpu", "memory", "mem", "disk"} and isinstance(item, (int, float)):
                result["memory" if normalized == "mem" else normalized] = float(item)
            result.update(_numbers(item))
    elif isinstance(value, list):
        for item in value:
            result.update(_numbers(item))
    return result
