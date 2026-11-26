from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from voyage_handover import (  # noqa: E402
    HandoverStore,
    ImmutableRecordError,
    ImmutableTrackError,
)
from voyage_handover.cli import main as cli_main  # noqa: E402

CASE_PATH = ROOT / "data" / "case.json"


def load_case() -> dict:
    return json.loads(CASE_PATH.read_text(encoding="utf-8"))


class BaselineScenarioTest(unittest.TestCase):
    def setUp(self) -> None:
        self.case = load_case()
        self.store = HandoverStore.from_case(self.case)

    def test_captain_order_shore_suggestion_and_clearance_are_distinct(self) -> None:
        cards = {card.action_key: card for card in self.store.action_cards.values()}
        self.assertIn("shift_anchor", cards)
        anchor = cards["shift_anchor"]

        self.assertEqual("blocked", anchor.status)
        self.assertIn("weather.wind_east", anchor.blocker_keys)
        self.assertIn("authorization.shore_clearance", anchor.blocker_keys)
        self.assertEqual("met", anchor.conditions["authority.captain_order"].state)
        self.assertEqual("absent", anchor.conditions["authorization.shore_clearance"].state)
        self.assertEqual("required", anchor.conditions["weather.wind_east"].state)

        self.assertTrue(anchor.order_claim_ids)
        self.assertTrue(anchor.suggestion_claim_ids)
        suggestion = self.store.claims[anchor.suggestion_claim_ids[0]]
        self.assertEqual("suggestion", suggestion.speech_act)
        self.assertEqual("shore_station", suggestion.speaker_role)
        self.assertNotIn("authority.captain_order", suggestion.condition_keys)

        maintain = cards["maintain_position"]
        self.assertEqual("in_force", maintain.status)
        self.assertFalse(maintain.blocker_keys)

    def test_equipment_intermittence_is_reported_but_not_erased(self) -> None:
        equipment = [o for o in self.store.observations.values() if o.category == "equipment"]
        self.assertEqual(1, len(equipment))
        obs = equipment[0]
        self.assertEqual("intermittent", obs.state)
        self.assertIsNone(obs.temporal_relation)
        self.assertTrue(obs.attributes["timing_unknown"])
        self.assertIn("每隔几分钟", obs.value or "")

        card = next(c for c in self.store.action_cards.values() if c.action_key == "shift_anchor")
        self.assertIn(obs.id, card.advisory_keys)

    def test_every_judgement_points_to_original_text(self) -> None:
        records = {r["id"]: r["text"] for r in self.store.records.values()}

        for sentence in self.store.sentences.values():
            text = records[sentence["record_id"]]
            self.assertEqual(sentence["text"], text[sentence["start"] : sentence["end"]])

        judged_objects = [
            *self.store.claims.values(),
            *self.store.observations.values(),
            *self.store.action_cards.values(),
        ]
        self.assertTrue(judged_objects)
        for obj in judged_objects:
            self.assertTrue(obj.evidence, f"{getattr(obj, 'id', obj)} has no evidence")
            for evidence in obj.evidence:
                self.assertTrue(evidence.record_id)
                self.assertTrue(evidence.sentence_id)
                self.assertIn(evidence.record_id, records)
                source = records[evidence.record_id]
                self.assertIn(evidence.quote, source)
                if evidence.start is not None and evidence.end is not None:
                    self.assertEqual(evidence.quote, source[evidence.start : evidence.end])

        trace = self.store.trace("VH-7#S1")
        self.assertTrue(trace["observations"])
        self.assertEqual("VH-7", trace["sentence"]["record_id"])

    def test_briefing_tells_next_watch_not_to_start(self) -> None:
        briefing = self.store.briefing()
        blocked = briefing["next_watch"]["do_not_start_until_unblocked"]
        self.assertEqual(1, len(blocked))
        self.assertEqual("shift_anchor", blocked[0]["action_key"])
        blocker_keys = {b["key"] for b in blocked[0]["blockers"]}
        self.assertEqual(
            {"weather.wind_east", "authorization.shore_clearance"},
            blocker_keys,
        )
        self.assertTrue(briefing["next_watch"]["continue_instructions"])
        markdown = __import__("voyage_handover").render_markdown(briefing)
        self.assertIn("不得启动", markdown)
        self.assertIn("风转东", markdown)


