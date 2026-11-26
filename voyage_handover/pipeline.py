"""Deterministic multilingual NLP pipeline for hand-over excerpts."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .entities import VesselRegistry
from .lexicon import (
    ACTION_PATTERNS,
    APPROVED_UNCONDITIONAL_PATTERN,
    CLARIFICATION,
    COMPLETION_MARKER,
    CONDITION_PATTERNS,
    CONDITIONAL_MARKER,
    EQUIPMENT_INTERMITTENT,
    EQUIPMENT_LOST,
    EQUIPMENT_NORMAL,
    EQUIPMENT_SUBJECT,
    GENERIC_MOVEMENT_PATTERNS,
    KIND_ROLE,
    NEGATIVE_AUTHORIZATION,
    ORDER_PATTERN,
    POSITIVE_AUTHORIZATION,
    ROLE_LABELS_ZH,
    SEA_NUMERIC,
    SEA_QUALITATIVE,
    SPEAKER_PATTERNS,
    SUGGESTION_PATTERN,
    TEMPORAL_AFTER_ANCHOR,
    TEMPORAL_BEFORE_ANCHOR,
    TIME_REF,
    TIME_UNKNOWN,
    TIME_WINDOW,
    TRANSLATION_MARKER,
)
from .models import Claim, Condition, Evidence, Issue, Observation, VesselRef

SENTENCE_DELIMITERS = "。！？!?；;\n"

ACTION_COMPLETED = re.compile(
    r"(?:移锚|移錨|anchor\s+move|anchor\s+operation|ANC\s+MOV)[^。；;\n]{0,40}"
    r"(?:已(?:经)?\s*完成|完成了|完毕|结束)|"
    r"(?:已(?:经)?\s*完成|has\s+(?:been\s+)?completed|completed|finished)\b[^。；;\n]{0,40}"
    r"(?:移锚|移錨|anchor|ANC)",
    re.I,
)

SPEECH_CUE = re.compile(
    r"说|说道|說道|表示|指出|声称|聲稱|称|稱|建议|建議|提议|提議|命令|指示|"
    r"要求|报告|報告|通报|通報|答复|答覆|回复|回覆|译|譯|：|"
    r"\bsays?\b|\bsaid\b|\bstated?\b|\breports?\b|\bnotified?\b|\binforms?\b|"
    r"\bsuggests?\b|\brecommends?\b|\badvises?\b|\borders?\b|\bdirects?\b|"
    r"\bcalls?\b|\btransmits?\b|\bradio(?:ed)?\b|:",
    re.I,
)

FAULT_STATE = re.compile(r"故障|failure|malfunction|\bfault\b", re.I)


@dataclass
class Sentence:
    id: str
    index: int
    text: str
    start: int
    end: int
    lang: str


@dataclass
class RecordAnalysis:
    record_id: str
    kind: str
    lang: str
    timestamp: str | None
    vessel: VesselRef
    sentences: list[Sentence] = field(default_factory=list)
    claims: list[Claim] = field(default_factory=list)
    conditions: list[Condition] = field(default_factory=list)
    observations: list[Observation] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    completion: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "kind": self.kind,
            "lang": self.lang,
            "timestamp": self.timestamp,
            "vessel": self.vessel.to_dict(),
            "sentences": [vars(s) for s in self.sentences],
            "claims": [c.to_dict() for c in self.claims],
            "conditions": [c.to_dict() for c in self.conditions],
            "observations": [o.to_dict() for o in self.observations],
            "issues": [i.to_dict() for i in self.issues],
            "completion": self.completion,
        }


def detect_language(record: dict[str, Any], text: str) -> str:
    lang = str(record.get("lang", "")).lower().replace("_", "-")
    if lang.startswith("zh"):
        return "zh"
    if lang.startswith("en"):
        return "en"
    cjk = len(re.findall(r"[一-鿿]", text))
    latin = len(re.findall(r"[A-Za-z]", text))
    if cjk and cjk >= latin / 3:
        return "zh"
    return "en" if latin else "zh"


def source_kind(record: dict[str, Any]) -> str:
    kind = record.get("kind") or record.get("type")
    if not kind:
        source = record.get("source")
        if isinstance(source, str):
            kind = source
        elif isinstance(source, dict):
            kind = source.get("kind") or source.get("role") or source.get("type")
    return str(kind or "unknown")


def record_timestamp(record: dict[str, Any]) -> str | None:
    value = (
        record.get("timestamp")
        or record.get("event_time")
        or record.get("time")
        or record.get("observed_at")
        or record.get("received_at")
    )
    return str(value) if value not in (None, "") else None


def split_sentences(record_id: str, text: str, lang: str) -> list[Sentence]:
    sentences: list[Sentence] = []
    start = 0
    index = 1
    for pos, char in enumerate(text):
        if char in SENTENCE_DELIMITERS:
            raw = text[start : pos + 1]
            if raw.strip():
                left = len(raw) - len(raw.lstrip())
                right = len(raw.rstrip())
                abs_start = start + left
                abs_end = start + right
                sentences.append(
                    Sentence(
                        id=f"{record_id}#S{index}",
                        index=index,
                        text=text[abs_start:abs_end],
                        start=abs_start,
                        end=abs_end,
                        lang=lang,
                    )
                )
                index += 1
            start = pos + 1
    raw = text[start:]
    if raw.strip():
        left = len(raw) - len(raw.lstrip())
        right = len(raw.rstrip())
        abs_start = start + left
        abs_end = start + right
        sentences.append(
            Sentence(
                id=f"{record_id}#S{index}",
                index=index,
                text=text[abs_start:abs_end],
                start=abs_start,
                end=abs_end,
                lang=lang,
            )
        )
    return sentences


def iter_clauses(sentence: Sentence, original_text: str):
    """Yield ``(text, absolute_start, absolute_end)`` comma clauses."""

    for match in re.finditer(r"[^，,]+", sentence.text):
        raw = match.group()
        if not raw.strip():
            continue
        left = len(raw) - len(raw.lstrip())
        right = len(raw.rstrip())
        abs_start = sentence.start + match.start() + left
        abs_end = sentence.start + match.start() + right
        yield original_text[abs_start:abs_end], abs_start, abs_end


def detect_actions(text: str) -> list[tuple[str, str, bool]]:
    found: list[tuple[str, str, bool]] = []
    for key, label, patterns in ACTION_PATTERNS:
        if any(p.search(text) for p in patterns):
            found.append((key, label, False))
    if not found and any(p.search(text) for p in GENERIC_MOVEMENT_PATTERNS):
        found.append(("move_vessel", "移船/移动（需上下文指代）", True))
    return found


class NlpAnalyzer:
    """Analyze records using an optional vessel registry."""

    def __init__(self, vessels: list[dict[str, Any]] | VesselRegistry | None = None):
        if isinstance(vessels, VesselRegistry):
            self.registry = vessels
        else:
            self.registry = VesselRegistry(vessels or [])

    def analyze_case(self, case: dict[str, Any]) -> list[RecordAnalysis]:
        if not isinstance(self.registry, VesselRegistry) or not self.registry.vessels:
            self.registry = VesselRegistry(case.get("vessels", []))
        return [self.analyze_record(record) for record in case.get("records", [])]

    def analyze_record(self, record: dict[str, Any]) -> RecordAnalysis:
        if not isinstance(record, dict):
            raise ValueError("record must be an object")
        rid = str(record.get("id") or "").strip()
        text = record.get("text")
        if not rid:
            raise ValueError("record.id is required")
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"record {rid} has non-empty text required")

        kind = source_kind(record)
        lang = detect_language(record, text)
        timestamp = record_timestamp(record)
        vessel_evidence = Evidence(
            record_id=rid,
            quote=text[:200],
            lang=lang,
            source_kind=kind,
        )
        vessel = self.registry.resolve(
            text,
            record_vessel_id=record.get("vessel_id"),
            timestamp=timestamp,
            evidence=vessel_evidence,
        )
        sentences = split_sentences(rid, text, lang)
        analysis = RecordAnalysis(
            record_id=rid,
            kind=kind,
            lang=lang,
            timestamp=timestamp,
            vessel=vessel,
            sentences=sentences,
        )

        if vessel.resolution == "ambiguous_reused_identifier":
            analysis.issues.append(
                Issue(
                    code="ambiguous_vessel_identifier",
                    severity="blocker",
                    message=(
                        f"标识 {vessel.mention!r} 被多个船只复用："
                        f"{', '.join(vessel.candidates)}；不得猜测归属。"
                    ),
                    evidence=[vessel_evidence],
                    details={"candidates": vessel.candidates},
                )
            )
        elif vessel.resolution in {"unknown_explicit_vessel", "ambiguous_or_expired_identifier"}:
            analysis.issues.append(
                Issue(
                    code="unresolved_vessel",
                    severity="warning",
                    message="无法按船只登记簿可靠解析该记录中的船名/呼号。",
                    evidence=[vessel_evidence],
                    details={"resolution": vessel.resolution, "candidates": vessel.candidates},
                )
            )

        seq = 0
        last_action_key: str | None = record.get("action_key") if isinstance(record.get("action_key"), str) else None
        is_translation_record = kind == "translation" or kind == "translated-summary"

        for sentence in sentences:
            sentence_evidence = Evidence(
                record_id=rid,
                sentence_id=sentence.id,
                quote=sentence.text,
                start=sentence.start,
                end=sentence.end,
                lang=lang,
                source_kind=kind,
            )
            clauses = list(iter_clauses(sentence, text))
            equipment_context = False
            carried_speaker: tuple[str, str | None] | None = None
            pending_condition_keys: list[str] = []

            for clause, cstart, cend in clauses:
                seq += 1
                clause_evidence = Evidence(
                    record_id=rid,
                    sentence_id=sentence.id,
                    quote=clause,
                    start=cstart,
                    end=cend,
                    lang=lang,
                    source_kind=kind,
                )
                speaker_role, speaker_label, speaker_explicit = self._speaker(clause, kind, record)
                if speaker_explicit:
                    carried_speaker = (speaker_role, speaker_label)
                elif carried_speaker is not None:
                    # A speaker tag before a comma governs the following
                    # shorthand clauses in the same sentence.
                    speaker_role, speaker_label = carried_speaker
                reporter_role = KIND_ROLE.get(kind.lower(), "unknown")
                translation = is_translation_record or bool(TRANSLATION_MARKER.search(clause))

                actions = detect_actions(clause)
                explicit_action_keys = [a[0] for a in actions if a[0] != "move_vessel"]
                if explicit_action_keys:
                    last_action_key = explicit_action_keys[0]
                elif any(a[0] == "move_vessel" for a in actions):
                    # Keep generic movement as the local discourse topic.  The
                    # store will corefer it to a unique known action card.
                    last_action_key = "move_vessel"

                clause_conditions = self._conditions(
                    clause,
                    clause_evidence,
                    speaker_role=speaker_role,
                    translation=translation,
                )
                for condition in clause_conditions:
                    self._merge_condition(analysis.conditions, condition)

                current_condition_keys = [condition.key for condition in clause_conditions]
                attached_condition_keys = list(current_condition_keys)
                if actions:
                    if not attached_condition_keys and CONDITIONAL_MARKER.search(clause):
                        attached_condition_keys = list(pending_condition_keys)
                    for key in attached_condition_keys:
                        condition = next((c for c in analysis.conditions if c.key == key), None)
                        if condition is not None and condition.state == "unknown":
                            condition.state = "required"
                            condition.blocking = speaker_role == "captain" or condition.blocking
                            if not condition.requirement_evidence:
                                condition.requirement_evidence.append(sentence_evidence)
                    pending_condition_keys = []
                else:
                    for key in current_condition_keys:
                        if key not in pending_condition_keys:
                            pending_condition_keys.append(key)

                auth_info = self._authorization_claim(
                    clause=clause,
                    seq=seq,
                    rid=rid,
                    sentence=sentence,
                    evidence=clause_evidence,
                    sentence_evidence=sentence_evidence,
                    speaker_role=speaker_role,
                    speaker_label=speaker_label,
                    reporter_role=reporter_role,
                    translation=translation,
                    action_key=(explicit_action_keys[0] if explicit_action_keys else last_action_key),
                    vessel=vessel,
                )
                if auth_info is not None:
                    claim, issue = auth_info
                    analysis.claims.append(claim)
                    if issue is not None:
                        analysis.issues.append(issue)
                    seq += 1  # keep IDs separated after nested claim

                for action_key, action_label, contextual in actions:
                    claim = self._action_claim(
                        seq=seq,
                        rid=rid,
                        sentence=sentence,
                        evidence=clause_evidence,
                        sentence_evidence=sentence_evidence,
                        action_key=action_key,
                        action_label=action_label,
                        contextual=contextual,
                        clause=clause,
                        speaker_role=speaker_role,
                        speaker_label=speaker_label,
                        reporter_role=reporter_role,
                        translation=translation,
                        condition_keys=attached_condition_keys,
                        vessel=vessel,
                    )
                    analysis.claims.append(claim)
                    if action_key != "move_vessel":
                        last_action_key = action_key

                equipment_obs = self._equipment_observation(
                    clause=clause,
                    sentence=sentence,
                    sentence_text=sentence.text,
                    seq=seq,
                    rid=rid,
                    timestamp=timestamp,
                    vessel=vessel,
                    evidence=clause_evidence,
                    sentence_evidence=sentence_evidence,
                    equipment_context=equipment_context,
                )
                if equipment_obs is not None:
                    analysis.observations.append(equipment_obs)
                    equipment_context = True
                    if equipment_obs.attributes.get("timing_unknown"):
                        analysis.issues.append(
                            Issue(
                                code="equipment_timing_unknown",
                                severity="info",
                                message="设备异常仅有间歇/丢失报告，尚未记录其与移锚的时间先后。",
                                evidence=[sentence_evidence],
                            )
                        )
                    if equipment_obs.clarification and equipment_obs.temporal_relation:
                        analysis.issues.append(
                            Issue(
                                code="timing_clarification",
                                severity="info",
                                message=(
                                    f"新日志澄清设备事件发生在移锚"
                                    f"{'之前' if equipment_obs.temporal_relation == 'before' else '之后'}。"
                                ),
                                evidence=[sentence_evidence],
                                details={
                                    "temporal_relation": equipment_obs.temporal_relation,
                                    "observation_id": equipment_obs.id,
                                },
                            )
                        )

                sea_obs = self._sea_observations(
                    clause=clause,
                    seq_base=seq,
                    rid=rid,
                    timestamp=timestamp,
                    vessel=vessel,
                    evidence=clause_evidence,
                    time_text=sentence.text,
                )
                for obs in sea_obs:
                    analysis.observations.append(obs)
                    seq += 1

            # Sentence-level sea extraction catches numeric phrases split by
            # clause punctuation in unusual layouts.
            if not clauses:
                for obs in self._sea_observations(
                    clause=sentence.text,
                    seq_base=seq,
                    rid=rid,
                    timestamp=timestamp,
                    vessel=vessel,
                    evidence=sentence_evidence,
                    time_text=sentence.text,
                ):
                    analysis.observations.append(obs)
                    seq += 1

        completion = self._completion(record, text, timestamp, vessel, sentences)
        if completion:
            analysis.completion = completion

        return analysis

    def _speaker(
        self, text: str, kind: str, record: dict[str, Any]
    ) -> tuple[str, str | None, bool]:
        explicit = record.get("speaker")
        if isinstance(explicit, dict):
            role = explicit.get("role") or explicit.get("id") or "unknown"
            return str(role), explicit.get("name") or explicit.get("label"), True
        if explicit:
            explicit_text = str(explicit)
            for role, pattern in SPEAKER_PATTERNS:
                match = pattern.search(explicit_text)
                if match:
                    return role, match.group(0), True
            return "named_reporter", explicit_text, True

        for role, pattern in SPEAKER_PATTERNS:
            match = pattern.search(text)
            if match:
                window = text[max(0, match.start() - 8) : min(len(text), match.end() + 24)]
                # A bare mention such as “未收到岸站确认” identifies the
                # authority/object, not necessarily the present speaker.
                if SPEECH_CUE.search(window):
                    return role, match.group(0), True
        return KIND_ROLE.get(kind.lower(), "unknown"), None, False

    def _merge_condition(self, conditions: list[Condition], condition: Condition) -> None:
        for existing in conditions:
            if existing.key == condition.key:
                existing.requirement_evidence.extend(condition.requirement_evidence)
                existing.state_evidence.extend(condition.state_evidence)
                if condition.state != "required":
                    existing.state = condition.state
                existing.blocking = existing.blocking or condition.blocking
                existing.detail.update(condition.detail)
                return
        conditions.append(condition)

    def _conditions(
        self,
        text: str,
        evidence: Evidence,
        *,
        speaker_role: str,
        translation: bool,
    ) -> list[Condition]:
        found: list[Condition] = []
        conditional = bool(CONDITIONAL_MARKER.search(text))
        positive = bool(POSITIVE_AUTHORIZATION.search(text))
        negative = bool(NEGATIVE_AUTHORIZATION.search(text))

        for key, label, category, patterns in CONDITION_PATTERNS:
            match = next((p.search(text) for p in patterns if p.search(text)), None)
            if not match:
                continue
            condition = Condition(
                key=key,
                label=label,
                category=category,
                source="translated_text" if translation else speaker_role,
                detail={"matched_text": match.group(0), "conditional_marker": conditional},
            )

            if key == "authorization.shore_clearance":
                condition.blocking = True
                if conditional or negative or positive:
                    condition.requirement_evidence.append(evidence)
                if negative:
                    condition.state = "absent"
                    condition.state_evidence.append(evidence)
                elif positive and not translation:
                    condition.state = "met"
                    condition.state_evidence.append(evidence)
                elif positive and translation:
                    # A translated claim is only an assertion until corroborated.
                    condition.state = "unknown"
                    condition.state_evidence.append(evidence)
                    condition.detail["translated_claim_not_authoritative"] = True
                else:
                    condition.state = "required"
                found.append(condition)
                continue

            if key == "equipment.positioning_normal":
                if conditional:
                    condition.state = "required"
                    condition.requirement_evidence.append(evidence)
                elif positive or COMPLETION_MARKER.search(text) or EQUIPMENT_NORMAL.search(text):
                    condition.state = "met"
                    condition.state_evidence.append(evidence)
                else:
                    condition.state = "unknown"
                found.append(condition)
                continue

            # Weather / sea-state conditions.
            if conditional:
                condition.state = "required"
                condition.requirement_evidence.append(evidence)
                # A shore suggestion supplies advisory timing, not the
                # captain's blocking requirement.
                condition.blocking = not bool(SUGGESTION_PATTERN.search(text))
                if SUGGESTION_PATTERN.search(text):
                    condition.source = "shore_suggestion"
                    condition.detail["advisory"] = True
            elif positive or COMPLETION_MARKER.search(text):
                condition.state = "met"
                condition.state_evidence.append(evidence)
            else:
                condition.state = "unknown"
                condition.detail["mentioned_without_completion_marker"] = True
            found.append(condition)
        return found

    def _action_claim(
        self,
        *,
        seq: int,
        rid: str,
        sentence: Sentence,
        evidence: Evidence,
        sentence_evidence: Evidence,
        action_key: str,
        action_label: str,
        contextual: bool,
        clause: str,
        speaker_role: str,
        speaker_label: str | None,
        reporter_role: str,
        translation: bool,
        condition_keys: list[str],
        vessel: VesselRef,
    ) -> Claim:
        suggestion = bool(SUGGESTION_PATTERN.search(clause))
        order_marker = bool(ORDER_PATTERN.search(clause))
        conditional = bool(CONDITIONAL_MARKER.search(clause))
        temporal_reference = bool(
            TEMPORAL_BEFORE_ANCHOR.search(clause) or TEMPORAL_AFTER_ANCHOR.search(clause)
        )
        approved = bool(POSITIVE_AUTHORIZATION.search(clause)) or bool(
            APPROVED_UNCONDITIONAL_PATTERN.search(clause)
        )
        polarity = "positive"

        if translation and approved:
            kind = "translated_approval_claim"
            speech_act = "translated_approval"
            modality = "unconditional" if not conditional else "conditional"
            confidence = "medium"
            summary = f"转译文本声称已批准/可执行 {action_label}，但转译本身不是许可确认。"
        elif temporal_reference and not order_marker and not suggestion:
            kind = "temporal_reference"
            speech_act = "temporal_reference"
            modality = "temporal"
            polarity = "neutral"
            confidence = "high"
            summary = f"“{action_label}”在此是时间参照事件，不是新的命令或许可。"
        elif suggestion:
            kind = "suggestion"
            speech_act = "suggestion"
            modality = "conditional" if conditional else "neutral"
            confidence = "high" if not contextual else "medium"
            summary = f"{ROLE_LABELS_ZH.get(speaker_role, speaker_role)}建议/提议 {action_label}。"
        elif order_marker or speaker_role == "captain" or (conditional and not temporal_reference) or action_key == "maintain_position":
            kind = "order"
            speech_act = "order"
            modality = "conditional" if conditional else "unconditional"
            confidence = "high" if not contextual else "medium"
            prefix = "条件性" if conditional else ""
            summary = f"{ROLE_LABELS_ZH.get(speaker_role, speaker_role)}{prefix}指令：{action_label}。"
        else:
            kind = "action_statement"
            speech_act = "statement"
            modality = "conditional" if conditional else "unknown"
            confidence = "medium" if contextual else "high"
            summary = f"出现行动表述 {action_label}，需结合上下文判断言语行为。"

        return Claim(
            id=f"CL-{rid}-{seq:02d}-A",
            record_id=rid,
            sentence_id=sentence.id,
            kind=kind,
            summary=summary,
            speaker_role=speaker_role,
            speaker_label=speaker_label,
            reporter_role=reporter_role,
            action_key=action_key,
            action_label=action_label,
            speech_act=speech_act,
            modality=modality,
            polarity=polarity,
            confidence=confidence,
            vessel=vessel,
            evidence=[sentence_evidence, evidence],
            condition_keys=condition_keys,
            attributes={
                "contextual_coreference_candidate": contextual,
                "translation": translation,
                "authoritative": not (translation and approved),
                "clause": clause,
            },
        )

    def _authorization_claim(
        self,
        *,
        clause: str,
        seq: int,
        rid: str,
        sentence: Sentence,
        evidence: Evidence,
        sentence_evidence: Evidence,
        speaker_role: str,
        speaker_label: str | None,
        reporter_role: str,
        translation: bool,
        action_key: str | None,
        vessel: VesselRef,
    ) -> tuple[Claim, Issue | None] | None:
        auth_pattern = CONDITION_PATTERNS[2][3]  # authorization.shore_clearance
        negative = bool(NEGATIVE_AUTHORIZATION.search(clause))
        positive = bool(POSITIVE_AUTHORIZATION.search(clause))
        unconditional_approval = bool(APPROVED_UNCONDITIONAL_PATTERN.search(clause))
        if not (
            any(p.search(clause) for p in auth_pattern)
            or negative
            or positive
            or unconditional_approval
        ):
            return None
        if not (negative or positive or unconditional_approval):
            status_cue = re.search(
                r"pending|request(?:ed)?|ask(?:ed)?|need(?:ed)?|required|subject to|await(?:ing)?|"
                r"等待|待|申请|请求|需",
                clause,
                re.I,
            )
            if not status_cue:
                return None

        issue: Issue | None = None
        if translation and (positive or unconditional_approval):
            kind = "translated_clearance_claim"
            speech_act = "translated_clearance"
            polarity = "positive"
            summary = "转译/摘要声称岸站已批准或签发许可；在与原始岸站记录核对前不得视为已确认。"
            confidence = "medium"
            issue = Issue(
                code="unverified_translation_as_clearance",
                severity="warning",
                message="“已批准”来自转译/摘要文本；条件句或许可状态可能在翻译中被压成无条件许可。",
                evidence=[sentence_evidence, evidence],
                details={"action_key": action_key},
            )
        elif negative:
            kind = "clearance_status"
            speech_act = "clearance_withheld"
            polarity = "negative"
            summary = "明确说明岸站确认/许可尚未收到或尚未签发。"
            confidence = "high"
        elif positive or unconditional_approval:
            kind = "clearance"
            speech_act = "clearance_issued"
            polarity = "positive"
            summary = "出现岸站已确认、批准或签发许可的肯定表述。"
            confidence = "high" if not translation else "medium"
        else:
            kind = "clearance_status"
            speech_act = "clearance_mentioned"
            polarity = "neutral"
            summary = "提到许可/确认，但没有足够肯定或否定词判断状态。"
            confidence = "medium"

        claim = Claim(
            id=f"CL-{rid}-{seq:02d}-C",
            record_id=rid,
            sentence_id=sentence.id,
            kind=kind,
            summary=summary,
            speaker_role=speaker_role,
            speaker_label=speaker_label,
            reporter_role=reporter_role,
            action_key=action_key,
            action_label=None,
            speech_act=speech_act,
            modality="unconditional" if positive and not negative else "status",
            polarity=polarity,
            confidence=confidence,
            vessel=vessel,
            evidence=[sentence_evidence, evidence],
            condition_keys=["authorization.shore_clearance"],
            attributes={
                "authoritative": not (translation and positive),
                "translation": translation,
                "unconditional_approval_text": unconditional_approval,
            },
        )
        return claim, issue

    def _equipment_observation(
        self,
        *,
        clause: str,
        sentence: Sentence,
        sentence_text: str,
        seq: int,
        rid: str,
        timestamp: str | None,
        vessel: VesselRef,
        evidence: Evidence,
        sentence_evidence: Evidence,
        equipment_context: bool,
    ) -> Observation | None:
        subject_match = EQUIPMENT_SUBJECT.search(clause)
        intermittent = bool(EQUIPMENT_INTERMITTENT.search(clause))
        lost = bool(EQUIPMENT_LOST.search(clause))
        normal = bool(EQUIPMENT_NORMAL.search(clause))
        fault = bool(FAULT_STATE.search(clause))

        if (
            not subject_match
            and not fault
            and not (equipment_context and (intermittent or lost or normal or fault))
        ):
            return None

        if intermittent:
            state = "intermittent"
            label = "定位信号间歇/周期性丢失"
            key = "equipment.positioning.intermittent"
        elif lost:
            state = "lost"
            label = "定位信号丢失/中断"
            key = "equipment.positioning.lost"
        elif fault:
            state = "fault"
            label = "设备故障（细节未分类）"
            key = "equipment.fault"
        elif normal and (subject_match or equipment_context):
            state = "normal"
            label = "定位/设备状态恢复正常"
            key = "equipment.positioning.normal"
        elif subject_match:
            state = "mentioned"
            label = "提到定位/设备状态"
            key = "equipment.positioning.mentioned"
        else:
            return None

        relation = None
        if TEMPORAL_BEFORE_ANCHOR.search(sentence_text):
            relation = "before"
        elif TEMPORAL_AFTER_ANCHOR.search(sentence_text):
            relation = "after"

        time_match = TIME_REF.search(sentence_text)
        timing_unknown = bool(TIME_UNKNOWN.search(sentence_text))
        clarification = bool(CLARIFICATION.search(sentence_text))
        frequency_match = re.search(
            r"每隔[^，,。；;]{0,12}|every\s+[^.;]{0,20}minutes?", sentence_text, re.I
        )

        return Observation(
            id=f"OB-{rid}-{seq:02d}-E",
            record_id=rid,
            sentence_id=sentence.id,
            category="equipment",
            subject="positioning_system",
            key=key,
            label=label,
            state=state,
            value=frequency_match.group(0) if frequency_match else None,
            time_ref=time_match.group(0) if time_match else None,
            timestamp=timestamp,
            temporal_relation=relation,
            reference_event="shift_anchor" if relation else None,
            clarification=clarification,
            vessel=vessel,
            evidence=[sentence_evidence],
            attributes={
                "timing_unknown": timing_unknown,
                "subject_match": subject_match.group(0) if subject_match else None,
            },
        )

    def _sea_observations(
        self,
        *,
        clause: str,
        seq_base: int,
        rid: str,
        timestamp: str | None,
        vessel: VesselRef,
        evidence: Evidence,
        time_text: str | None = None,
    ) -> list[Observation]:
        observations: list[Observation] = []
        time_source = time_text or clause
        time_match = TIME_REF.search(time_source)
        time_ref = time_match.group(0) if time_match else None
        window_match = TIME_WINDOW.search(time_source)
        time_window = window_match.group(0) if window_match else None
        for offset, match in enumerate(SEA_NUMERIC.finditer(clause)):
            subject = match.group("subject").lower()
            value = match.group("value")
            unit = (match.group("unit") or "").strip()
            category = "weather" if re.search(r"wind|风", subject, re.I) else "sea_state"
            key = f"{category}.numeric.{re.sub(r'[^a-z0-9]+', '_', subject.lower()).strip('_')}"
            observations.append(
                Observation(
                    id=f"OB-{rid}-{seq_base + offset:02d}-S",
                    record_id=rid,
                    sentence_id=evidence.sentence_id,
                    category=category,
                    subject=subject,
                    key=key,
                    label=f"{match.group('subject')} {value}{unit}",
                    state="observed",
                    value=f"{value}{unit}",
                    time_ref=time_ref,
                    timestamp=timestamp,
                    vessel=vessel,
                    evidence=[evidence],
                    attributes={
                        "numeric": float(value),
                        "unit": unit or None,
                        "time_window": time_window,
                    },
                )
            )
        qualitative = SEA_QUALITATIVE.search(clause)
        if qualitative and not observations:
            observations.append(
                Observation(
                    id=f"OB-{rid}-{seq_base:02d}-Q",
                    record_id=rid,
                    sentence_id=evidence.sentence_id,
                    category="sea_state",
                    subject="sea_state",
                    key="sea_state.qualitative",
                    label=qualitative.group(0),
                    state="observed",
                    value=qualitative.group(0),
                    time_ref=time_ref,
                    timestamp=timestamp,
                    vessel=vessel,
                    evidence=[evidence],
                    attributes={"time_window": time_window},
                )
            )
        return observations

    def _completion(
        self,
        record: dict[str, Any],
        text: str,
        timestamp: str | None,
        vessel: VesselRef,
        sentences: list[Sentence],
    ) -> dict[str, Any] | None:
        kind = source_kind(record).lower()
        explicit_completed = record.get("completed") is True or record.get("status") == "completed"
        action_key = record.get("action_key")
        if not action_key:
            for sentence in sentences:
                actions = detect_actions(sentence.text)
                if actions:
                    action_key = next((a[0] for a in actions if a[0] != "move_vessel"), actions[0][0])
                    break
        if kind in {"completion", "action-completion", "outcome"} and action_key:
            return {
                "action_key": action_key,
                "completed_at": record.get("completed_at") or timestamp,
                "record_id": str(record["id"]),
                "evidence": Evidence(
                    record_id=str(record["id"]),
                    quote=text,
                    lang=record.get("lang"),
                    source_kind=source_kind(record),
                ).to_dict(),
                "explicit_record": True,
            }
        if explicit_completed and action_key:
            return {
                "action_key": action_key,
                "completed_at": record.get("completed_at") or timestamp,
                "record_id": str(record["id"]),
                "evidence": Evidence(
                    record_id=str(record["id"]),
                    quote=text,
                    lang=record.get("lang"),
                    source_kind=source_kind(record),
                ).to_dict(),
                "explicit_record": True,
            }
        match = ACTION_COMPLETED.search(text)
        if match and action_key:
            sentence = next(
                (s for s in sentences if s.start <= match.start() < s.end),
                sentences[0] if sentences else None,
            )
            ev = Evidence(
                record_id=str(record["id"]),
                sentence_id=sentence.id if sentence else None,
                quote=sentence.text if sentence else text,
                start=sentence.start if sentence else None,
                end=sentence.end if sentence else None,
                lang=detect_language(record, text),
                source_kind=source_kind(record),
            )
            return {
                "action_key": action_key,
                "completed_at": timestamp,
                "record_id": str(record["id"]),
                "evidence": ev.to_dict(),
                "explicit_text": True,
            }
        return None


def analyze_record(record: dict[str, Any], vessels: list[dict[str, Any]] | None = None) -> RecordAnalysis:
    """Convenience wrapper for one record."""

    return NlpAnalyzer(vessels or []).analyze_record(record)


def analyze_case(case: dict[str, Any]) -> list[RecordAnalysis]:
    """Analyze all records in a case dictionary."""

    return NlpAnalyzer(case.get("vessels", [])).analyze_case(case)
