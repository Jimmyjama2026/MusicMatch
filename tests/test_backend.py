import csv
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from data.backend import FEATURES, FeedbackStore, MusicRecommender


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.csv_path = self.directory / "songs.csv"
        rows = [
            ["a", "First Song", "Artist One", .5, 100, .5, .5],
            ["b", "Close Song", "Artist Two", .51, 101, .52, .51],
            ["b", "Duplicate ID", "Artist Two", .51, 101, .52, .51],
            ["c", "Distant Song", "Artist Three", .95, 180, .95, .95],
            ["d", "Close Song", "Artist Two", .51, 101, .52, .51],
            ["bad", "Invalid Song", "Artist Four", .5, 0, .5, .5],
        ]
        with self.csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["track_id", "track_name", "artists", *FEATURES])
            writer.writerows(rows)
        self.engine = MusicRecommender(self.csv_path)

    def test_search_handles_blank_case_artist_partial_and_typo(self):
        self.assertEqual(self.engine.search("  "), [])
        for query in ("FIRST SONG", "First", "Artist One", "Frst Song"):
            self.assertEqual(self.engine.search(query)[0]["track_id"], "a")
        self.assertEqual(self.engine.search("unrelated zzzzz"), [])

    def test_rank_excludes_favorites_and_duplicate_recordings_and_bad_rows(self):
        results = self.engine.recommend(["a", "a"], limit=10)
        self.assertEqual([song["track_id"] for song in results], ["b", "c"])
        self.assertLess(results[0]["distance"], results[1]["distance"])
        for song in results:
            self.assertIn("favorites' average", song["reason"])
            self.assertIn("versus", song["reason"])
            self.assertTrue(song["model_version"])

    def test_combined_search_uses_artist_filter_and_supports_artist_only(self):
        self.assertEqual([song["track_id"] for song in self.engine.search("Song", "Two")], ["b"])
        self.assertEqual(self.engine.search("First Song", "Two"), [])
        self.assertEqual([song["track_id"] for song in self.engine.search("", "ARTIST THREE")], ["c"])
        self.assertEqual([song["track_id"] for song in self.engine.search("Frst Song", "One")], ["a"])
        self.assertEqual(self.engine.search("  ", "  "), [])
        self.assertEqual(self.engine.search("Artist One", title_only=True), [])
        self.assertEqual(self.engine.search("Frst Song", "Two"), [])

    def test_requires_valid_favorites_and_handles_all_selected(self):
        for favorites in ([], ["missing"]):
            with self.assertRaises(ValueError):
                self.engine.recommend(favorites)
        self.assertEqual(self.engine.recommend(["a", "b", "c"]), [])

    def test_feedback_reopens_upserts_and_retains_original_context(self):
        path = self.directory / "context.sqlite3"
        store = FeedbackStore(path)
        favorites = [self.engine.get_song("a")]
        recommendations = self.engine.recommend(["a"])
        batch = store.save_batch(favorites, recommendations)
        favorites[0]["track_name"] = "Later mutation"
        store.save_feedback(batch, "b", True)
        reopened = FeedbackStore(path)
        self.assertEqual(reopened.feedback_counts(), (1, 0))
        reopened.save_feedback(batch, "b", False)
        self.assertEqual(reopened.feedback_counts(), (0, 1))
        second_batch = reopened.save_batch([self.engine.get_song("c")], self.engine.recommend(["c"]))
        reopened.save_feedback(second_batch, "b", True)
        self.assertEqual(reopened.feedback_counts(), (1, 1))
        with closing(sqlite3.connect(path)) as connection:
            context = json.loads(connection.execute(
                "SELECT favorites_json FROM recommendation_batches WHERE batch_id=?", (batch,)
            ).fetchone()[0])
            song = json.loads(connection.execute(
                "SELECT song_json FROM recommendations WHERE batch_id=? AND track_id='b'", (batch,)
            ).fetchone()[0])
        self.assertEqual(context[0]["track_name"], "First Song")
        self.assertTrue(all(feature in context[0] and feature in song for feature in FEATURES))
        self.assertEqual(song["reason"], recommendations[0]["reason"])
        self.assertEqual(song["distance"], recommendations[0]["distance"])

    def test_feedback_rejects_non_boolean_or_unknown_recommendation(self):
        store = FeedbackStore(self.directory / "context.sqlite3")
        batch = store.save_batch([self.engine.get_song("a")], self.engine.recommend(["a"]))
        with self.assertRaises(ValueError):
            store.save_feedback(batch, "b", "yes")
        with self.assertRaises(sqlite3.IntegrityError):
            store.save_feedback(batch, "a", True)
        self.assertEqual(store.feedback_counts(), (0, 0))

    def test_profile_restore_isolation_active_and_safe_reset(self):
        path = self.directory / "profiles.sqlite3"
        store = FeedbackStore(path)
        favorites = [self.engine.get_song("a")]
        recommendations = self.engine.recommend(["a"])
        personal = store.save_batch(favorites, recommendations)
        test = store.save_batch(favorites, recommendations, "test")
        store.save_feedback(personal, "b", True)
        store.save_feedback(test, "b", False, "test")
        store.set_active_profile("test")
        reopened = FeedbackStore(path)
        self.assertEqual(reopened.get_active_profile(), "test")
        self.assertEqual(reopened.load_profile("personal")["recommendations"][0]["liked"], True)
        self.assertEqual(reopened.load_profile("test")["counts"], (0, 1))
        with self.assertRaises(ValueError):
            reopened.save_feedback(personal, "b", False, "test")
        with self.assertRaises(ValueError):
            reopened.reset_profile("personal")
        reopened.reset_profile("test")
        self.assertEqual(reopened.load_profile("test")["favorites"], [])
        self.assertEqual(reopened.training_feedback("test"), [])
        self.assertEqual(reopened.feedback_counts("personal"), (1, 0))
        reopened.save_favorites("personal", [self.engine.get_song("c")])
        self.assertIsNone(reopened.load_profile("personal")["batch_id"])
        self.assertEqual(reopened.feedback_counts("personal"), (1, 0))

    def test_saved_missing_catalog_favorite_and_feedback_adjustments(self):
        saved = self.engine.get_song("a")
        saved["track_id"] = "old-catalog-id"
        results = self.engine.recommend([saved["track_id"]], favorite_songs=[saved])
        self.assertNotIn("a", [song["track_id"] for song in results])
        base = {song["track_id"]: song for song in self.engine.recommend(["a"])}
        store = FeedbackStore(self.directory / "learning.sqlite3")
        batch = store.save_batch([self.engine.get_song("a")], list(base.values()))
        store.save_feedback(batch, "b", False)
        restored = FeedbackStore(store.path)
        no_results = self.engine.recommend(["a"], feedback=restored.training_feedback())
        b = next(song for song in no_results if song["track_id"] == "b")
        self.assertGreater(b["ranking_score"], base["b"]["ranking_score"])
        self.assertEqual(b["distance"], base["b"]["distance"])
        self.assertTrue(all(-.12000001 <= song["feedback_adjustment"] <= .12000001 for song in no_results))
        self.assertEqual(restored.training_feedback("test"), [])
        store.save_feedback(batch, "b", True)
        yes = next(song for song in self.engine.recommend(["a"], feedback=store.training_feedback()) if song["track_id"] == "b")
        self.assertLess(yes["ranking_score"], base["b"]["ranking_score"])

    def test_v1_migration_preserves_original_snapshots_votes_and_is_idempotent(self):
        path = self.directory / "legacy.sqlite3"
        favorite = self.engine.get_song("a")
        recommendation = self.engine.recommend(["a"])[0]
        with closing(sqlite3.connect(path)) as connection:
            connection.executescript("""
                CREATE TABLE recommendation_batches(batch_id TEXT PRIMARY KEY,created_at TEXT,model_version TEXT,favorites_json TEXT);
                CREATE TABLE recommendations(batch_id TEXT,track_id TEXT,song_json TEXT,PRIMARY KEY(batch_id,track_id));
                CREATE TABLE feedback(batch_id TEXT,track_id TEXT,liked INTEGER,updated_at TEXT,PRIMARY KEY(batch_id,track_id));
                PRAGMA user_version=1;
            """)
            connection.execute("INSERT INTO recommendation_batches VALUES (?,?,?,?)", ("legacy", "2026-01-01", "v1", json.dumps([favorite])))
            connection.execute("INSERT INTO recommendations VALUES (?,?,?)", ("legacy", "b", json.dumps(recommendation)))
            connection.execute("INSERT INTO feedback VALUES (?,?,?,?)", ("legacy", "b", 1, "2026-01-01"))
            connection.commit()
        for _ in range(2):
            store = FeedbackStore(path)
            state = store.load_profile("personal")
            self.assertEqual(state["favorites"], [favorite])
            self.assertEqual(state["batch_id"], "legacy")
            self.assertEqual(state["recommendations"][0]["reason"], recommendation["reason"])
            self.assertIs(state["recommendations"][0]["liked"], True)
            self.assertEqual(state["counts"], (1, 0))
            self.assertEqual(store.load_profile("test")["counts"], (0, 0))

    def test_history_filters_reasons_profile_ownership_and_clear_pointer(self):
        path = self.directory / "history.sqlite3"
        store = FeedbackStore(path)
        favorites = [self.engine.get_song("a")]
        recommendations = self.engine.recommend(["a"])
        batch = store.save_batch(favorites, recommendations)
        test_batch = store.save_batch(favorites, recommendations, "test")
        store.save_feedback(batch, "b", False, reason="Wrong mood")
        reopened = FeedbackStore(path)
        self.assertEqual(reopened.load_batch("personal", batch, "no")["recommendations"][0]["feedback_reason"], "Wrong mood")
        self.assertEqual([song["track_id"] for song in reopened.load_batch("personal", batch, "unrated")["recommendations"]], ["c"])
        self.assertEqual(reopened.list_history("personal", "yes"), [])
        self.assertEqual([item["batch_id"] for item in reopened.list_history("personal", "no")], [batch])
        self.assertEqual([item["batch_id"] for item in reopened.list_history("test")], [test_batch])
        with self.assertRaises(ValueError):
            reopened.load_batch("test", batch)
        reopened.save_favorites("personal", [self.engine.get_song("c")])
        reopened.load_batch("personal", batch)
        self.assertEqual(reopened.load_profile("personal")["favorites"][0]["track_id"], "c")
        reopened.save_feedback(batch, "b", True)
        self.assertIsNone(reopened.load_batch("personal", batch, "yes")["recommendations"][0]["feedback_reason"])
        reopened.clear_current_recommendations("personal")
        self.assertIsNone(FeedbackStore(path).load_profile("personal")["batch_id"])
        self.assertEqual(len(reopened.list_history("personal")), 1)
        reopened.reset_profile("test")
        self.assertEqual(reopened.list_history("test"), [])
        self.assertEqual(len(reopened.list_history("personal")), 1)

    def test_latest_votes_and_fresh_exclusions_exhaust_without_repeating(self):
        store = FeedbackStore(self.directory / "exclusions.sqlite3")
        favorites = [self.engine.get_song("a")]
        recommendations = self.engine.recommend(["a"])
        older = store.save_batch(favorites, recommendations)
        store.save_feedback(older, "b", False)
        self.assertEqual(store.recommendation_exclusions("personal"), {"b"})
        self.assertEqual([song["track_id"] for song in self.engine.recommend(["a"], exclude_ids=store.recommendation_exclusions("personal"))], ["c"])
        newer = store.save_batch(favorites, recommendations)
        self.assertEqual([item["batch_id"] for item in store.list_history("personal", limit=1, offset=0)], [newer])
        self.assertEqual([item["batch_id"] for item in store.list_history("personal", limit=1, offset=1)], [older])
        self.assertEqual(store.list_history("personal", offset=2), [])
        for invalid in (-1, True, "1"):
            with self.assertRaises(ValueError):
                store.list_history("personal", offset=invalid)
        store.save_feedback(newer, "b", True)
        self.assertEqual(store.recommendation_exclusions("personal"), set())
        self.assertEqual(store.recommendation_exclusions("test", fresh=True), set())
        self.assertEqual(self.engine.recommend(["a"], exclude_ids=store.recommendation_exclusions("personal", fresh=True)), [])
        store.clear_current_recommendations("personal")
        self.assertEqual(store.load_profile("personal")["recommendations"], [])
        self.assertEqual(len(store.list_history("personal")), 2)

    def test_v2_migration_adds_optional_reason_without_losing_votes(self):
        path = self.directory / "v2.sqlite3"
        store = FeedbackStore(path)
        batch = store.save_batch([self.engine.get_song("a")], self.engine.recommend(["a"]))
        store.save_feedback(batch, "b", False)
        with closing(sqlite3.connect(path)) as connection:
            connection.execute("ALTER TABLE feedback DROP COLUMN reason")
            connection.execute("PRAGMA user_version=2")
            connection.commit()
        for _ in range(2):
            reopened = FeedbackStore(path)
            saved = reopened.load_batch("personal", batch)["recommendations"][0]
            self.assertIs(saved["liked"], False)
            self.assertIsNone(saved["feedback_reason"])
            self.assertEqual(reopened.feedback_counts(), (0, 1))


if __name__ == "__main__":
    unittest.main()