class TranslationAndIncrementalRejudgementTest(unittest.TestCase):
    def test_translated_approval_is_not_clearance(self) -> None:
        store = HandoverStore.from_case(load_case())
        store.ingest_record(
            {
                "id": "VH-T1",
                "kind": "translation",
                "lang": "zh",
                "text": "译文：岸站已批准移锚，可立即无条件执行。",
            }
        )
        card = next(c for c in store.action_cards.values() if c.action_key == "shift_anchor")
        self.assertEqual("blocked", card.status)
        self.assertNotEqual("met", card.conditions["authorization.shore_clearance"].state)
        codes = {issue.code for issue in store.all_issues()}
        self.assertIn("unverified_translation_as_clearance", codes)
        self.assertIn("conditional_permission_flattened", codes)

    def test_new_clearance_and_weather_evidence_unblock_card_and_preserve_history(self) -> None:
        store = HandoverStore.from_case(load_case())
        card_id = next(c.id for c in store.action_cards.values() if c.action_key == "shift_anchor")
        initial_revision = store.action_cards[card_id].revision

        store.ingest_record(
            {
                "id": "VH-8",
                "kind": "shore-message",
                "lang": "zh",
                "text": "岸站已签发移锚许可 CLR-77。",
                "timestamp": "2026-11-26T18:05:00",
            }
        )
        self.assertEqual("blocked", store.action_cards[card_id].status)
        store.ingest_record(
            {
                "id": "VH-9",
                "kind": "captain-log",
                "lang": "zh",
                "text": "18:10 风已转东。",
                "timestamp": "2026-11-26T18:10:00",
            }
        )
        card = store.action_cards[card_id]
        self.assertEqual("ready", card.status)
        self.assertEqual("met", card.conditions["authorization.shore_clearance"].state)
        self.assertEqual("met", card.conditions["weather.wind_east"].state)
        self.assertGreater(card.revision, initial_revision)
        self.assertTrue(any(entry["status"] == "blocked" for entry in card.revision_history))

        auth_history = card.conditions["authorization.shore_clearance"].detail["state_history"]
        states = {item["state"] for item in auth_history if item.get("authoritative")}
        self.assertIn("absent", states)
        self.assertIn("met", states)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "store.json"
            store.save(path)
            reloaded = HandoverStore.load(path)
            self.assertEqual("ready", reloaded.action_cards[card_id].status)
            self.assertTrue(reloaded.verify_track_chain())


class TimingAndImmutabilityTest(unittest.TestCase):
    def test_new_log_clarifies_before_anchor_move(self) -> None:
        store = HandoverStore.from_case(load_case())
        store.ingest_record(
            {
                "id": "VH-8",
                "kind": "equipment-note",
                "lang": "zh",
                "text": "设备员澄清：定位间歇发生在移锚之前。",
            }
        )
        observations = [o for o in store.observations.values() if o.category == "equipment"]
        clarified = next(o for o in observations if o.id.startswith("OB-VH-8"))
        self.assertEqual("before", clarified.temporal_relation)
        self.assertTrue(clarified.clarification)

        card = next(c for c in store.action_cards.values() if c.action_key == "shift_anchor")
        self.assertTrue(any(event.relation == "before" for event in card.timeline))

    def test_temporal_reference_is_not_a_new_command(self) -> None:
        store = HandoverStore(vessels=[{"id": "V-1"}])
        store.ingest_record(
            {
                "id": "TIME-1",
                "kind": "equipment-note",
                "lang": "en",
                "text": "The GNSS outage was before the anchor move.",
            }
        )
        card = next(iter(store.action_cards.values()))
        self.assertEqual([], card.order_claim_ids)
        self.assertNotEqual("met", card.conditions["authority.captain_order"].state)
        self.assertTrue(card.report_claim_ids)

    def test_after_relation_on_open_card_warns_without_completing(self) -> None:
        store = HandoverStore.from_case(load_case())
        store.ingest_record(
            {
                "id": "VH-9",
                "kind": "equipment-note",
                "text": "设备员查明，定位间歇发生在移锚之后。",
            }
        )
        card = next(c for c in store.action_cards.values() if c.action_key == "shift_anchor")
        self.assertFalse(card.completed)
        self.assertEqual("blocked", card.status)
        self.assertIn(
            "after_reference_without_completion_record",
            {i.code for i in store.all_issues()},
        )

    def test_completed_track_is_immutable_but_new_timing_is_linked(self) -> None:
        store = HandoverStore.from_case(load_case())
        track = {
            "id": "TRACK-1820",
            "kind": "track-point",
            "timestamp": "2026-11-26T18:20:00",
            "lat": 30.12,
            "lon": 122.45,
            "action_key": "shift_anchor",
            "event": "anchor_move",
            "completed": True,
        }
        store.ingest_track_record(track)
        store.ingest_record(
            {
                "id": "VH-10",
                "kind": "equipment-note",
                "text": "补充：定位间歇发生在移锚之后。",
            }
        )

        card = next(c for c in store.action_cards.values() if c.action_key == "shift_anchor")
        self.assertEqual("completed", card.status)
        self.assertTrue(card.immutable)
        self.assertTrue(any(event.relation == "after" for event in card.timeline))
        self.assertTrue(store.verify_track_chain())

        with self.assertRaises(ImmutableTrackError):
            store.ingest_track_record({**track, "lat": 30.99})
        with self.assertRaises(ImmutableTrackError):
            store.amend_track_record("TRACK-1820", lat=31.0)
        with self.assertRaises(ImmutableRecordError):
            store.ingest_record({**load_case()["records"][0], "text": "改写后的旧记录"})


