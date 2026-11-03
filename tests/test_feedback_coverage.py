import tempfile
from pathlib import Path
import unittest
from dataclasses import replace
import pandas as pd

from data.neighborhoods import MusicRecommender
from data.selection import select_candidates
from data.ranking_config import DEFAULT_RANKING
from tests.test_neighborhoods import song


class DirectionalNoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.rows = [song("anchor", 100, .2, .1, "Local"), song("rejected", 100, .21, .1),
                     song("slower", 90, .2, .1), song("faster", 110, .2, .1),
                     song("other_anchor", 200, .95, .8), song("unrelated", 190, .95, .8)]
        path = Path(self.temp.name) / "songs.csv"
        pd.DataFrame(self.rows).to_csv(path, index=False)
        self.engine = MusicRecommender(path)

    def results(self, feedback):
        return {item["track_id"]: item for item in self.engine.recommend(["anchor", "other_anchor"], 20, feedback=feedback)}

    def test_directional_reasons_learn_opposite_local_tempo_preferences(self):
        base = self.results([dict(self.rows[1], liked=False, feedback_reason="Already know it")])
        for reason, worse, better in (("Too slow", "slower", "faster"), ("Too fast", "faster", "slower")):
            feedback = dict(self.rows[1], liked=False, feedback_reason=reason, matched_anchor=self.rows[0])
            results = self.results([feedback])
            penalty = lambda key: results[key]["ranking_score"] - base[key]["ranking_score"]
            self.assertGreater(penalty(worse), penalty(better))
            self.assertAlmostEqual(penalty("unrelated"), 0.)
            for result in results.values():
                self.assertLessEqual(result["feedback_adjustment"], .040001)
                self.assertAlmostEqual(result["ranking_score"], sum(result["score_components"].values()), places=6)
            self.assertEqual(results[better]["directional_feedback_context"]["records"][0]["scope_source"], "matched_anchor")

    def test_fallback_missing_tempo_and_generic_reasons(self):
        directional = self.results([dict(self.rows[1], liked=False, feedback_reason="Too slow")])
        self.assertEqual(directional["slower"]["directional_feedback_context"]["records"][0]["scope_source"], "rejected_song")
        without_tempo = dict(self.rows[1], tempo=None, liked=False, feedback_reason="Too slow")
        generic = self.results([dict(without_tempo, feedback_reason="Other")])
        fallback = self.results([without_tempo])
        for key in fallback:
            self.assertEqual(generic[key]["ranking_score"], fallback[key]["ranking_score"])
            self.assertNotIn("directional_feedback_context", fallback[key])

    def test_repeated_and_generic_negatives_share_one_penalty_bound(self):
        feedback = [dict(self.rows[1], track_id=f"saved{i}", liked=False,
                         feedback_reason="Too slow", matched_anchor=self.rows[0]) for i in range(30)]
        feedback.append(dict(self.rows[1], liked=False, feedback_reason="Wrong mood"))
        for result in self.results(feedback).values():
            self.assertLessEqual(result["feedback_adjustment"], .040001)

    def test_invalid_candidate_tempo_is_unknown_not_zero_bpm_preference(self):
        rows = self.rows + [song("unknown_tempo", 100, .2, .1)]
        path = Path(self.temp.name) / "invalid.csv"
        pd.DataFrame(rows).to_csv(path, index=False)
        self.engine = MusicRecommender(path)
        # The loader normally rejects zero tempo; exercise the ranking guard
        # against an unavailable runtime value without changing other features.
        self.engine.table.loc[self.engine.table["track_id"] == "unknown_tempo", "tempo"] = 0
        baseline = self.results([dict(self.rows[1], liked=False, feedback_reason="Already know it")])
        for reason in ("Too slow", "Too fast"):
            result = self.results([dict(self.rows[1], liked=False, feedback_reason=reason, matched_anchor=self.rows[0])])
            self.assertEqual(result["unknown_tempo"]["ranking_score"], baseline["unknown_tempo"]["ranking_score"])


class AnchorCoverageTests(unittest.TestCase):
    @staticmethod
    def candidate(identifier, anchor_artist, score, group, artist=None, distance=.03):
        return dict(track_id=identifier, track_name=identifier, artists=artist or identifier,
                    ranking_score=score, distance=distance,
                    matched_anchor={"track_id": f"anchor{group}", "artists": anchor_artist},
                    neighborhood_context={"group": group})

    def test_many_groups_for_one_artist_do_not_outvote_old_families(self):
        rows = [self.candidate(f"country{i}", "Morgan" if i < 6 else "Luke", -.18 + i * .001, i) for i in range(11)]
        rows += [self.candidate("old_pop", "Olivia", -.15, 11),
                 self.candidate("old_hiphop", "NF", -.14, 12), self.candidate("old_adele", "Adele", -.13, 13)]
        result = select_candidates(rows, 5)
        families = {tuple(item["selection_context"]["anchor_artist_family"]) for item in result}
        self.assertEqual(len(families), 5)
        self.assertTrue({"old_pop", "old_hiphop", "old_adele"}.issubset({item["track_id"] for item in result}))
        disabled = select_candidates(rows, 5, config=replace(DEFAULT_RANKING, anchor_family_diversity=False))
        self.assertTrue(all(item["track_id"].startswith("country") for item in disabled))

    def test_discoveries_prefer_different_original_anchor_families(self):
        rows = [self.candidate("new_a", "Adele", .001, 0), self.candidate("new_b", "Adele", .002, 1),
                self.candidate("new_c", "NF", .003, 2), self.candidate("known", "Morgan", -.18, 3, "Morgan")]
        result = select_candidates(rows, 5, known_artist_names={"morgan"})
        reserved = [item for item in result if item["selection_context"]["discovery"]]
        self.assertEqual({item["track_id"] for item in reserved}, {"new_a", "new_c"})
        self.assertEqual({item["selection_context"]["discovery_fulfilled"] for item in result}, {2})

    def test_single_family_and_distant_alternatives_do_not_force_shortage(self):
        rows = [self.candidate(f"same{i}", "Focus", -.18 + i * .001, i) for i in range(6)]
        rows.append(self.candidate("far", "Other", .5, 7, distance=.5))
        result = select_candidates(rows, 5)
        self.assertEqual([item["track_id"] for item in result], [f"same{i}" for i in range(5)])
        self.assertTrue(result[1]["selection_context"]["anchor_family_cap_relaxed"])


if __name__ == "__main__":
    unittest.main()
