"""Append-only hand-over store and action-card reconciliation."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import replace
from pathlib import Path
from typing import Any

from .lexicon import TRACK_KIND
from .models import ActionCard, Condition, Evidence, Issue
from .pipeline import NlpAnalyzer, RecordAnalysis, record_timestamp

SCHEMA_VERSION = "voyage-handover/1.0"


class HandoverError(ValueError):
    """Base class for store errors."""


class ImmutableRecordError(HandoverError):
    """Raised when an existing source/track record is changed."""


class ImmutableTrackError(ImmutableRecordError):
    """Raised when code attempts to rewrite a completed track record."""


DEFAULT_POLICY: dict[str, Any] = {
    "captain_order_actions": ["shift_anchor", "start_operations"],
    "clearance_actions": ["shift_anchor", "start_operations"],
    "positioning_hard_block_states": {
        # Intermittent positioning is treated as a hard block for survey
        # operations, while for an anchor shift only a total loss blocks.
        "shift_anchor": ["lost"],
        "start_operations": ["intermittent", "lost"],
    },
    "positioning_advisory_states": ["intermittent", "fault", "mentioned"],
    "block_on_untimed_abnormal_positioning": False,
}

ACTION_LABELS = {
    "shift_anchor": "移锚",
    "maintain_position": "维持现位",
    "start_operations": "开始作业",
    "move_vessel": "移船/移动",
}


def canonical_hash(record: dict[str, Any]) -> str:
    payload = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _evidence_key(evidence: Evidence) -> tuple[Any, ...]:
    return (
        evidence.record_id,
        evidence.sentence_id,
        evidence.quote,
        evidence.start,
        evidence.end,
    )


class HandoverStore:
    """Continuously ingest records and recompute open action cards.

    Source records are append-only.  Track records are additionally hash
    chained and cannot be replaced.  Action cards are projections and are
    rebuilt as new logs arrive; completed cards remain completed.
    """

    def __init__(
        self,
        case_id: str | None = None,
        vessels: list[dict[str, Any]] | None = None,
        policy: dict[str, Any] | None = None,
    ) -> None:
        self.case_id = case_id
        self.vessels = vessels or []
        self.policy = json.loads(json.dumps(DEFAULT_POLICY, ensure_ascii=False))
        if policy:
            self._deep_update(self.policy, policy)
        self.analyzer = NlpAnalyzer(self.vessels)

        self.records: dict[str, dict[str, Any]] = {}
        self.record_hashes: dict[str, str] = {}
        self.sentences: dict[str, dict[str, Any]] = {}
        self.analyses: dict[str, RecordAnalysis] = {}
        self.claims: dict[str, Any] = {}
        self.observations: dict[str, Any] = {}
        self.conditions: dict[str, Condition] = {}
        self.issues: list[Issue] = []
        self.derived_issues: list[Issue] = []
        self.action_cards: dict[str, ActionCard] = {}
        self.track_records: dict[str, dict[str, Any]] = {}
        self.track_chain: list[dict[str, str]] = []
        self.completion_events: dict[str, dict[str, Any]] = {}
        self.ingest_count = 0

    @staticmethod
    def _deep_update(base: dict[str, Any], override: dict[str, Any]) -> None:
        for key, value in override.items():
            if isinstance(value, dict) and isinstance(base.get(key), dict):
                HandoverStore._deep_update(base[key], value)
            else:
                base[key] = value

    # ------------------------------------------------------------------
    # Construction and persistence
    # ------------------------------------------------------------------
    @classmethod
    def from_case(cls, case: dict[str, Any], policy: dict[str, Any] | None = None) -> "HandoverStore":
        store = cls(case_id=case.get("case_id"), vessels=case.get("vessels", []), policy=policy)
        for record in case.get("records", []):
            store.ingest_record(record)
        for track in case.get("track", []):
            store.ingest_track_record(track)
        return store

    @classmethod
    def from_case_file(cls, path: str | Path, policy: dict[str, Any] | None = None) -> "HandoverStore":
        case = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls.from_case(case, policy=policy)

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
        return path

    @classmethod
    def load(cls, path: str | Path) -> "HandoverStore":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        store = cls(
            case_id=data.get("case_id"),
            vessels=data.get("vessels", []),
            policy=data.get("policy"),
        )
        for record in data.get("source_records", []):
            store.ingest_record(record)
        for track in (data.get("track_records") or {}).values():
            store.ingest_track_record(track)
        return store

    # ------------------------------------------------------------------
    # Append-only ingestion
    # ------------------------------------------------------------------
    def ingest_record(self, record: dict[str, Any]) -> RecordAnalysis:
        if not isinstance(record, dict):
            raise HandoverError("record must be a JSON object")
        rid = str(record.get("id") or "").strip()
        if not rid:
            raise HandoverError("record.id is required")
        digest = canonical_hash(record)

        if rid in self.track_records and canonical_hash(self.track_records[rid]) != digest:
            raise ImmutableTrackError(
                f"completed track record {rid} is immutable and cannot be rewritten"
            )

        if rid in self.records:
            if self.record_hashes[rid] != digest:
                raise ImmutableRecordError(
                    f"source record {rid} already exists with different content; "
                    "add a new clarification record instead of rewriting it"
                )
            return self.analyses[rid]

        self.ingest_count += 1
        order = self.ingest_count
        kind = str(record.get("kind") or record.get("type") or "").lower()
        looks_like_track = kind in TRACK_KIND or any(
            key in record for key in ("lat", "lon", "latitude", "longitude", "position_wgs84")
        )
        if not str(record.get("text") or "").strip() and looks_like_track:
            vessel = self.analyzer.registry.resolve(
                json.dumps(record, ensure_ascii=False),
                record_vessel_id=record.get("vessel_id"),
                timestamp=record_timestamp(record),
            )
            analysis = RecordAnalysis(
                record_id=rid,
                kind=kind or "track-point",
                lang=str(record.get("lang") or "unknown"),
                timestamp=record_timestamp(record),
                vessel=vessel,
            )
            self.records[rid] = record
            self.record_hashes[rid] = digest
            self.analyses[rid] = analysis
            self.ingest_track_record(record)
            return analysis

        analysis = self.analyzer.analyze_record(record)
        for claim in analysis.claims:
            claim.attributes["ingest_order"] = order
        for observation in analysis.observations:
            observation.attributes["ingest_order"] = order

        self.records[rid] = record
        self.record_hashes[rid] = digest
        self.analyses[rid] = analysis
        for sentence in analysis.sentences:
            self.sentences[sentence.id] = {
                "sentence_id": sentence.id,
                "record_id": rid,
                "text": sentence.text,
                "start": sentence.start,
                "end": sentence.end,
                "lang": sentence.lang,
            }
        for claim in analysis.claims:
            self.claims[claim.id] = claim
        for observation in analysis.observations:
            self.observations[observation.id] = observation
        self.issues.extend(analysis.issues)
        for condition in analysis.conditions:
            self._merge_condition(condition, rid, analysis.timestamp, order)

        if looks_like_track:
            self.ingest_track_record(record)

        if analysis.completion:
            completion = dict(analysis.completion)
            completion["ingest_order"] = order
            vessel_id = analysis.vessel.vessel_id or "UNRESOLVED"
            key = f"{vessel_id}:{completion['action_key']}"
            existing = self.completion_events.get(key)
            if existing is None or order >= int(existing.get("ingest_order", 0)):
                self.completion_events[key] = completion

        self._reconcile()
        return analysis

    def ingest_track_record(self, track: dict[str, Any]) -> dict[str, str]:
        if not isinstance(track, dict):
            raise HandoverError("track record must be an object")
        tid = str(track.get("id") or track.get("record_id") or "").strip()
        if not tid:
            raise HandoverError("track record id is required")
        digest = canonical_hash(track)
        if tid in self.track_records:
            if canonical_hash(self.track_records[tid]) != digest:
                raise ImmutableTrackError(
                    f"completed track record {tid} is immutable and cannot be rewritten"
                )
            return next(item for item in self.track_chain if item["record_id"] == tid)

        previous_hash = self.track_chain[-1]["chain_hash"] if self.track_chain else "0" * 64
        chain_hash = hashlib.sha256((previous_hash + digest).encode("utf-8")).hexdigest()
        entry = {"record_id": tid, "content_hash": digest, "chain_hash": chain_hash}
        self.track_records[tid] = track
        self.track_chain.append(entry)

        action_key = track.get("action_key") or track.get("event")
        if action_key in ACTION_LABELS or track.get("completed") is True or track.get("status") == "completed":
            if action_key and action_key not in ACTION_LABELS:
                # Track events such as "anchor_move" use the card action key.
                if "anchor" in str(action_key):
                    action_key = "shift_anchor"
            vessel_id = str(track.get("vessel_id") or self.analyzer.registry.default_vessel_id or "UNRESOLVED")
            normalized_action = action_key if action_key in ACTION_LABELS else "shift_anchor"
            key = f"{vessel_id}:{normalized_action}"
            self.completion_events[key] = {
                "action_key": normalized_action,
                "completed_at": track.get("timestamp") or track.get("time"),
                "record_id": tid,
                "evidence": {
                    "record_id": tid,
                    "quote": track.get("text") or json.dumps(track, ensure_ascii=False),
                },
                "explicit_track_record": True,
            }
            self._reconcile()
        return entry

    def amend_track_record(self, *_args: Any, **_kwargs: Any) -> None:
        raise ImmutableTrackError("track records are append-only; add a correction/clarification record instead")

    def verify_track_chain(self) -> bool:
        previous = "0" * 64
        for entry in self.track_chain:
            record = self.track_records[entry["record_id"]]
            content_hash = canonical_hash(record)
            if content_hash != entry["content_hash"]:
                return False
            expected = hashlib.sha256((previous + content_hash).encode("utf-8")).hexdigest()
            if expected != entry["chain_hash"]:
                return False
            previous = entry["chain_hash"]
        return True

    # ------------------------------------------------------------------
    # Condition merging
    # ------------------------------------------------------------------
    def _merge_condition(self, incoming: Condition, record_id: str, timestamp: str | None, order: int) -> None:
        existing = self.conditions.get(incoming.key)
        if existing is None:
            existing = Condition(
                key=incoming.key,
                label=incoming.label,
                category=incoming.category,
                state=incoming.state,
                blocking=incoming.blocking,
                source=incoming.source,
            )
            self.conditions[incoming.key] = existing

        existing.label = incoming.label or existing.label
        existing.category = incoming.category or existing.category
        existing.blocking = existing.blocking or incoming.blocking
        for ev in incoming.requirement_evidence:
            if not any(_evidence_key(e) == _evidence_key(ev) for e in existing.requirement_evidence):
                existing.requirement_evidence.append(ev)
        for ev in incoming.state_evidence:
            if not any(_evidence_key(e) == _evidence_key(ev) for e in existing.state_evidence):
                existing.state_evidence.append(ev)

        history = existing.detail.setdefault("state_history", [])
        translated = bool(incoming.detail.get("translated_claim_not_authoritative"))
        if translated:
            history.append(
                {
                    "state": "unverified_claim",
                    "record_id": record_id,
                    "timestamp": timestamp,
                    "order": order,
                    "authoritative": False,
                }
            )
        elif incoming.state in {"met", "absent", "conflicting"} and incoming.state_evidence:
            history.append(
                {
                    "state": incoming.state,
                    "record_id": record_id,
                    "timestamp": timestamp,
                    "order": order,
                    "authoritative": True,
                }
            )

        authoritative = [item for item in history if item.get("authoritative")]
        if authoritative:
            latest = max(authoritative, key=lambda item: int(item.get("order", 0)))
            later_conflicts = [
                item
                for item in authoritative
                if int(item.get("order", 0)) == int(latest.get("order", 0))
                and item.get("state") != latest.get("state")
            ]
            existing.state = "conflicting" if later_conflicts else latest["state"]
            existing.detail["latest_state_record"] = latest.get("record_id")
            existing.detail["latest_state_order"] = latest.get("order")
        elif existing.requirement_evidence:
            existing.state = "required"
        else:
            existing.state = incoming.state

    def _copy_condition(self, key: str, *, blocking: bool | None = None) -> Condition:
        source = self.conditions.get(key)
        if source is None:
            source = Condition(key=key, label=key, category="unknown", state="unknown")
        copied = replace(
            source,
            requirement_evidence=list(source.requirement_evidence),
            state_evidence=list(source.state_evidence),
            detail=json.loads(json.dumps(source.detail, ensure_ascii=False, default=str)),
        )
        if blocking is not None:
            copied.blocking = blocking
        return copied

    # ------------------------------------------------------------------
    # Reconciliation
    # ------------------------------------------------------------------
    @staticmethod
    def _vessel_group(vessel: Any) -> tuple[str, str | None, list[str]]:
        if vessel is not None and vessel.vessel_id:
            return f"V:{vessel.vessel_id}", vessel.vessel_id, []
        candidates = sorted(getattr(vessel, "candidates", []) or [])
        if candidates:
            return "A:" + ",".join(candidates), None, candidates
        return "U", None, []

    @staticmethod
    def _card_id(vessel_id: str | None, candidates: list[str], action_key: str) -> str:
        if vessel_id:
            vessel_part = vessel_id
        elif candidates:
            vessel_part = "AMBIG-" + "-".join(candidates)
        else:
            vessel_part = "UNRESOLVED"
        raw = f"AC-{vessel_part}-{action_key}"
        return "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in raw)

    def _reconcile(self) -> None:
        self.derived_issues = []

        # Resolve generic movement pronouns/ellipsis to a unique known move.
        known_movement: dict[str, set[str]] = defaultdict(set)
        for claim in self.claims.values():
            if claim.action_key in {"shift_anchor", "start_operations"}:
                vessel_key, _, _ = self._vessel_group(claim.vessel)
                known_movement[vessel_key].add(claim.action_key)
        for claim in self.claims.values():
            if claim.action_key != "move_vessel":
                continue
            vessel_key, _, _ = self._vessel_group(claim.vessel)
            known = known_movement.get(vessel_key, set())
            if "shift_anchor" in known and len(known) == 1:
                claim.attributes["coreference_resolution"] = "shift_anchor"
                claim.attributes["coreference_reason"] = "same vessel and unique known movement action"
                if claim.attributes.get("contextual_coreference_candidate"):
                    self.derived_issues.append(
                        Issue(
                            code="contextual_action_coreference",
                            severity="info",
                            message="“moving/移动”按同船唯一已知移锚事项指代到移锚；该关联保留原句证据。",
                            evidence=list(claim.evidence),
                            details={"claim_id": claim.id, "resolved_action_key": "shift_anchor"},
                        )
                    )

        grouped_claims: dict[tuple[str, str], list[Any]] = defaultdict(list)
        for claim in self.claims.values():
            if not claim.action_key:
                continue
            action_key = claim.attributes.get("coreference_resolution") or claim.action_key
            vessel_key, _, _ = self._vessel_group(claim.vessel)
            grouped_claims[(vessel_key, action_key)].append(claim)

        grouped_observations: dict[str, list[Any]] = defaultdict(list)
        for observation in self.observations.values():
            vessel_key, _, _ = self._vessel_group(observation.vessel)
            grouped_observations[vessel_key].append(observation)

        new_cards: dict[str, ActionCard] = {}
        for (vessel_key, action_key), claims in sorted(grouped_claims.items()):
            claims.sort(key=lambda c: int(c.attributes.get("ingest_order", 0)))
            _vk, vessel_id, candidates = self._vessel_group(claims[0].vessel)
            card_id = self._card_id(vessel_id, candidates, action_key)
            old = self.action_cards.get(card_id)
            card = self._build_card(
                card_id=card_id,
                vessel_key=vessel_key,
                vessel_id=vessel_id,
                candidates=candidates,
                action_key=action_key,
                claims=claims,
                observations=grouped_observations.get(vessel_key, []),
            )
            if old is not None:
                old_signature = self._card_signature(old)
                new_signature = self._card_signature(card)
                unchanged = old_signature == new_signature
                card.revision = old.revision if unchanged else old.revision + 1
                card.revision_history = list(old.revision_history)
                if not unchanged:
                    card.revision_history.append(
                        {
                            "revision": old.revision,
                            "status": old.status,
                            "blocker_keys": list(old.blocker_keys),
                            "advisory_keys": list(old.advisory_keys),
                            "condition_states": {
                                key: condition.state for key, condition in old.conditions.items()
                            },
                            "after_ingest_order": self.ingest_count,
                        }
                    )
                if old.completed and old.completion:
                    # Completion outcome is an immutable historical projection.
                    card.completed = True
                    card.immutable = True
                    card.status = "completed"
                    card.completion = old.completion
                    card.blocker_keys = []
            else:
                card.revision = 1
            new_cards[card.id] = card

        self.action_cards = new_cards
        self._derive_card_issues()

    def _card_signature(self, card: ActionCard) -> tuple[Any, ...]:
        return (
            card.status,
            tuple(sorted(card.blocker_keys)),
            tuple(sorted(card.advisory_keys)),
            tuple(sorted((k, c.state) for k, c in card.conditions.items())),
            tuple(sorted(card.order_claim_ids)),
            tuple(sorted(card.suggestion_claim_ids)),
            tuple(sorted(card.clearance_claim_ids)),
            tuple((t.key, t.relation) for t in card.timeline),
            card.completed,
        )

    def _build_card(
        self,
        *,
        card_id: str,
        vessel_key: str,
        vessel_id: str | None,
        candidates: list[str],
        action_key: str,
        claims: list[Any],
        observations: list[Any],
    ) -> ActionCard:
        label = ACTION_LABELS.get(action_key, action_key)
        card = ActionCard(
            id=card_id,
            action_key=action_key,
            action_label=label,
            title=label,
            vessel_id=vessel_id,
            vessel_candidates=candidates,
        )

        evidence: list[Evidence] = []
        record_ids: list[str] = []

        def add_evidence(items: list[Evidence]) -> None:
            for ev in items:
                if not any(_evidence_key(e) == _evidence_key(ev) for e in evidence):
                    evidence.append(ev)

        for claim in claims:
            add_evidence(list(claim.evidence))
            if claim.record_id not in record_ids:
                record_ids.append(claim.record_id)
            if claim.kind == "order" or claim.speech_act == "order":
                card.order_claim_ids.append(claim.id)
            if claim.kind == "suggestion" or claim.speech_act == "suggestion":
                card.suggestion_claim_ids.append(claim.id)
            if "clearance" in claim.kind or "clearance" in claim.speech_act:
                card.clearance_claim_ids.append(claim.id)
            if claim.kind.endswith("report") or "report" in claim.kind or claim.kind == "temporal_reference":
                card.report_claim_ids.append(claim.id)

        card.evidence = evidence
        card.source_record_ids = record_ids

        # Conditions explicitly attached to extracted claims.
        for claim in claims:
            for key in claim.condition_keys:
                if key in card.conditions:
                    continue
                condition = self._copy_condition(key)
                # Suggestion-derived weather/timing is advisory unless a
                # blocking source also established the same key.
                if claim.kind == "suggestion" or claim.speech_act == "suggestion":
                    if condition.source == "shore_suggestion":
                        condition.blocking = False
                if action_key == "maintain_position" and key == "authorization.shore_clearance":
                    condition.blocking = False
                    condition.detail["role"] = "termination_condition_for_maintain_position"
                card.conditions[key] = condition
                card.condition_keys.append(key)

        # Command authority.
        if action_key in self.policy.get("captain_order_actions", []):
            authority = Condition(
                key="authority.captain_order",
                label="船长命令（岸站建议/转译不能替代）",
                category="authority",
                blocking=True,
            )
            order_claims = [self.claims[cid] for cid in card.order_claim_ids if cid in self.claims]
            if order_claims:
                authority.state = "met"
                for claim in order_claims:
                    authority.state_evidence.extend(claim.evidence)
            else:
                authority.state = "absent"
                suggestions = [self.claims[cid] for cid in card.suggestion_claim_ids if cid in self.claims]
                authority.detail["only_suggestion"] = bool(suggestions)
                if suggestions:
                    authority.state_evidence.extend(suggestions[0].evidence)
            card.conditions[authority.key] = authority
            card.condition_keys.append(authority.key)

        # Shore clearance / confirmation.
        if action_key in self.policy.get("clearance_actions", []):
            auth = self._copy_condition("authorization.shore_clearance", blocking=True)
            auth.label = "岸站确认/作业许可已签发并收到"
            card.conditions[auth.key] = auth
            if auth.key not in card.condition_keys:
                card.condition_keys.append(auth.key)

        # Maintain-position uses clearance as its termination condition, not a
        # prerequisite for continuing to hold position.
        if action_key == "maintain_position" and "authorization.shore_clearance" in card.conditions:
            card.conditions["authorization.shore_clearance"].blocking = False
            card.conditions["authorization.shore_clearance"].detail["role"] = "termination_condition"

        # Equipment applicability and policy.
        equipment = [o for o in observations if o.category == "equipment"]
        equipment.sort(key=lambda o: int(o.attributes.get("ingest_order", 0)))
        hard_states = set(self.policy.get("positioning_hard_block_states", {}).get(action_key, []))
        advisory_states = set(self.policy.get("positioning_advisory_states", []))
        latest_by_subject: dict[str, Any] = {}
        for obs in equipment:
            latest_by_subject[obs.subject] = obs
            add_evidence(list(obs.evidence))
            if obs.record_id not in record_ids:
                record_ids.append(obs.record_id)
            if obs.temporal_relation and obs.reference_event == "shift_anchor":
                event_key = f"equipment-{obs.id}"
                card.timeline.append(
                    # Local import avoids a module cycle in type references.
                    __import__("voyage_handover.models", fromlist=["TimelineEvent"]).TimelineEvent(
                        key=event_key,
                        label=obs.label,
                        relation=obs.temporal_relation,
                        timestamp=obs.timestamp,
                        evidence=list(obs.evidence),
                        source_observation_id=obs.id,
                    )
                )

        for obs in latest_by_subject.values():
            relation = obs.temporal_relation
            applies_before_action = relation != "after"
            if obs.state in hard_states and applies_before_action:
                condition = self._copy_condition("equipment.positioning_normal", blocking=True)
                condition.state = "absent" if obs.state in {"intermittent", "lost", "fault"} else condition.state
                condition.label = "定位/设备状态满足该作业的安全要求"
                condition.state_evidence = list(obs.evidence)
                condition.detail["observed_state"] = obs.state
                condition.detail["temporal_relation"] = relation or "unknown"
                card.conditions[condition.key] = condition
                if condition.key not in card.condition_keys:
                    card.condition_keys.append(condition.key)
                card.blocker_keys.append(condition.key)
            elif obs.state in advisory_states:
                card.advisory_keys.append(obs.id)
                obs.attributes["applicability"] = (
                    "before_or_unclear_relative_to_action"
                    if applies_before_action
                    else "after_reference_action"
                )
                if relation is None and self.policy.get("block_on_untimed_abnormal_positioning"):
                    timing_key = "equipment.timing_verified"
                    timing_condition = Condition(
                        key=timing_key,
                        label="已核实设备异常相对于行动的时间",
                        category="equipment",
                        state="required",
                        blocking=True,
                        requirement_evidence=list(obs.evidence),
                    )
                    card.conditions[timing_key] = timing_condition
                    card.condition_keys.append(timing_key)
            elif obs.state == "normal":
                condition = self._copy_condition("equipment.positioning_normal", blocking=bool(hard_states))
                condition.state = "met"
                condition.state_evidence = list(obs.evidence)
                card.conditions[condition.key] = condition
                if condition.key not in card.condition_keys:
                    card.condition_keys.append(condition.key)

        # Completion from track/completion records.
        vessel_for_completion = vessel_id or self.analyzer.registry.default_vessel_id or "UNRESOLVED"
        completion = self.completion_events.get(f"{vessel_for_completion}:{action_key}")
        if completion is None and vessel_id is None and candidates:
            for candidate in candidates:
                completion = self.completion_events.get(f"{candidate}:{action_key}")
                if completion:
                    break
        if completion:
            card.completed = True
            card.immutable = bool(completion.get("explicit_track_record") or completion.get("explicit_record"))
            card.completion = completion
            card.status = "completed"
            completion_evidence = completion.get("evidence")
            if isinstance(completion_evidence, dict):
                try:
                    ev = Evidence(**completion_evidence)
                    if not any(_evidence_key(e) == _evidence_key(ev) for e in evidence):
                        evidence.append(ev)
                except TypeError:
                    pass
            record_id = completion.get("record_id")
            if record_id and record_id not in record_ids:
                record_ids.append(record_id)

        # Final blocker/advisory calculation.
        blockers: list[str] = []
        advisories: list[str] = []
        for key in card.condition_keys:
            condition = card.conditions.get(key)
            if condition is None:
                continue
            if condition.blocking and condition.state != "met" and not card.completed:
                blockers.append(key)
            elif not condition.blocking and condition.state != "met":
                advisories.append(key)
        card.blocker_keys = sorted(set(blockers))
        card.advisory_keys = sorted(set(card.advisory_keys) | set(advisories))

        if not card.completed:
            if vessel_key.startswith("A:") or vessel_key == "U":
                card.status = "ambiguous"
            elif action_key == "maintain_position" and card.order_claim_ids:
                card.status = "in_force"
            elif card.blocker_keys:
                card.status = "blocked"
            else:
                card.status = "ready"

        card.condition_keys = sorted(set(card.condition_keys))
        card.source_record_ids = list(dict.fromkeys(record_ids))
        card.evidence = evidence
        return card

    def _derive_card_issues(self) -> None:
        for card in self.action_cards.values():
            translated_positive = [
                self.claims[cid]
                for cid in card.clearance_claim_ids
                if cid in self.claims
                and self.claims[cid].kind == "translated_clearance_claim"
                and self.claims[cid].polarity == "positive"
            ]
            auth = card.conditions.get("authorization.shore_clearance")
            authoritative_met = bool(auth and auth.state == "met")
            if translated_positive and not authoritative_met:
                order_evidence: list[Evidence] = []
                for cid in card.order_claim_ids:
                    if cid in self.claims:
                        order_evidence.extend(self.claims[cid].evidence)
                evidence = list(translated_positive[0].evidence) + order_evidence
                if auth and auth.state_evidence:
                    evidence.extend(auth.state_evidence[:1])
                self.derived_issues.append(
                    Issue(
                        code="conditional_permission_flattened",
                        severity="blocker",
                        message=(
                            "转译/摘要出现无条件“已批准”表述，但原始条件/许可状态不支持已确认许可；"
                            "不得据此启动行动。"
                        ),
                        evidence=evidence,
                        details={
                            "action_card_id": card.id,
                            "translated_claim_id": translated_positive[0].id,
                            "authorization_state": auth.state if auth else "missing",
                        },
                    )
                )

            if card.status != "completed" and card.action_key in {"shift_anchor", "start_operations"}:
                after_obs = [
                    self.observations[o.source_observation_id]
                    for event in card.timeline
                    if event.relation == "after" and event.source_observation_id in self.observations
                    for o in [event]
                ]
                if after_obs:
                    self.derived_issues.append(
                        Issue(
                            code="after_reference_without_completion_record",
                            severity="warning",
                            message=(
                                "新日志用“移锚之后”叙述设备事件，但尚无不可改写的完成/航迹记录；"
                                "行动卡继续保留并重新判定，需值班员核实移锚是否已完成。"
                            ),
                            evidence=list(after_obs[0].evidence),
                            details={"action_card_id": card.id},
                        )
                    )

    # ------------------------------------------------------------------
    # Query / serialization
    # ------------------------------------------------------------------
    def lookup_sentence(self, sentence_id: str) -> dict[str, Any] | None:
        return self.sentences.get(sentence_id)

    def trace(self, sentence_id: str) -> dict[str, Any]:
        """Return a source sentence and every judgement citing it."""

        source = self.sentences.get(sentence_id)
        claims = [c.to_dict() for c in self.claims.values() if c.sentence_id == sentence_id]
        observations = [o.to_dict() for o in self.observations.values() if o.sentence_id == sentence_id]
        cards = [
            card.to_dict()
            for card in self.action_cards.values()
            if any(e.sentence_id == sentence_id for e in card.evidence)
        ]
        issues = [
            issue.to_dict()
            for issue in self.all_issues()
            if any(e.sentence_id == sentence_id for e in issue.evidence)
        ]
        return {
            "sentence": source,
            "claims": claims,
            "observations": observations,
            "action_cards": cards,
            "issues": issues,
        }

    def all_issues(self) -> list[Issue]:
        # Deduplicate by code and evidence record/sentence/quote.
        result: list[Issue] = []
        seen: set[tuple[str, tuple[Any, ...]]] = set()
        for issue in [*self.issues, *self.derived_issues]:
            ev_sig = tuple(sorted((e.record_id, e.sentence_id, e.quote) for e in issue.evidence))
            key = (issue.code, ev_sig)
            if key not in seen:
                seen.add(key)
                result.append(issue)
        return result

    def briefing(self) -> dict[str, Any]:
        from .briefing import build_briefing

        return build_briefing(self)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "case_id": self.case_id,
            "vessels": self.vessels,
            "policy": self.policy,
            "source_records": list(self.records.values()),
            "record_hashes": self.record_hashes,
            "sentences": self.sentences,
            "claims": [c.to_dict() for c in self.claims.values()],
            "observations": [o.to_dict() for o in self.observations.values()],
            "conditions": {k: v.to_dict() for k, v in sorted(self.conditions.items())},
            "issues": [i.to_dict() for i in self.all_issues()],
            "action_cards": {k: v.to_dict() for k, v in sorted(self.action_cards.items())},
            "track_records": self.track_records,
            "track_chain": self.track_chain,
            "track_chain_verified": self.verify_track_chain(),
            "completion_events": self.completion_events,
            "briefing": self.briefing(),
        }
