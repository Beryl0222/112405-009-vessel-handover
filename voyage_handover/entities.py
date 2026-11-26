"""Vessel registry and entity resolution.

Ship short names and callsigns can be reused.  Resolution therefore never
silently guesses when an alias refers to more than one registered vessel.
An explicit ``vessel_id`` on a record always takes precedence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .models import Evidence, VesselRef


def normalize_alias(value: str) -> str:
    return re.sub(r"[^a-z0-9一-鿿]+", "", value.lower())


def alias_pattern(alias: str) -> re.Pattern[str] | None:
    alias = alias.strip()
    if not alias:
        return None
    if re.search(r"[A-Za-z0-9]", alias) and not re.search(r"[一-鿿]", alias):
        # HAI-5 should also match "HAI 5", "HAI5", and "HAI_5".
        parts = [re.escape(p) for p in re.split(r"[^A-Za-z0-9]+", alias) if p]
        if not parts:
            return None
        body = r"[\W_]*?".join(parts)
        return re.compile(rf"(?<![A-Za-z0-9]){body}(?![A-Za-z0-9])", re.I)
    return re.compile(re.escape(alias), re.I)


@dataclass
class VesselRegistry:
    vessels: list[dict[str, Any]] = field(default_factory=list)
    default_vessel_id: str | None = None
    _alias_map: dict[str, list[str]] = field(default_factory=dict, repr=False)
    _patterns: list[tuple[re.Pattern[str], str, str]] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        self._alias_map = {}
        self._patterns = []
        for vessel in self.vessels:
            vid = str(vessel["id"])
            names = [vid]
            if vessel.get("callsign"):
                names.append(str(vessel["callsign"]))
            names.extend(str(a) for a in vessel.get("aliases", []))
            for name in names:
                norm = normalize_alias(name)
                if norm:
                    self._alias_map.setdefault(norm, []).append(vid)
                pat = alias_pattern(name)
                if pat is not None:
                    self._patterns.append((pat, vid, name))
        if self.default_vessel_id is None and len(self.vessels) == 1:
            self.default_vessel_id = str(self.vessels[0]["id"])

    def get(self, vessel_id: str) -> dict[str, Any] | None:
        for vessel in self.vessels:
            if str(vessel["id"]) == vessel_id:
                return vessel
        return None

    def _period_allows(self, vessel: dict[str, Any], timestamp: str | None) -> bool:
        if not timestamp:
            return True
        start = vessel.get("valid_from")
        end = vessel.get("valid_to")
        # ISO-ish strings sort lexicographically in the restricted profile.
        if start and timestamp < str(start):
            return False
        if end and timestamp >= str(end):
            return False
        return True

    def resolve(
        self,
        text: str,
        *,
        record_vessel_id: str | None = None,
        timestamp: str | None = None,
        evidence: Evidence | None = None,
    ) -> VesselRef:
        if record_vessel_id:
            vessel = self.get(str(record_vessel_id))
            if vessel is not None:
                return VesselRef(
                    vessel_id=str(record_vessel_id),
                    resolution="explicit_record_vessel_id",
                    evidence=evidence,
                )

        mentions: list[tuple[str, str, re.Match[str]]] = []
        seen_spans: set[tuple[int, int, str]] = set()
        for pat, vid, alias in self._patterns:
            for match in pat.finditer(text or ""):
                key = (match.start(), match.end(), vid)
                if key not in seen_spans:
                    seen_spans.add(key)
                    mentions.append((vid, alias, match))

        # Prefer a mention that is valid at the record timestamp.
        valid_ids: list[str] = []
        for vid, _alias, match in mentions:
            vessel = self.get(vid) or {}
            if self._period_allows(vessel, timestamp):
                if vid not in valid_ids:
                    valid_ids.append(vid)

        all_ids = sorted({vid for vid, _alias, _m in mentions})
        if len(valid_ids) == 1:
            vid, alias, match = next((v, a, m) for v, a, m in mentions if v == valid_ids[0])
            return VesselRef(
                vessel_id=vid,
                resolution="text_mention",
                mention=alias,
                candidates=all_ids if len(all_ids) > 1 else [],
                evidence=evidence,
            )
        if len(valid_ids) > 1:
            aliases = sorted({a for _v, a, _m in mentions})
            return VesselRef(
                vessel_id=None,
                resolution="ambiguous_reused_identifier",
                mention=aliases[0] if aliases else None,
                candidates=valid_ids,
                evidence=evidence,
            )
        if all_ids:
            # Mentions exist but all are outside their validity periods or the
            # timestamp cannot be matched.  Do not silently select one.
            aliases = sorted({a for _v, a, _m in mentions})
            return VesselRef(
                vessel_id=None,
                resolution="ambiguous_or_expired_identifier",
                mention=aliases[0] if aliases else None,
                candidates=all_ids,
                evidence=evidence,
            )

        if record_vessel_id and self.get(str(record_vessel_id)) is None:
            return VesselRef(
                vessel_id=None,
                resolution="unknown_explicit_vessel",
                candidates=[str(record_vessel_id)],
                evidence=evidence,
            )

        if self.default_vessel_id:
            return VesselRef(
                vessel_id=self.default_vessel_id,
                resolution="sole_case_vessel_context",
                evidence=evidence,
            )
        return VesselRef(resolution="unresolved", evidence=evidence)
