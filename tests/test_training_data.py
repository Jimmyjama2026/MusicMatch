from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from data.backend import FeedbackStore, FEEDBACK_REASONS
from data.training_data import load_feedback_events, load_training_records, load_comparison_records
from tests.test_comparisons import anchor, candidates


class TrainingDataTests(unittest.TestCase):
    def test_favorites_count_as_yes_without_self_anchor_or_duplicate_votes(self):
        favorite = dict(candidates()[0])
        self.store.save_favorites("personal", [favorite])
        rows = load_training_records(self.path, "personal")
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["liked"])
        self.assertEqual(rows[0]["judgment_source"], "favorite")
        self.assertIsNone(rows[0]["anchor"])
        self.store.save_feedback(self.batch, "A", True)
        rows = load_training_records(self.path, "personal")
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["liked"])
        self.store.save_feedback(self.batch, "A", False, reason="Not my style")
        self.assertFalse(load_training_records(self.path, "personal")[0]["liked"])

    def test_favorite_removal_is_not_a_negative_and_profiles_stay_isolated(self):
        self.store.save_favorites("personal", [dict(candidates()[0])])
        self.assertEqual(load_training_records(self.path, "test"), [])
        self.assertEqual(len(load_training_records(self.path, "personal")), 1)
        self.store.save_favorites("personal", [])
        self.assertEqual(load_training_records(self.path, "personal"), [])

    def test_genre_evidence_survives_feedback_export_as_frozen_context(self):
        rows = candidates()
        rows[0]["artist_genre_evidence"] = {"level": "artist", "genres": ["country"], "source": "fixture"}
        rows[0]["matched_anchor"]["artist_genre_evidence"] = {"level": "artist", "genres": ["country"]}
        batch = self.store.save_batch([rows[0]["matched_anchor"]], rows)
        self.store.save_feedback(batch, "A", True)
        exported = load_training_records(self.path, "personal", include_favorites=False)
        self.assertEqual(exported[0]["song"]["artist_genre_evidence"]["genres"], ["country"])
        self.assertEqual(exported[0]["anchor"]["artist_genre_evidence"]["genres"], ["country"])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "feedback.sqlite3"
        self.store = FeedbackStore(self.path)
        self.batch = self.store.save_batch([anchor()], candidates())

    def test_all_no_reasons_retained_in_events_and_latest_policy(self):
        for reason in FEEDBACK_REASONS:
            self.store.save_feedback(self.batch, "A", False, reason=reason)
        events = load_feedback_events(self.path, "personal")
        self.assertEqual([e["reason"] for e in events], list(FEEDBACK_REASONS))
        self.assertEqual(len({e["event_id"] for e in events}), len(FEEDBACK_REASONS))
        self.assertTrue(all(e["judged_at"].endswith("Z") for e in events))
        rows = load_training_records(self.path, "personal", include_favorites=False)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["reason"], "Other")
        self.assertNotIn("ranking_score", rows[0]["song"])
        self.assertEqual(rows[0]["heuristic_score"], .02)
        self.assertEqual(rows[0]["anchor"], anchor())
        self.assertEqual(load_training_records(self.path, "test", include_favorites=False), [])
        for reason in ("Too slow", "Too fast", "Already know it"):
            self.store.save_feedback(self.batch, "A", False, reason=reason)
            self.assertEqual(load_training_records(self.path, "personal", include_favorites=False), [])

    def test_latest_alias_correction_wins_and_never_resurrects_old_yes(self):
        self.store.save_feedback(self.batch, "A", True)
        alias = dict(candidates()[0], track_id="alias", track_name=" a ")
        second = self.store.save_batch([anchor()], [alias])
        self.store.save_feedback(second, "alias", False, reason="Not my style")
        rows = load_training_records(self.path, "personal", include_favorites=False)
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["liked"])
        self.assertEqual(rows[0]["song"]["track_id"], "alias")
        self.store.save_feedback(second, "alias", False, reason="Too fast")
        self.assertEqual(load_training_records(self.path, "personal", include_favorites=False), [])
        self.assertEqual(len(load_feedback_events(self.path, "personal")), 3)

    def test_missing_and_self_anchors_not_training_examples(self):
        song = dict(candidates()[0])
        song.pop("matched_anchor")
        batch = self.store.save_batch([anchor()], [song])
        self.store.save_feedback(batch, "A", True)
        self.assertEqual(load_training_records(self.path, "personal", include_favorites=False), [])
        song["matched_anchor"] = dict(song)
        batch = self.store.save_batch([anchor()], [song])
        self.store.save_feedback(batch, "A", True)
        self.assertEqual(load_training_records(self.path, "personal", include_favorites=False), [])

    def test_export_read_only_and_migration_preserves_vote_time(self):
        self.store.save_feedback(self.batch, "A", False, reason="Wrong mood")
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute("DROP TABLE feedback_events")
            connection.execute("UPDATE feedback SET updated_at='2020-01-01T02:03:04.000Z'")
            connection.execute("PRAGMA user_version=4")
            connection.commit()
        before = self.path.read_bytes()
        old = load_training_records(self.path, "personal", include_favorites=False)
        self.assertEqual(before, self.path.read_bytes())
        self.assertEqual(old[0]["judged_at"], "2020-01-01T02:03:04.000Z")
        FeedbackStore(self.path)
        rows = load_training_records(self.path, "personal", include_favorites=False)
        self.assertEqual(rows[0]["judged_at"], old[0]["judged_at"])
        self.assertEqual(rows[0]["reason"], "Wrong mood")
        before = self.path.read_bytes()
        load_training_records(self.path, "personal", include_favorites=False)
        self.assertEqual(before, self.path.read_bytes())

    def test_comparison_events_undo_and_reset(self):
        ident = self.store.offer_comparison("personal", self.batch)
        self.store.choose_comparison("personal", ident, "a")
        record = load_comparison_records(self.path, "personal")[0]
        self.assertEqual(record["winner"]["track_id"], "A")
        self.assertEqual(load_comparison_records(self.path, "test"), [])
        self.store.undo_comparison("personal", ident)
        self.assertEqual(load_comparison_records(self.path, "personal"), [])
        for choice in ("equal", "skip"):
            self.store.choose_comparison("personal", ident, choice)
            self.assertEqual(load_comparison_records(self.path, "personal"), [])
        with closing(sqlite3.connect(self.path)) as connection:
            self.assertEqual(connection.execute("SELECT action FROM comparison_events ORDER BY sequence").fetchall(),
                             [("choose",), ("undo",), ("choose",), ("choose",)])
        self.store.reset_comparisons("personal")
        with closing(sqlite3.connect(self.path)) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM comparison_events").fetchone()[0], 0)

    def test_test_reset_removes_its_events_only(self):
        self.store.save_feedback(self.batch, "A", True)
        batch = self.store.save_batch([anchor()], candidates(), "test")
        self.store.save_feedback(batch, "A", False, "test", "Not my style")
        self.store.save_favorites("test", [anchor()])
        self.store.reset_profile("test")
        self.assertEqual(load_feedback_events(self.path, "test"), [])
        self.assertEqual(len(load_feedback_events(self.path, "personal")), 1)

    def test_actual_vote_time_and_context_survive_favorite_changes(self):
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute("UPDATE recommendation_batches SET created_at='2000-01-01T00:00:00.000Z'")
            connection.commit()
        self.store.save_feedback(self.batch, "A", False, reason="Not my style")
        self.store.save_favorites("personal", [])
        record = load_training_records(self.path, "personal", include_favorites=False)[0]
        self.assertGreater(record["judged_at"], record["shown_at"])
        self.assertEqual(record["favorites"], [anchor()])
        self.assertEqual(record["anchor"], anchor())
        with self.assertRaises(ValueError):
            self.store.save_feedback(self.batch, "B", True, profile_id="test")
        self.assertEqual(len(load_feedback_events(self.path, "personal")), 1)
        self.assertEqual(load_feedback_events(self.path, "test"), [])

    def test_comparison_export_is_not_live_32_item_window(self):
        for number in range(35):
            batch = self.store.save_batch([anchor()], candidates(str(number)))
            ident = self.store.offer_comparison("personal", batch)
            self.store.choose_comparison("personal", ident, "a")
        self.assertEqual(len(self.store.training_comparisons("personal")), 32)
        self.assertEqual(len(load_comparison_records(self.path, "personal")), 35)

    def test_baseline_score_is_finite_audit_metadata_only(self):
        for value in (None, "bad", "nan", "inf", "-inf"):
            song = dict(candidates()[0], ranking_score=value)
            batch = self.store.save_batch([anchor()], [song])
            self.store.save_feedback(batch, "A", True)
            record = load_training_records(self.path, "personal", include_favorites=False)[0]
            self.assertIsNone(record["heuristic_score"])
            self.assertNotIn("ranking_score", record["song"])
            self.assertNotIn("heuristic_score", record["song"])
            self.assertNotIn("heuristic_score", record["anchor"])

