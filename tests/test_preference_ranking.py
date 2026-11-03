"""Behavioral gates for request-only steering, local comparisons and screening."""
import tempfile
from pathlib import Path
import unittest
import pandas as pd
import numpy as np

from data.neighborhoods import MusicRecommender
from data.hybrid import MusicRecommender as Hybrid
from data.preference_policy import prepare_pairs, pairwise_adjustment
from tests.test_neighborhoods import song


class PreferenceRankingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "songs.csv"
        self.rows = [song("anchor", 100, .2, .1, "Known"),
                     song("slow", 90, .2, .1), song("fast", 110, .2, .1),
                     song("same_artist", 100, .2, .1, "Known"),
                     song("far", 210, 1, .9), song("low", 50, .2, .1)]
        self.rows[1]["energy"] = .4
        self.rows[2]["energy"] = .6
        pd.DataFrame(self.rows).to_csv(self.path, index=False)

    def results(self, engine, **options):
        return {s["track_id"]: s for s in engine.recommend(["anchor"], 20, **options)}

    def test_default_is_exact_neutral_and_request_does_not_mutate(self):
        engine = MusicRecommender(self.path)
        original = self.results(engine)
        self.assertEqual(original, self.results(engine, steering="same", pairwise_feedback=[], candidate_filter=None))
        self.results(engine, steering="faster")
        self.assertEqual(original, self.results(engine))

    def test_directional_targets_change_retrieval_scores_preserve_vectors(self):
        engine = MusicRecommender(self.path)
        original = self.results(engine)
        for option, preferred, other in (("slower", "slow", "fast"), ("faster", "fast", "slow"), ("energetic", "fast", "slow")):
            changed = self.results(engine, steering=option)
            delta = lambda key: changed[key]["ranking_score"] - original[key]["ranking_score"]
            self.assertLess(delta(preferred), delta(other))
            self.assertEqual(changed[preferred]["distance"], original[preferred]["distance"])
            self.assertEqual(changed[preferred]["matched_anchor"], original[preferred]["matched_anchor"])
            self.assertEqual(changed[preferred]["neighborhood_anchors"], original[preferred]["neighborhood_anchors"])
            self.assertEqual(changed[preferred]["tempo"], original[preferred]["tempo"])
            self.assertLessEqual(abs(changed[preferred]["steering_context"]["score_adjustment"]), .02501)
        self.assertEqual(self.results(engine, steering="less_artist")["same_artist"]["artist_adjustment"], original["same_artist"]["artist_adjustment"] / 2)

    def test_pairwise_cap_locality_dedup_and_not_negative(self):
        engine = MusicRecommender(self.path)
        original = self.results(engine)
        pair = dict(choice="a", winner=self.rows[2], loser=self.rows[1], anchor=self.rows[0])
        changed = self.results(engine, pairwise_feedback=[pair] * 50)
        self.assertEqual(changed["fast"]["pairwise_context"]["record_count"], 1)
        self.assertLess(changed["fast"]["ranking_score"], original["fast"]["ranking_score"])
        self.assertGreater(changed["slow"]["ranking_score"], original["slow"]["ranking_score"])
        self.assertEqual(changed["far"]["ranking_score"], original["far"]["ranking_score"])
        self.assertEqual(changed["far"]["pairwise_context"]["active_count"], 0)
        self.assertTrue(all(abs(s["pairwise_context"]["score_adjustment"]) <= .020001 for s in changed.values()))
        self.assertIn("slow", changed)  # Losing is not a No or exclusion.
        self.assertEqual(original, self.results(engine, pairwise_feedback=[dict(pair, choice="equal")]))
        self.assertEqual(original, self.results(engine, pairwise_feedback=[dict(pair, anchor={"track_id": "missing"})]))
        self.assertEqual(original, self.results(engine, pairwise_feedback=[dict(pair, winner=dict(self.rows[2], source_fingerprint="other-catalog"))]))
        self.assertEqual(original, self.results(engine, pairwise_feedback=[dict(pair, anchor=dict(self.rows[0], feature_version="incompatible"))]))

    def test_filter_precedes_discovery_and_applies_hybrid(self):
        for cls in (MusicRecommender, Hybrid):
            engine = cls(self.path)
            results = engine.recommend(["anchor"], 5, candidate_filter=lambda s: s["track_id"] != "slow")
            self.assertNotIn("slow", {s["track_id"] for s in results})
            self.assertTrue(all(not s["selection_context"]["discovery"] or s["distance"] <= .10 for s in results))
            self.assertEqual(engine.recommend(["anchor"], 5, candidate_filter=lambda _: False), [])
            with self.assertRaises(ValueError):
                engine.recommend(["anchor"], steering="unsupported")

    def test_legacy_fallback_filters_and_exhausts(self):
        pd.DataFrame(self.rows).drop(columns=["acousticness"]).to_csv(self.path, index=False)
        for cls in (MusicRecommender, Hybrid):
            engine = cls(self.path)
            self.assertEqual(engine.recommend(["anchor"], candidate_filter=lambda _: False), [])

    def test_compiled_pair_kernel_matches_individual_evidence_calculation(self):
        engine = MusicRecommender(self.path)
        pairs = prepare_pairs([dict(choice="a", anchor=self.rows[0], winner=self.rows[2], loser=self.rows[1]),
                               dict(choice="b", anchor=self.rows[0], winner=self.rows[3], loser=self.rows[2])], engine.vectors)
        matrix, validity = engine.vectors.transform(self.rows)
        masks = engine.vectors.expand_validity(validity)
        expected, counts = np.zeros(len(matrix)), np.zeros(len(matrix))
        for seeds, seed_masks, _ in pairs:
            distances = engine._distance(matrix, masks, seeds, seed_masks)
            eligible = np.isfinite(distances).all(axis=1) & (distances[:, 2] <= .10)
            preference = np.exp(-distances[:, 1] ** 2 / .01) - np.exp(-distances[:, 0] ** 2 / .01)
            expected += np.where(eligible, preference, 0)
            counts += eligible
        actual, actual_counts = pairwise_adjustment(matrix, masks, pairs, engine._distance)
        np.testing.assert_allclose(actual, .02 * expected / np.maximum(counts, 1), atol=1e-8)
        np.testing.assert_array_equal(actual_counts, counts)
        self.assertLess(len(pairs.seed_matrix), len(pairs) * 3)


if __name__ == "__main__":
    unittest.main()
