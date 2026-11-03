"""Offline enrichment contracts: missing data is neutral, identities stay honest."""
import csv
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import pandas as pd

from data.backend import FeedbackStore, MusicRecommender as Audio
from data.hybrid import MusicRecommender, VERSION, RICH_VERSION
from data.neighborhoods import MODEL_VERSION as NEIGHBORHOOD_VERSION
from data.main import MusicMatchApp


def mbid(n):
    return f"00000000-0000-4000-8000-{n:012d}"


class HybridTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.csv = self.root / "audio.csv"
        with self.csv.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["track_id", "track_name", "artists", "duration_ms", "valence", "tempo", "energy", "danceability"])
            writer.writerows([
                ["a", "Seed", "Artist A", 180000, .5, 100, .5, .5],
                ["b", "Close", "Artist B", 180000, .51, 101, .51, .51],
                ["c", "Other", "Artist C", 180000, .6, 110, .6, .6],
            ])
        self.catalog = self.root / "catalog.json"
        self.doc = {"schema_version": 1, "tracks": [self.track(1, "Seed", "Artist A", 11),
            self.track(2, "Close", "Artist B", 12), self.track(3, "New", "Artist D", 14)],
            "related_edges": [self.edge(11, 2), self.edge(11, 3), self.edge(14, 2)]}

    @staticmethod
    def track(n, title, artist, artist_id):
        return {"mbid": mbid(n), "title": title, "artist_names": [artist],
            "artist_mbids": [mbid(artist_id)], "duration_ms": 180000,
            "source": "musicbrainz", "license": "CC0-1.0"}

    @staticmethod
    def edge(seed, recording):
        return {"seed_artist_mbid": mbid(seed), "recording_mbid": mbid(recording),
            "source": "listenbrainz", "license": "CC0-1.0"}

    def engine(self):
        self.catalog.write_text(json.dumps(self.doc), encoding="utf-8")
        return MusicRecommender(self.csv, self.catalog)

    def rich_engine(self):
        table = pd.read_csv(self.csv)
        for name, value in {"acousticness": .2, "instrumentalness": .1,
                "speechiness": .1, "loudness": -8, "liveness": .1,
                "key": 0, "mode": 1, "time_signature": 4}.items():
            table[name] = value
        table.to_csv(self.csv, index=False)
        engine = self.engine()
        self.assertTrue(engine.audio.vectors_active)
        return engine

    def test_absent_or_unmapped_enrichment_is_exact_baseline(self):
        baseline = Audio(self.csv).recommend(["a"])
        self.assertEqual(MusicRecommender(self.csv).recommend(["a"]), baseline)
        self.doc["related_edges"] = []
        self.assertEqual(self.engine().recommend(["a"]), baseline)

    def test_metadata_search_and_discovery_have_no_invented_audio(self):
        engine = self.engine()
        song = engine.search("New", title_only=True)[0]
        self.assertNotIn("tempo", song)
        results = engine.recommend(["a"], limit=3)
        self.assertEqual(len(results), 3)
        self.assertEqual(results[-1]["track_id"], "mb:" + mbid(3))
        self.assertNotIn("distance", results[-1])
        self.assertEqual(results[-1]["model_version"], VERSION)
        self.assertIn("unknown", MusicMatchApp.reason_preview(results[-1]))
        self.assertEqual(len(engine.recommend(["a"], limit=1)), 1)

    def test_metadata_only_favorite_can_use_provider_relationship_and_persist(self):
        engine = self.engine()
        favorite = engine.get_song("mb:" + mbid(3))
        # Edge points to audio-mapped recording, so it must be available without an audio seed.
        result = engine.recommend([favorite["track_id"]])
        self.assertTrue(result)
        store = FeedbackStore(self.root / "feedback.sqlite3")
        batch = store.save_batch([favorite], result)
        store.save_feedback(batch, result[0]["track_id"], True)
        restored = store.load_profile("personal")
        self.assertEqual(restored["favorites"], [favorite])
        self.assertEqual(store.training_feedback("personal")[0]["liked"], True)
        self.assertEqual(store.training_feedback("test"), [])

    def test_alias_exclusions_and_fresh_exhaustion(self):
        engine = self.engine()
        result = engine.recommend(["a"], exclude_ids=["mb:" + mbid(2), "mb:" + mbid(3)])
        self.assertEqual([s["track_id"] for s in result], ["c"])
        self.assertEqual(engine.recommend(["a"], exclude_ids=["b", "c", "mb:" + mbid(3)]), [])
        rejected = dict(engine.get_song("mb:" + mbid(2)), liked=False)
        self.assertNotIn("b", [s["track_id"] for s in engine.recommend(["a"], feedback=[rejected])])

    def test_partial_listenbrainz_metadata_is_usable(self):
        self.doc["tracks"][-1]["source"] = "listenbrainz_musicbrainz_metadata"
        self.doc["related_edges"].append(self.edge(11, 999))
        engine = self.engine()
        self.assertIsNone(engine.enrichment_warning)
        self.assertIn("mb:" + mbid(3), [s["track_id"] for s in engine.recommend(["a"], limit=3)])

    def test_partial_credit_duplicates_do_not_consume_discovery_slot(self):
        self.doc["tracks"][1]["credit_complete"] = False
        engine = self.engine()
        results = engine.recommend(["a"], limit=3)
        self.assertEqual([s["track_id"] for s in results], ["b", "c", "mb:" + mbid(3)])
        self.assertNotIn("audio_model_version", results[-1])
        self.assertIn("audio_model_version", results[0])

    def test_partial_credit_aliases_honor_no_and_fresh_in_both_directions(self):
        self.doc["tracks"][1]["credit_complete"] = False
        engine = self.engine()
        for excluded_id in ("b", "mb:" + mbid(2)):
            with self.subTest(excluded_id=excluded_id):
                results = engine.recommend(["a"], limit=3, exclude_ids=[excluded_id])
                self.assertFalse({"b", "mb:" + mbid(2)} & {s["track_id"] for s in results})
        rejected = dict(engine.get_song("b"), liked=False)
        self.assertFalse({"b", "mb:" + mbid(2)} & {
            s["track_id"] for s in engine.recommend(["a"], feedback=[rejected])})
        # The same policy also applies on the exact original-audio fallback path.
        self.doc["related_edges"] = []
        fallback = self.engine().recommend(["a"], exclude_ids=["mb:" + mbid(2)])
        self.assertNotIn("b", [s["track_id"] for s in fallback])

    def test_discovery_duplicates_are_removed_before_limit(self):
        self.doc["tracks"].extend([
            self.track(4, "Twin", "Artist E", 15),
            self.track(5, "Twin", "Artist E", 15),
            self.track(6, "Another", "Artist F", 16)])
        self.doc["related_edges"].extend([self.edge(14, n) for n in (4, 5, 6)])
        results = self.engine().recommend(["mb:" + mbid(3)], limit=3)
        self.assertEqual([s["track_name"] for s in results], ["Close", "Twin", "Another"])

    def test_metadata_only_exhaustion_is_empty_but_missing_support_is_explicit(self):
        engine = self.engine()
        self.assertEqual(engine.recommend(["mb:" + mbid(3)], exclude_ids=["b"]), [])
        self.doc["related_edges"] = []
        with self.assertRaisesRegex(ValueError, "no cached listening recommendations"):
            self.engine().recommend(["mb:" + mbid(3)])

    def test_ambiguous_versions_never_map_automatically(self):
        self.doc["tracks"].append(self.track(4, "Seed", "Artist A", 11))
        engine = self.engine()
        self.assertNotIn("a", engine.audio_to_mbid)
        self.assertEqual(engine.recommend(["a"]), Audio(self.csv).recommend(["a"]))

    def test_partial_artist_credits_never_map_automatically(self):
        self.doc["tracks"][0]["credit_complete"] = False
        engine = self.engine()
        self.assertNotIn("a", engine.audio_to_mbid)
        self.assertTrue(engine.search("Seed"))
        self.assertEqual(engine.recommend(["a"]), Audio(self.csv).recommend(["a"]))

    def test_version_notes_are_preserved_for_display(self):
        self.doc["tracks"][-1]["disambiguation"] = "live, 2025"
        found = self.engine().search("New", title_only=True)[0]
        self.assertEqual(found["track_name"], "New")
        self.assertEqual(found["display_title"], "New (live, 2025)")

    def test_reviewed_artist_name_can_seed_without_recording_match(self):
        self.doc["tracks"][0]["credit_complete"] = False
        self.doc["artists"] = [{"name": "Artist A", "requested_name": "Artist A",
            "mbid": mbid(11), "match_confidence": "manually_verified"}]
        engine = self.engine()
        self.assertNotIn("a", engine.audio_to_mbid)
        self.assertIn("mb:" + mbid(3), [s["track_id"] for s in engine.recommend(["a"], limit=3)])

    def test_known_namesake_disables_reviewed_name_fallback(self):
        self.doc["tracks"][0]["credit_complete"] = False
        self.doc["artists"] = [
            {"name": "Artist A", "mbid": mbid(11), "match_confidence": "manually_verified"},
            {"name": "Artist A", "mbid": mbid(99), "match_confidence": "provisional"}]
        engine = self.engine()
        self.assertNotIn("artist a", engine.artist_names)
        self.assertEqual(engine.recommend(["a"]), Audio(self.csv).recommend(["a"]))

    def test_rich_model_keeps_neighborhoods_and_does_not_force_unknown_discovery(self):
        engine = self.rich_engine()
        results = engine.recommend(["a"], limit=3)
        self.assertEqual({s["track_id"] for s in results}, {"b", "c"})
        for song in results:
            self.assertTrue(song["neighborhood_context"])
            self.assertTrue(song["feature_version"])
            self.assertEqual(song["model_version"], RICH_VERSION)
            self.assertLessEqual(abs(song.get("listening_adjustment", 0)), .025)
        store = FeedbackStore(self.root / "rich.sqlite3")
        batch = store.save_batch([engine.get_song("a")], results)
        store.save_feedback(batch, results[0]["track_id"], True)
        restored = store.training_feedback()[0]
        self.assertEqual(restored["source_fingerprint"], results[0]["source_fingerprint"])
        self.assertEqual(restored["neighborhood_context"], results[0]["neighborhood_context"])

    def test_rich_model_resolves_known_metadata_favorite_on_no_support_path(self):
        self.doc["related_edges"] = []
        engine = self.rich_engine()
        results = engine.recommend(["mb:" + mbid(1)])
        self.assertTrue(results)
        self.assertEqual(results[0]["model_version"], NEIGHBORHOOD_VERSION)
        self.assertEqual(results[0]["favorite_resolution"], {
            "selected_ids": ["mb:" + mbid(1)], "audio_input_ids": ["a"]})

    def test_rich_index_does_not_label_provider_only_result_as_neighborhood_match(self):
        engine = self.rich_engine()
        results = engine.recommend(["mb:" + mbid(3)])
        self.assertTrue(results)
        self.assertEqual(results[0]["model_version"], VERSION)
        self.assertNotIn("neighborhood_context", results[0])
        self.assertNotIn("audio_model_version", results[0])

    def test_bad_optional_sidecar_preserves_original_app(self):
        self.doc["tracks"][0]["license"] = "unknown"
        engine = self.engine()
        self.assertTrue(engine.enrichment_warning)
        self.assertEqual(engine.recommend(["a"]), Audio(self.csv).recommend(["a"]))
        with patch("urllib.request.urlopen", side_effect=AssertionError("UI must not use network")):
            MusicRecommender(self.csv, self.catalog).search("Seed")

    def test_rich_graph_union_scores_candidate_outside_fifty(self):
        table = pd.read_csv(self.csv)
        seed = table.iloc[0].to_dict()
        rows = [seed]
        for i in range(260):
            rows.append(dict(seed, track_id=f"near{i}", track_name=f"Near{i}", artists=f"Artist{i}", tempo=100.01))
        rows.append(dict(seed, track_id="graph", track_name="Graph", artists="Graph Artist", tempo=100.02))
        pd.DataFrame(rows).to_csv(self.csv, index=False)
        self.doc["tracks"] = [self.track(1, "Seed", "Artist A", 11), self.track(4, "Graph", "Graph Artist", 15)]
        self.doc["related_edges"] = [self.edge(11, 4)]
        engine = self.rich_engine()
        raw = engine.audio.recommend(["a"], 50, diversify=False)
        self.assertNotIn("graph", {s["track_id"] for s in raw})
        results = engine.recommend(["a"], limit=5)
        self.assertEqual(results[0]["track_id"], "graph")
        graph = results[0]
        pure = engine.audio.score_candidates(["a"], ["graph"])[0]
        self.assertEqual(graph["distance"], pure["distance"])
        self.assertEqual(graph["score_components"]["audio_distance"], pure["distance"])
        self.assertAlmostEqual(graph["ranking_score"], pure["ranking_score"] - .02, places=6)

    def test_rich_supported_path_retains_diverse_pool_beyond_fifty(self):
        table = pd.read_csv(self.csv)
        seed = table.iloc[0].to_dict()
        rows = [seed] + [dict(seed, track_id=f"near{i}", track_name=f"Near{i}", artists="Repeated", tempo=100.01) for i in range(60)]
        rows += [dict(seed, track_id=f"other{i}", track_name=f"Other{i}", artists=f"Novel{i}", tempo=100.02) for i in range(5)]
        pd.DataFrame(rows).to_csv(self.csv, index=False)
        self.doc["tracks"].append(self.track(4, "Near0", "Repeated", 15))
        self.doc["related_edges"].append(self.edge(11, 4))
        engine = self.rich_engine()
        results = engine.recommend(["a"], limit=5)
        self.assertEqual(len(results), 5)
        self.assertLessEqual(sum(s["artists"] == "Repeated" for s in results), 2)

    def test_exhausted_rich_audio_does_not_force_metadata_only_discovery(self):
        engine = self.rich_engine()
        self.assertEqual(engine.recommend(["a"], exclude_ids=["b", "c"]), [])

    def test_screening_filters_graph_union_before_selection(self):
        engine = self.rich_engine()
        results = engine.recommend(["a"], limit=5, candidate_filter=lambda song: song["track_id"] == "b")
        self.assertEqual([song["track_id"] for song in results], ["b"])
        self.assertEqual(engine.recommend(["a"], candidate_filter=lambda _: False), [])

    def test_screening_filters_metadata_only_provider_discoveries(self):
        engine = self.rich_engine()
        self.assertTrue(engine.recommend(["mb:" + mbid(3)]))
        self.assertEqual(engine.recommend(["mb:" + mbid(3)], candidate_filter=lambda _: False), [])


if __name__ == "__main__":
    unittest.main()
