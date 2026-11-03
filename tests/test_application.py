import json
from pathlib import Path
import tempfile
import unittest

from data.application import ApplicationService
from data.backend import FeedbackStore
from data.title_language import TitleLanguageScreen


def english_screen(engine, path=None):
    screen = TitleLanguageScreen(path)
    for track_id in engine.songs:
        screen.set_override(track_id, "en")
    return screen


class Engine:
    def __init__(self):
        self.songs = {key: {"track_id": key, "track_name": key, "artists": "Artist " + key,
            "model_version": "service-test", "reason": "Test reason", "feature_version": "features-test",
            "source_fingerprint": "source-test", "neighborhood_context": {"anchor_id": "a"}}
            for key in ("a", "b", "c", "d", "e")}
        self.last = None

    def get_song(self, track_id):
        if track_id not in self.songs:
            raise ValueError("Missing song")
        return dict(self.songs[track_id])

    def search(self, title, artist="", title_only=True):
        return [dict(s) for s in self.songs.values() if title.casefold() in s["track_name"].casefold()][:10]

    def recommend(self, ids, favorite_songs=None, feedback=None, exclude_ids=None, known_artist_names=None,
                  known_artist_ids=None, steering="same", pairwise_feedback=None, candidate_filter=None):
        self.last = dict(ids=ids, favorites=favorite_songs, feedback=feedback, excluded=set(exclude_ids or ()),
                         known_artist_names=set(known_artist_names or ()),
                         known_artist_ids=set(known_artist_ids or ()), steering=steering, pairs=pairwise_feedback)
        return [dict(s) for s in self.songs.values() if s["track_id"] not in self.last["excluded"] and s["track_id"] not in ids
                and (candidate_filter is None or candidate_filter(s))][:2]


class ApplicationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = FeedbackStore(Path(self.tmp.name) / "service.sqlite3")
        self.engine = Engine()
        self.service = ApplicationService(self.engine, self.store, english_screen(
            self.engine, self.store.path.parent / "sources" / "title_language.sqlite3"))
        self.service.initialize()

    def test_request_steering_resets_and_cannot_be_applied_globally(self):
        self.service.add_favorite("a")
        with self.assertRaises(ValueError):
            self.service.recommend(steering="faster")
        focused = self.service.more_like_this("a", steering="faster")
        self.assertEqual(self.engine.last["steering"], "faster")
        self.assertEqual(focused["favorites"][0]["track_id"], "a")
        self.service.recommend()
        self.assertEqual(self.engine.last["steering"], "same")
        with self.assertRaises(ValueError):
            self.service.more_like_this("a", steering="invalid")

    def test_title_correction_changes_future_selection_not_saved_history(self):
        self.service.add_favorite("a")
        first = self.service.recommend()
        self.assertEqual([s["track_id"] for s in first["recommendations"]], ["b", "c"])
        corrected = self.service.set_title_language("b", "other")
        self.assertNotIn("b", [s["track_id"] for s in corrected["recommendations"]])
        following = self.service.recommend()
        self.assertNotIn("b", [s["track_id"] for s in following["recommendations"]])
        historical = self.service.load_history(first["batch_id"])
        self.assertEqual(historical["recommendations"][0]["title_language"]["status"], "allowed")
        self.service.set_title_language("b", "en")
        again = self.service.recommend()
        self.assertEqual(again["recommendations"][0]["title_language"]["source"], "override")

    def test_comparisons_change_future_requests_without_writing_yes_no(self):
        for key in ("b", "c"):
            self.engine.songs[key].update(matched_anchor=dict(self.engine.songs["a"]),
                distance=.02, ranking_score=.02)
        self.service.add_favorite("a")
        first = self.service.recommend()
        ident = first["comparison"]["id"]
        voted = self.service.choose_comparison(ident, "a")
        self.assertEqual(voted["counts"], [0, 0])
        self.assertEqual(voted["comparison_stats"]["active_count"], 1)
        self.assertEqual(self.store.training_feedback(), [])
        self.service.recommend()
        self.assertEqual(len(self.engine.last["pairs"]), 1)
        self.service.undo_comparison(ident)
        self.assertEqual(self.store.training_comparisons("personal"), [])
        self.service.choose_comparison(ident, "b")
        self.service.switch_profile("test")
        with self.assertRaises(ValueError):
            self.service.choose_comparison(ident, "a")
        self.service.reset_comparisons()
        self.assertEqual(len(self.store.training_comparisons("personal")), 1)
        self.service.switch_profile("personal")
        self.service.reset_comparisons()
        self.assertEqual(self.service.current_state()["favorites"][0]["track_id"], "a")

    def test_search_favorites_recommend_feedback_context_and_reopen(self):
        self.assertEqual(self.service.search("a")[0]["track_id"], "a")
        self.service.add_favorite("a")
        state = self.service.recommend()
        self.assertTrue(state["batch_id"])
        song = state["recommendations"][0]
        state = self.service.rate(state["batch_id"], song["track_id"], True)
        json.dumps(state, allow_nan=False)
        saved = self.store.training_feedback()[0]
        self.assertEqual(saved["feature_version"], "features-test")
        self.assertEqual(saved["neighborhood_context"], {"anchor_id": "a"})
        reopened = ApplicationService(self.engine, FeedbackStore(self.store.path)).initialize()
        self.assertEqual(reopened["counts"], [1, 0])
        self.assertEqual(reopened["favorites"][0]["track_id"], "a")

    def test_profile_history_ownership_and_reset_safety(self):
        self.service.add_favorite("a")
        personal = self.service.recommend()
        self.service.switch_profile("test")
        self.assertEqual(self.service.current_state()["favorites"], [])
        with self.assertRaises(ValueError):
            self.service.load_history(personal["batch_id"])
        self.service.add_favorite("b")
        self.service.recommend()
        self.assertEqual(self.service.reset_test()["favorites"], [])
        restored = self.service.switch_profile("personal")
        self.assertEqual(restored["favorites"][0]["track_id"], "a")
        with self.assertRaises(ValueError):
            self.service.reset_test()

    def test_focus_preserves_active_likes_and_stores_actual_focus_context(self):
        self.engine.songs["b"]["id_artists"] = ["B" * 22]
        self.engine.songs["c"]["id_artists"] = ["C" * 22]
        self.service.add_favorite("a")
        self.service.add_favorite("b")
        first = self.service.recommend()
        self.service.rate(first["batch_id"], "c", True)
        focused = self.service.more_like_this("a")
        self.assertEqual({s["track_id"] for s in focused["favorites"]}, {"a", "b"})
        batch = self.service.load_history(focused["batch_id"])
        self.assertEqual([s["track_id"] for s in batch["favorites"]], ["a"])
        self.assertTrue({"a", "b", "c"}.issubset(self.engine.last["excluded"]))
        self.assertEqual(self.engine.last["feedback"], [])
        self.assertTrue({"artist a", "artist b", "artist c"}.issubset(self.engine.last["known_artist_names"]))
        self.assertTrue({"spotify:" + "B" * 22, "spotify:" + "C" * 22}.issubset(
            self.engine.last["known_artist_ids"]))
        self.assertTrue(all(s["focused_on"]["track_id"] == "a" for s in batch["recommendations"]))

    def test_empty_fresh_result_clears_current_but_retains_history(self):
        for key in ("a", "b", "c", "d"):
            self.service.add_favorite(key)
        first = self.service.recommend()
        result = self.service.recommend(fresh=True)
        self.assertEqual(result["recommendations"], [])
        self.assertIsNone(result["batch_id"])
        self.assertEqual(self.service.list_history()[0]["batch_id"], first["batch_id"])

    def test_history_rating_does_not_change_current_batch_or_likes(self):
        self.service.add_favorite("a")
        first = self.service.recommend()
        second = self.service.recommend(fresh=True)
        state = self.service.rate(first["batch_id"], first["recommendations"][0]["track_id"], False, "Already know it")
        self.assertEqual(state["batch_id"], second["batch_id"])
        self.assertEqual(state["favorites"][0]["track_id"], "a")
        self.assertEqual(state["rated_batch"]["recommendations"][0]["feedback_reason"], "Already know it")

    def test_saved_song_absent_from_catalog_keeps_its_snapshot(self):
        saved = dict(self.engine.get_song("a"), track_id="old-id")
        self.store.save_favorites("personal", [saved])
        state = self.service.recommend()
        self.assertEqual(state["favorites"], [saved])
        self.assertEqual(self.engine.last["favorites"], [saved])
