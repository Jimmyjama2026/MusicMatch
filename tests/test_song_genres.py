import json
from pathlib import Path
import tempfile
import unittest

import pandas as pd

from data.genres import VERSION, ARTIST_VERSION, compatible, labels, effective_labels
from data.neighborhoods import MusicRecommender
from scripts.acquire_song_genres import matching_recording, fetch_song, supported_genres
from tests.test_neighborhoods import song


def evidence(row, genres):
    return dict(row, status="labelled", level="recording", genres=genres)


class SongGenreTests(unittest.TestCase):
    def test_recording_labels_override_conflicting_artist_fallback(self):
        item = {"genre_evidence": {"level": "recording", "genres": ["country"]},
                "artist_genre_evidence": {"level": "artist", "genres": ["pop"]}}
        self.assertEqual(effective_labels(item), frozenset(["country"]))
        self.assertFalse(compatible(item, {"artist_genre_evidence": {"level": "artist", "genres": ["pop"]}}))

    def test_artist_ids_drive_fallback_and_explanations_do_not_claim_song_labels(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rows = [dict(song(i, 100, .2, .1, "Same display name"), id_artists=str([artist]))
                    for i, artist in (("seed", "country-id"), ("match", "country-id"), ("wrong", "metal-id"))]
            pd.DataFrame(rows).to_csv(root / "songs.csv", index=False)
            (root / "artists.json").write_text(json.dumps({"version": ARTIST_VERSION, "source": "fixture", "license": "fixture",
                "artists": {"country-id": {"genres": ["country"]}, "metal-id": {"genres": ["metal"]}}}))
            engine = MusicRecommender(root / "songs.csv", artist_genre_path=root / "artists.json")
            results = engine.recommend(["seed"], limit=5)
            self.assertEqual([r["track_id"] for r in results], ["match"])
            self.assertEqual(results[0]["genre_context"]["status"], "shared_artist_genre_fallback")
            self.assertIn("artist fallback", results[0]["reason_preview"])
            self.assertEqual(results[0]["matched_anchor"]["artist_genre_evidence"]["level"], "artist")

    def test_artist_and_unknown_labels_are_not_recording_evidence(self):
        self.assertFalse(labels({"genres": ["pop"]}))
        self.assertFalse(labels({"genre_evidence": {"level": "artist", "genres": ["pop"]}}))
        self.assertFalse(compatible({}, {}))

    def test_neighborhoods_and_candidates_obey_genres_despite_same_audio_artist(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rows = [song(i, 100, .2, .1, "Same Artist") for i in ("country", "metal", "country_match", "metal_match", "unknown")]
            pd.DataFrame(rows).to_csv(root / "songs.csv", index=False)
            payload = {"version": VERSION, "songs": {r["track_id"]: evidence(r, ["country" if "country" in r["track_id"] else "metal"])
                                                       for r in rows[:-1]}}
            (root / "genres.json").write_text(json.dumps(payload))
            engine = MusicRecommender(root / "songs.csv", genre_path=root / "genres.json")
            results = engine.recommend(["country", "metal"], limit=5)
            self.assertEqual({r["track_id"] for r in results}, {"country_match", "metal_match"})
            self.assertTrue(all(r["neighborhood_context"]["groups"] == 2 for r in results))
            self.assertTrue(all(r["genre_context"]["shared_genres"] for r in results))
            self.assertEqual([r["track_id"] for r in engine.recommend(["country"], limit=5)], ["country_match"])
            self.assertEqual(engine.score_candidates(["country"], ["metal_match", "unknown"]), [])

    def test_recording_join_rejects_versions_namesakes_and_ambiguity(self):
        row = song("x", 100, .2, .1, "Artist")
        recording = {"id": "dc80e9a0-8282-4bea-8cdb-a7acdeb7f692", "title": "x", "length": 200000,
                     "artist-credit": [{"artist": {"name": "Artist"}}]}
        self.assertEqual(matching_recording(row, [recording]), recording)
        self.assertIsNone(matching_recording(row, [dict(recording, length=210000)]))
        self.assertIsNone(matching_recording(row, [dict(recording, disambiguation="live")] ))
        self.assertIsNone(matching_recording(row, [recording, dict(recording, id="c3551fa7-ee72-4295-8fbd-a2d203dd17b6")]))

    def test_only_positive_recording_genres_are_collected(self):
        row = song("x", 100, .2, .1, "Artist")
        mbid = "dc80e9a0-8282-4bea-8cdb-a7acdeb7f692"
        class Client:
            last_retrieved_at = "test"
            def get(self, *args):
                return {"id": mbid, "title": "x", "length": 200000,
                        "artist-credit": [{"artist": {"name": "Artist", "genres": [{"name": "metal", "count": 10}]}}],
                        "genres": [{"name": "pop", "count": 2}, {"name": "rock", "count": -1}]}
        result = fetch_song(Client(), row, mbid)
        self.assertEqual(result["genres"], ["pop"])
        self.assertEqual(result["level"], "recording")

    def test_weak_conflicting_tags_are_retained_for_review_not_used_as_boundaries(self):
        selected, votes = supported_genres({"genres": [{"name": "country", "count": 4},
                                                        {"name": "pop", "count": 2},
                                                        {"name": "jazz", "count": 1}]})
        self.assertEqual(selected, ["country"])
        self.assertEqual(votes["jazz"], 1)
        self.assertEqual(supported_genres({"genres": [{"name": "rock", "count": 1}]})[0], [])

    def test_unknown_anchors_stay_separate_and_known_candidate_cannot_join_them(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rows = [song(i, 100, .2, .1) for i in ("known", "unknown1", "unknown2", "candidate")]
            pd.DataFrame(rows).to_csv(root / "songs.csv", index=False)
            (root / "genres.json").write_text(json.dumps({"version": VERSION, "songs": {
                r["track_id"]: evidence(r, ["country"]) for r in (rows[0], rows[3])}}))
            engine = MusicRecommender(root / "songs.csv", genre_path=root / "genres.json")
            result = engine.recommend(["known", "unknown1", "unknown2"], limit=5)
            self.assertEqual(result[0]["neighborhood_context"]["groups"], 3)
            self.assertEqual(engine.score_candidates(["unknown1"], ["candidate"]), [])


if __name__ == "__main__":
    unittest.main()