class VesselReuseAndShorthandTest(unittest.TestCase):
    def test_reused_callsign_is_ambiguous_without_context(self) -> None:
        vessels = [
            {"id": "V-OLD", "callsign": "REUSE-1"},
            {"id": "V-NEW", "callsign": "REUSE-1"},
        ]
        store = HandoverStore(vessels=vessels)
        store.ingest_record(
            {"id": "R-1", "kind": "radio-excerpt", "text": "REUSE-1 MOV ANC AFTER; CLR NIL."}
        )
        card = next(iter(store.action_cards.values()))
        self.assertEqual("ambiguous", card.status)
        self.assertEqual(["V-NEW", "V-OLD"], card.vessel_candidates)
        self.assertIn("ambiguous_vessel_identifier", {i.code for i in store.all_issues()})

        explicit = HandoverStore(vessels=vessels)
        explicit.ingest_record(
            {"id": "R-2", "vessel_id": "V-NEW", "kind": "radio-excerpt", "text": "MOV ANC"}
        )
        explicit_card = next(iter(explicit.action_cards.values()))
        self.assertEqual("V-NEW", explicit_card.vessel_id)
        self.assertNotEqual("ambiguous", explicit_card.status)

    def test_temporal_registry_resolves_reused_callsign(self) -> None:
        vessels = [
            {"id": "V-OLD", "callsign": "HAI-5", "valid_to": "2020-01-01"},
            {"id": "V-NEW", "callsign": "HAI-5", "valid_from": "2020-01-01"},
        ]
        store = HandoverStore(vessels=vessels)
        analysis = store.ingest_record(
            {
                "id": "R-3",
                "kind": "radio-log",
                "timestamp": "2026-11-26T10:00:00",
                "text": "HAI-5 POSN INT",
            }
        )
        self.assertEqual("V-NEW", analysis.vessel.vessel_id)
        self.assertEqual("text_mention", analysis.vessel.resolution)

    def test_shorthand_captain_condition_and_nil_clearance(self) -> None:
        store = HandoverStore(vessels=[{"id": "V-1", "aliases": []}])
        store.ingest_record(
            {
                "id": "RADIO-1",
                "kind": "radio-excerpt",
                "lang": "en",
                "text": "CAPT: WND E 1800, MOV ANC AFTER; CLR NIL.",
            }
        )
        card = next(c for c in store.action_cards.values() if c.action_key == "shift_anchor")
        self.assertEqual("blocked", card.status)
        self.assertIn("weather.wind_east", card.blocker_keys)
        self.assertIn("authorization.shore_clearance", card.blocker_keys)
        captain_claim = next(self.store_claims(store, "order"))
        self.assertEqual("captain", captain_claim.speaker_role)

    @staticmethod
    def store_claims(store: HandoverStore, kind: str):
        return (c for c in store.claims.values() if c.kind == kind)


class CliTest(unittest.TestCase):
    def test_build_cli_writes_store_and_brief(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store_path = root / "store.json"
            brief_path = root / "brief.md"
            code = cli_main(
                [
                    "build",
                    str(CASE_PATH),
                    "--store",
                    str(store_path),
                    "--brief",
                    str(brief_path),
                ]
            )
            self.assertEqual(0, code)
            data = json.loads(store_path.read_text(encoding="utf-8"))
            self.assertIn("action_cards", data)
            self.assertIn("移锚", brief_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
