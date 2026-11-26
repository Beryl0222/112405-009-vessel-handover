"""Core data structures for auditable voyage hand-over analysis.

The structures are deliberately JSON-serializable.  Every judgement contains
one or more :class:`Evidence` objects so that a watch officer can navigate from
a generated card back to the exact source record and sentence.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

SCHEMA_VERSION = "voyage-handover/1.0"

ActionStatus = Literal["blocked", "ready", "completed", "ambiguous", "cancelled", "in_force"]
ConditionState = Literal["required", "met", "absent", "unknown", "conflicting", "not_applicable"]


@dataclass(frozen=True)
class Evidence:
    """A pointer to text that supports a judgement."""

    record_id: str
    quote: str
    sentence_id: str | None = None
    start: int | None = None
    end: int | None = None
    lang: str | None = None
    source_kind: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class VesselRef:
    vessel_id: str | None = None
    resolution: str = "unresolved"
    mention: str | None = None
    candidates: list[str] = field(default_factory=list)
    evidence: Evidence | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if self.evidence is not None:
            data["evidence"] = self.evidence.to_dict()
        return data


@dataclass
class Condition:
    """An action condition and its current evidence-based state."""

    key: str
    label: str
    category: str
    state: ConditionState = "required"
    blocking: bool = True
    source: str = "captain_order"
    requirement_evidence: list[Evidence] = field(default_factory=list)
    state_evidence: list[Evidence] = field(default_factory=list)
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "category": self.category,
            "state": self.state,
            "blocking": self.blocking,
            "source": self.source,
            "requirement_evidence": [e.to_dict() for e in self.requirement_evidence],
            "state_evidence": [e.to_dict() for e in self.state_evidence],
            "detail": self.detail,
        }


@dataclass
class Claim:
    """A reported speech act or assertion extracted from one sentence."""

    id: str
    record_id: str
    sentence_id: str
    kind: str
    summary: str
    speaker_role: str = "unknown"
    speaker_label: str | None = None
    reporter_role: str = "unknown"
    action_key: str | None = None
    action_label: str | None = None
    speech_act: str = "statement"
    modality: str = "unknown"
    polarity: str = "neutral"
    confidence: str = "high"
    vessel: VesselRef | None = None
    evidence: list[Evidence] = field(default_factory=list)
    condition_keys: list[str] = field(default_factory=list)
    attributes: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "record_id": self.record_id,
            "sentence_id": self.sentence_id,
            "kind": self.kind,
            "summary": self.summary,
            "speaker_role": self.speaker_role,
            "speaker_label": self.speaker_label,
            "reporter_role": self.reporter_role,
            "action_key": self.action_key,
            "action_label": self.action_label,
            "speech_act": self.speech_act,
            "modality": self.modality,
            "polarity": self.polarity,
            "confidence": self.confidence,
            "vessel": self.vessel.to_dict() if self.vessel else None,
            "evidence": [e.to_dict() for e in self.evidence],
            "condition_keys": list(self.condition_keys),
            "attributes": dict(self.attributes),
        }


@dataclass
class Observation:
    """An equipment, weather, sea-state, or temporal observation."""

    id: str
    record_id: str
    sentence_id: str
    category: str
    subject: str
    key: str
    label: str
    state: str
    value: str | None = None
    time_ref: str | None = None
    timestamp: str | None = None
    temporal_relation: str | None = None
    reference_event: str | None = None
    clarification: bool = False
    vessel: VesselRef | None = None
    evidence: list[Evidence] = field(default_factory=list)
    attributes: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "record_id": self.record_id,
            "sentence_id": self.sentence_id,
            "category": self.category,
            "subject": self.subject,
            "key": self.key,
            "label": self.label,
            "state": self.state,
            "value": self.value,
            "time_ref": self.time_ref,
            "timestamp": self.timestamp,
            "temporal_relation": self.temporal_relation,
            "reference_event": self.reference_event,
            "clarification": self.clarification,
            "vessel": self.vessel.to_dict() if self.vessel else None,
            "evidence": [e.to_dict() for e in self.evidence],
            "attributes": dict(self.attributes),
        }


@dataclass
class Issue:
    code: str
    severity: str
    message: str
    evidence: list[Evidence] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "evidence": [e.to_dict() for e in self.evidence],
            "details": dict(self.details),
        }


@dataclass
class TimelineEvent:
    key: str
    label: str
    relation: str | None = None
    timestamp: str | None = None
    evidence: list[Evidence] = field(default_factory=list)
    source_observation_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "relation": self.relation,
            "timestamp": self.timestamp,
            "evidence": [e.to_dict() for e in self.evidence],
            "source_observation_id": self.source_observation_id,
        }


@dataclass
class ActionCard:
    id: str
    action_key: str
    action_label: str
    vessel_id: str | None = None
    vessel_candidates: list[str] = field(default_factory=list)
    status: ActionStatus = "blocked"
    title: str = ""
    order_claim_ids: list[str] = field(default_factory=list)
    suggestion_claim_ids: list[str] = field(default_factory=list)
    clearance_claim_ids: list[str] = field(default_factory=list)
    report_claim_ids: list[str] = field(default_factory=list)
    condition_keys: list[str] = field(default_factory=list)
    conditions: dict[str, Condition] = field(default_factory=dict)
    blocker_keys: list[str] = field(default_factory=list)
    advisory_keys: list[str] = field(default_factory=list)
    timeline: list[TimelineEvent] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    revision: int = 1
    source_record_ids: list[str] = field(default_factory=list)
    completed: bool = False
    completion: dict[str, Any] | None = None
    immutable: bool = False
    revision_history: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "action_key": self.action_key,
            "action_label": self.action_label,
            "vessel_id": self.vessel_id,
            "vessel_candidates": list(self.vessel_candidates),
            "status": self.status,
            "title": self.title or self.action_label,
            "order_claim_ids": list(self.order_claim_ids),
            "suggestion_claim_ids": list(self.suggestion_claim_ids),
            "clearance_claim_ids": list(self.clearance_claim_ids),
            "report_claim_ids": list(self.report_claim_ids),
            "condition_keys": list(self.condition_keys),
            "conditions": {k: v.to_dict() for k, v in self.conditions.items()},
            "blocker_keys": list(self.blocker_keys),
            "advisory_keys": list(self.advisory_keys),
            "timeline": [t.to_dict() for t in self.timeline],
            "evidence": [e.to_dict() for e in self.evidence],
            "revision": self.revision,
            "source_record_ids": list(self.source_record_ids),
            "completed": self.completed,
            "completion": self.completion,
            "immutable": self.immutable,
            "revision_history": list(self.revision_history),
            "notes": list(self.notes),
        }
