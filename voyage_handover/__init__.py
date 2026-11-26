"""Auditable multilingual NLP for fictional vessel hand-over records."""

from .briefing import build_briefing, render_markdown
from .entities import VesselRegistry
from .pipeline import NlpAnalyzer, analyze_case, analyze_record
from .store import (
    DEFAULT_POLICY,
    HandoverStore,
    ImmutableRecordError,
    ImmutableTrackError,
)

__version__ = "0.2.0"

__all__ = [
    "DEFAULT_POLICY",
    "HandoverStore",
    "ImmutableRecordError",
    "ImmutableTrackError",
    "NlpAnalyzer",
    "VesselRegistry",
    "analyze_case",
    "analyze_record",
    "build_briefing",
    "render_markdown",
]
