import copy
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from data.backend import FeedbackStore


def anchor():
    return dict(track_id="seed", track_name="Liked seed", artists="Seed Artist", tempo=100,
        energy=.5, valence=.3, danceability=.6, acousticness=.1, instrumentalness=.1,
        speechiness=.05, loudness=-10, liveness=.1, duration_ms=180000,
        key=0, mode=1, time_signature=4)


def candidates(prefix=""):
    return [dict(anchor(), track_id=prefix + name, track_name=prefix + name, artists="Artist " + name,
        distance=.02 + index * .001, ranking_score=.02 + index * .001,
        matched_anchor=anchor(), feature_version="test-v1", source_fingerprint="test-source",
        neighborhood_visual={"nested": {"do_not_copy": True}})
        for index, name in enumerate(("A", "B"))]


class ComparisonStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "feedback.sqlite3"
        self.store = FeedbackStore(self.path)
        self.batch = self.store.save_batch([anchor()], candidates())
        self.ident = self.store.offer_comparison("personal", self.batch)

    def test_offer_is_stable_minimal_and_does_not_write_ratings(self):
        self.assertTrue(self.ident)
        self.assertEqual(self.ident, self.store.offer_comparison("personal", self.batch))
        state = self.store.comparison_state("personal", self.batch)
        self.assertEqual(state["comparison"]["anchor"]["track_id"], "seed")
        self.assertNotIn("neighborhood_visual", state["comparison"]["a"])
        self.assertNotIn("matched_anchor", state["comparison"]["a"])
        self.assertEqual(self.store.training_feedback(), [])
        json.dumps(state, allow_nan=False)

    def test_latest_choice_undo_equal_and_skip_are_separate_from_dislikes(self):
        self.store.choose_comparison("personal", self.ident, "a")
        first = self.store.training_comparisons("personal")[0]
        self.store.choose_comparison("personal", self.ident, "b")
        latest = self.store.training_comparisons("personal")
        self.assertEqual(len(latest), 1)
        self.assertEqual(first["winner"], latest[0]["loser"])
        self.assertEqual(self.store.feedback_counts(), (0, 0))
        self.assertEqual(self.store.recommendation_exclusions("personal"), set())
        self.store.undo_comparison("personal", self.ident)
        self.assertEqual(self.store.training_comparisons("personal"), [])
        self.assertEqual(self.store.comparison_state("personal", self.batch)["comparison"]["id"], self.ident)
        for choice in ("equal", "skip"):
            self.store.choose_comparison("personal", self.ident, choice)
            self.assertEqual(self.store.training_comparisons("personal"), [])

    def test_profile_ownership_and_validation(self):
        for action in (lambda: self.store.choose_comparison("test", self.ident, "a"),
                       lambda: self.store.undo_comparison("test", self.ident),
                       lambda: self.store.choose_comparison("personal", self.ident, "bad"),
                       lambda: self.store.offer_comparison("test", self.batch)):
            with self.assertRaises(ValueError):
                action()
        self.assertEqual(self.store.training_comparisons("test"), [])

    def test_seen_pair_is_not_reoffered_across_batches_or_alias_ids(self):
        songs = candidates()
        for song in songs:
            song["track_id"] += "-alias"
        another = self.store.save_batch([anchor()], songs)
        self.assertIsNone(self.store.offer_comparison("personal", another))
        # Different score contexts/anchors do not manufacture a repeat pair.
        self.assertEqual(self.store.comparison_state("personal", another)["comparison"], None)

    def test_test_reset_and_comparison_reset_preserve_other_feedback(self):
        self.store.choose_comparison("personal", self.ident, "a")
        test_batch = self.store.save_batch([anchor()], candidates("test"), "test")
        test_id = self.store.offer_comparison("test", test_batch)
        self.store.choose_comparison("test", test_id, "b")
        self.store.save_feedback(self.batch, "A", True)
        self.store.reset_profile("test")
        self.assertEqual(len(self.store.training_comparisons("personal")), 1)
        self.store.reset_comparisons("personal")
        self.assertEqual(self.store.training_comparisons("personal"), [])
        self.assertEqual(len(self.store.training_feedback()), 1)
        self.assertEqual(len(self.store.load_profile("personal")["recommendations"]), 2)

    def test_schema_three_migration_preserves_saved_batch(self):
        before = copy.deepcopy(self.store.load_profile("personal"))
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute("DROP TABLE pairwise_comparisons")
            connection.execute("PRAGMA user_version=3")
            connection.commit()
        reopened = FeedbackStore(self.path)
        self.assertEqual(reopened.load_profile("personal"), before)
        self.assertEqual(reopened.training_comparisons("personal"), [])

    def test_offers_require_shared_real_anchor_and_comparable_quality(self):
        rows = candidates("new")
        rows[1]["matched_anchor"]["track_id"] = "another"
        rows[1]["matched_anchor"]["track_name"] = "Different seed"
        other = self.store.save_batch([anchor()], rows)
        self.assertIsNone(self.store.offer_comparison("personal", other))
        rows = candidates("distant")
        rows[1]["ranking_score"] = .5
        other = self.store.save_batch([anchor()], rows)
        self.assertIsNone(self.store.offer_comparison("personal", other))
