import tempfile
from pathlib import Path
import unittest
import numpy as np
import pandas as pd

from data.backend import MusicRecommender as Baseline
from data.neighborhoods import MusicRecommender, MODEL_VERSION, ARTIST_MATCH_BONUS


def song(identifier, tempo, acoustic, speech, artist=None):
    return dict(track_id=identifier, track_name=identifier, artists=artist or identifier,
                tempo=tempo, acousticness=acoustic, speechiness=speech, energy=.5,
                danceability=.5, valence=.5, instrumentalness=.1, loudness=-10,
                liveness=.1, duration_ms=200000, key=0, mode=1, time_signature=4)


class NeighborhoodTests(unittest.TestCase):
    def test_rejected_shortlist_backfills_from_remaining_eligible_catalog(self):
        rows = [song("seed", 100, .2, .1)] + [song(f"row{i}", 100 + i / 100, .2, .1) for i in range(160)]
        engine = self.engine(rows)
        allowed_ids = {f"row{i}" for i in range(140, 160)}
        counts = {}
        def predicate(item):
            key = item["track_id"]
            counts[key] = counts.get(key, 0) + 1
            return key in allowed_ids
        results = engine.recommend(["seed"], limit=5, candidate_filter=predicate)
        self.assertEqual(len(results), 5)
        self.assertTrue(all(item["track_id"] in allowed_ids for item in results))
        self.assertTrue(all(count == 1 for count in counts.values()))

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "songs.csv"
        self.rows = [song("slow", 65, .05, .8), song("fast", 180, .95, .05),
                     song("slow_match", 66, .06, .79), song("fast_match", 179, .94, .06),
                     song("compromise", 115, .5, .4), song("far", 220, .01, .01)]

    def engine(self, rows=None):
        pd.DataFrame(self.rows if rows is None else rows).to_csv(self.path, index=False)
        return MusicRecommender(self.path)

    def test_two_preferences_match_actual_anchors_not_global_compromise(self):
        engine = self.engine()
        results = engine.recommend(["slow", "fast"], limit=2)
        self.assertEqual({r["track_id"] for r in results}, {"slow_match", "fast_match"})
        self.assertEqual({r["neighborhood_context"]["groups"] for r in results}, {2})
        for result in results:
            self.assertEqual(result["model_version"], MODEL_VERSION)
            self.assertTrue(result["feature_version"])
            self.assertTrue(result["source_fingerprint"])
            self.assertIn(result["neighborhood_context"]["anchor_id"], ["slow", "fast"])

    def test_complete_link_does_not_chain_distant_preferences(self):
        matrix = np.asarray([[0, .09, .18], [.09, 0, .09], [.18, .09, 0]])
        labels, groups = MusicRecommender._groups(matrix)
        self.assertEqual(groups, [[0, 1], [2]])

    def test_explicit_candidates_share_metric_and_validate_bound(self):
        engine = self.engine()
        full = {s["track_id"]: s for s in engine.recommend(["slow"], limit=10)}
        scored = engine.score_candidates(["slow"], ["slow_match", "fast_match"])
        for item in scored:
            self.assertAlmostEqual(item["distance"], full[item["track_id"]]["distance"], places=7)
            self.assertAlmostEqual(item["ranking_score"], full[item["track_id"]]["ranking_score"], places=7)
            self.assertEqual(item["ranking_config"]["values"]["artist_bonus"], .18)
        with self.assertRaises(ValueError):
            engine.score_candidates(["slow"], ["unknown"])
        with self.assertRaises(ValueError):
            engine.score_candidates(["slow"], "slow_match")
        with self.assertRaises(ValueError):
            engine.score_candidates(["slow"], ["slow_match"] * 1001)

    def test_fresh_and_focus_exclusions_resolve_full_credit_aliases(self):
        rows = self.rows + [song("excluded", 66, .06, .79, "A; B"),
                            song("alias", 66, .06, .79, " B ;Ａ ")]
        rows[-2]["track_name"] = "What’s Next"
        rows[-1]["track_name"] = "what's  next"
        engine = self.engine(rows)
        results = engine.recommend(["slow"], limit=20, exclude_ids=["excluded"])
        self.assertFalse({"excluded", "alias"} & {r["track_id"] for r in results})
        self.assertEqual(engine.score_candidates(["slow"], ["alias"], exclude_ids=["excluded"]), [])

    def test_close_cross_artist_can_beat_distant_same_artist(self):
        seed = song("seed", 65, .05, .8, "Favorite")
        cross = song("cross", 66, .06, .79, "New Artist")
        distant = song("distant", 220, 1, 0, "Favorite")
        result = self.engine([seed, cross, distant]).recommend(["seed"], limit=2)
        self.assertEqual(result[0]["track_id"], "cross")

    def test_focused_full_context_and_ids_block_nonfocus_alias_discovery(self):
        rows = [song("focus", 100, .2, .1, "Focus"),
                dict(song("collaboration", 101, .2, .1, "B; C"), id_artists=str(["B" * 22, "C" * 22])),
                dict(song("alias", 101, .2, .1, "Different B Name"), id_artists=str(["B" * 22])),
                song("new1", 101, .2, .1, "New One"), song("new2", 102, .2, .1, "New Two"),
                song("known", 101, .2, .1, "Focus")]
        result = self.engine(rows).recommend(["focus"], 5, exclude_ids=["collaboration"],
            known_artist_names={"focus", "b", "c"}, known_artist_ids={"spotify:" + "B" * 22, "spotify:" + "C" * 22})
        discoveries = [r for r in result if r["selection_context"]["discovery"]]
        self.assertEqual({r["track_id"] for r in discoveries}, {"new1", "new2"})
        self.assertTrue(next(r for r in result if r["track_id"] == "alias")["known_artist_overlap"])

    def test_anchor_snapshot_preserves_actual_group_without_recursive_payload(self):
        engine = self.engine()
        positive = dict(engine.get_song("fast"), liked=True, neighborhood_anchors=[{"nested": "large"}],
                        visualization={"nested": "large"}, reason="do not persist in anchor")
        result = engine.recommend(["slow"], 5, feedback=[positive])
        self.assertTrue(result)
        for row in result:
            self.assertEqual(row["matched_anchor"]["track_id"], row["neighborhood_context"]["anchor_id"])
            for entry in row["neighborhood_anchors"]:
                self.assertIn(entry["kind"], ("liked", "positive"))
                self.assertNotIn("neighborhood_anchors", entry["song"])
                self.assertNotIn("visualization", entry["song"])
                self.assertNotIn("reason", entry["song"])

    def test_artist_overlap_can_outrank_closer_unrelated_numeric_match(self):
        seed = dict(self.rows[0], artists="Favorite Artist")
        related = song("artist_match", 78, .12, .72, "Favorite Artist")
        engine = self.engine([seed] + self.rows[1:] + [related])
        results = engine.recommend(["slow"], limit=3)
        self.assertEqual(results[0]["track_id"], "artist_match")
        self.assertAlmostEqual(results[0]["artist_adjustment"], -ARTIST_MATCH_BONUS, places=6)
        self.assertIn("Shares an artist", results[0]["reason_preview"])
        self.assertGreater(results[0]["distance"], next(s["distance"] for s in results if s["track_id"] == "slow_match"))
        self.assertNotIn("artist_match", [s["track_id"] for s in engine.recommend(["slow"], exclude_ids=["artist_match"])])

    def test_artist_ids_take_precedence_over_names_and_credit_substrings(self):
        seed = dict(self.rows[0], artists="Favorite", id_artists=str(["A"*22]))
        same_id = dict(song("alias", 78, .12, .72, "Different credited name"), id_artists=str(["A"*22]))
        namesake = dict(song("namesake", 65, .05, .8, "Favorite"), id_artists=str(["B"*22]))
        substring = song("substring", 65, .05, .8, "Favorite Impersonator")
        engine = self.engine([seed] + self.rows[1:] + [same_id, namesake, substring])
        results = engine.recommend(["slow"], limit=20)
        by_id = {s["track_id"]: s for s in results}
        self.assertEqual(results[0]["track_id"], "alias")
        self.assertEqual(by_id["namesake"]["artist_adjustment"], 0)
        self.assertEqual(by_id["substring"]["artist_adjustment"], 0)

    def test_shared_collaborator_receives_one_artist_bonus(self):
        seed = dict(self.rows[0], artists="Lead; Partner")
        duet = song("duet", 78, .12, .72, "Partner; Other")
        engine = self.engine([seed] + self.rows[1:] + [duet])
        result = next(s for s in engine.recommend(["slow"], limit=20) if s["track_id"] == "duet")
        self.assertAlmostEqual(result["artist_adjustment"], -ARTIST_MATCH_BONUS, places=6)

    def test_punctuation_alias_of_favorite_does_not_consume_artist_slot(self):
        seed = dict(self.rows[0], track_name="What's next", artists="Favorite")
        alias = dict(seed, track_id="alias", track_name="What’s next")
        other_songs = [song("one", 68, .06, .78, "Favorite"), song("two", 70, .07, .76, "Favorite")]
        results = self.engine([seed, alias] + self.rows[1:] + other_songs).recommend(["slow"], limit=2)
        self.assertEqual({s["track_id"] for s in results}, {"one", "two"})

    def test_latest_feedback_exclusions_and_no_profile_state_leakage(self):
        engine = self.engine()
        no = dict(engine.get_song("slow_match"), liked=False, feedback_reason="Already know it")
        yes = dict(no, liked=True)
        excluded = engine.recommend(["slow"], feedback=[no, yes], limit=10)
        self.assertNotIn("slow_match", [r["track_id"] for r in excluded])
        clean = engine.recommend(["slow"], limit=1)
        self.assertEqual(clean[0]["track_id"], "slow_match")
        explicit = engine.recommend(["slow"], exclude_ids=["slow_match"], limit=10)
        self.assertNotIn("slow_match", [r["track_id"] for r in explicit])

    def test_yes_can_add_a_distinct_neighborhood(self):
        engine = self.engine()
        yes = dict(engine.get_song("fast"), liked=True)
        results = engine.recommend(["slow"], feedback=[yes], limit=3)
        self.assertIn("fast_match", [r["track_id"] for r in results])
        # A rated positive is a liked anchor and should not be suggested itself.
        self.assertNotIn("slow", [r["track_id"] for r in results])

    def test_missing_features_do_not_become_matching_evidence(self):
        bad = song("missing", 65, .05, .8)
        for feature in ("acousticness", "speechiness", "instrumentalness", "loudness", "liveness", "duration_ms"):
            bad[feature] = None
        engine = self.engine(self.rows + [bad])
        self.assertNotIn("missing", [r["track_id"] for r in engine.recommend(["slow"], limit=20)])
        with self.assertRaises(ValueError):
            engine.recommend(["old"], favorite_songs=[dict(bad, track_id="old")])

    def test_shared_coverage_counts_measurements_not_one_hot_columns(self):
        matrix = np.zeros((1, 21), dtype=np.float32)
        # All continuous measurements remain sufficient without categorical data.
        masks = np.ones((1, 21), dtype=bool)
        masks[:, 10:] = False
        self.assertTrue(np.isfinite(MusicRecommender._distance(matrix, masks, matrix, masks)[0, 0]))
        # Only four continuous measurements overlap, despite all categories known.
        left = np.ones((1, 21), dtype=bool)
        right = left.copy()
        left[:, :3] = False
        right[:, 7:10] = False
        self.assertTrue(np.isinf(MusicRecommender._distance(matrix, left, matrix, right)[0, 0]))

    def test_familiarity_is_not_negative_feature_training(self):
        engine = self.engine()
        base = dict(engine.get_song("slow_match"), liked=False)
        familiar = engine.recommend(["slow"], feedback=[dict(base, feedback_reason="Already know it")], limit=10)
        dislike = engine.recommend(["slow"], feedback=[dict(base, feedback_reason="Not my style")], limit=10)
        familiar_scores = {r["track_id"]: r["feedback_adjustment"] for r in familiar}
        dislike_scores = {r["track_id"]: r["feedback_adjustment"] for r in dislike}
        self.assertTrue(all(value == 0 for value in familiar_scores.values()))
        self.assertTrue(any(dislike_scores[key] > value for key, value in familiar_scores.items()))

    def test_legacy_four_feature_fixture_falls_back_identically(self):
        pd.DataFrame(self.rows)[["track_id", "track_name", "artists", "valence", "tempo", "energy", "danceability"]].to_csv(self.path, index=False)
        engine = MusicRecommender(self.path)
        self.assertFalse(engine.vectors_active)
        self.assertEqual(engine.recommend(["slow"]), Baseline(self.path).recommend(["slow"]))

    def test_artist_cap_sees_beyond_fifty_near_same_artist(self):
        near = [song(f"many{i}", 65 + i * .001, .05, .8, "same") for i in range(60)]
        others = [song(f"other{i}", 68+i, .06, .78) for i in range(4)]
        results = self.engine(self.rows[:1]+near+others).recommend(["slow"], limit=5)
        self.assertLessEqual(sum(r["artists"] == "same" for r in results), 2)

    def test_duets_and_solos_count_toward_each_individual_artist_cap(self):
        duets = [song(f"duet{i}", 65 + i*.001, .05, .8, f"Repeat; Collaborator {i}") for i in range(60)]
        solos = [song("solo", 65.0001, .05, .8, "Repeat")]
        others = [song(f"other{i}", 68+i, .06, .78) for i in range(4)]
        results = self.engine(self.rows[:1]+duets+solos+others).recommend(["slow"], limit=5)
        self.assertLessEqual(sum("Repeat" in r["artists"].split("; ") for r in results), 2)
        self.assertEqual(len(results), 5)
        # Hybrid post-signal reranking must apply the same individual-artist rule.
        candidates = [dict(row, ranking_score=i*.001,
                           neighborhood_context={"group": 0}) for i, row in enumerate(duets[:4]+solos+others)]
        selected = MusicRecommender.select_candidates(candidates, 5)
        self.assertLessEqual(sum("Repeat" in r["artists"].split("; ") for r in selected), 2)
        self.assertEqual(len(selected), 5)
        self.assertEqual(len(MusicRecommender.select_candidates(candidates[:5], 5)), 5)

    def test_saved_complete_snapshot_and_exhausted_candidates(self):
        engine = self.engine()
        old = dict(self.rows[0], track_id="old", track_name="old")
        self.assertTrue(engine.recommend(["old"], favorite_songs=[old]))
        self.assertEqual(engine.recommend([r["track_id"] for r in self.rows]), [])
        for invalid in (0, -1, True):
            with self.assertRaises(ValueError):
                engine.recommend(["slow"], limit=invalid)

    def test_many_favorites_bound_representatives_and_keep_extremes(self):
        rows = [song(f"like{i}", 60 + i, i/110, 1-i/110) for i in range(110)]
        rows += [song("candidate_low", 60.1, .001, .999),
                 song("candidate_high", 169.1, .991, .009)]
        engine = self.engine(rows)
        results = engine.recommend([r["track_id"] for r in rows[:110]], limit=2)
        self.assertEqual({r["track_id"] for r in results}, {"candidate_low", "candidate_high"})
        self.assertTrue(all(r["neighborhood_context"]["seed_count"] == 96 for r in results))


if __name__ == "__main__":
    unittest.main()
