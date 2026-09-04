"""Rule-based incident detection."""

from .incident import IncidentDraft, build_incident
from .rules import DiagnosisResult, RuleMatch, detect_context, detect_lines

__all__ = [
    "DiagnosisResult",
    "IncidentDraft",
    "RuleMatch",
    "build_incident",
    "detect_context",
    "detect_lines",
]
