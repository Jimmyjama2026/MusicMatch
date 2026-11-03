import copy
import json
from pathlib import Path
import tempfile
import unittest

from data.backend import FeedbackStore
from data.neighborhood_view import attach_visuals, comparison_table
from data.song_vectors import SongVectors


def song(index):
    return dict(track_id=str(index), track_name="Song " + str(index), artists="Artist " + str(index),
        energy=.40 + index * .001, valence=.3, tempo=120 + index, danceability=.5,
        acousticness=.6, instrumentalness=.01, speechiness=.05, loudness=-12,
        liveness=.1, duration_ms=180000 + 1000 * index, key=index % 12, mode=1, time_signature=4)


def batch(anchors=None):
    anchors = anchors or [song(0), song(1)]
    candidate = song(2)
    candidate.update(neighborhood_anchors=[dict(song=s, group=i % 2, kind="liked")
                        for i, s in enumerate(anchors)],
        matched_anchor=anchors[0], neighborhood_context={"group": 0},
        selection_context={"discovery": True}, feature_version="test", source_fingerprint="saved-source")
    return [candidate]


class NeighborhoodViewTests(unittest.TestCase):
    def setUp(self):
        self.vectors = SongVectors.build([song(i) for i in range(8)])

    def test_real_vectors_groups_and_raw_values_are_saved_and_deterministic(self):
        first, second = batch(), batch()
        attach_visuals(first, self.vectors)
        attach_visuals(second, self.vectors)
        self.assertEqual(first, second)
        view = first[0]["neighborhood_visual"]
        self.assertTrue(view["available"])
        self.assertEqual(len(view["points"]), 3)
        self.assertEqual([g["id"] for g in view["groups"]], [0, 1])
        candidate = next(p for p in view["points"] if p["kind"] == "suggestion")
        self.assertTrue(candidate["discovery"])
        self.assertEqual(first[0]["match_table"][0]["liked"], "40.0%")
        self.assertEqual(first[0]["match_table"][0]["suggested"], "40.2%")
        self.assertIn("cannot be compared", view["projection_note"])
        json.dumps(first, allow_nan=False)

    def test_incomplete_features_are_not_projected_as_zero(self):
        songs = batch()
        songs[0]["acousticness"] = None
        attach_visuals(songs, self.vectors)
        view = songs[0]["neighborhood_visual"]
        self.assertEqual(view["omitted_incomplete"], 1)
        self.assertNotIn("2", [p["track_id"] for p in view["points"]])
        self.assertEqual(songs[0]["match_table"][3]["suggested"], "Unavailable")

    def test_single_and_constant_vectors_are_finite_and_centered(self):
        songs = batch([song(2)])
        attach_visuals(songs, self.vectors)
        points = songs[0]["neighborhood_visual"]["points"]
        self.assertEqual(len(points), 1)
        self.assertEqual((points[0]["x"], points[0]["y"]), (.5, .5))
        json.dumps(songs, allow_nan=False)

    def test_cap_retains_candidate_and_matched_anchor_and_reports_omission(self):
        songs = batch([song(i) for i in range(90)])
        attach_visuals(songs, self.vectors, max_points=12)
        view = songs[0]["neighborhood_visual"]
        self.assertEqual(len(view["points"]), 12)
        self.assertEqual(view["omitted_display"], 78)
        self.assertTrue({"0", "2"}.issubset({p["track_id"] for p in view["points"]}))

    def test_history_does_not_reconstruct_with_changed_features(self):
        songs = batch()
        attach_visuals(songs, self.vectors)
        expected = copy.deepcopy(songs[0]["neighborhood_visual"])
        with tempfile.TemporaryDirectory() as temp:
            store = FeedbackStore(Path(temp) / "test.sqlite3")
            batch_id = store.save_batch([song(0)], songs)
            songs[0]["matched_anchor"]["energy"] = .99
            self.vectors.metadata["centers"][0] = .99
            restored = store.load_batch("personal", batch_id)
            self.assertEqual(restored["recommendations"][0]["neighborhood_visual"], expected)
            self.assertEqual(restored["recommendations"][0]["match_table"][0]["liked"], "40.0%")

    def test_missing_snapshot_does_not_invent_historical_view(self):
        songs = [song(2)]
        attach_visuals(songs, self.vectors)
        self.assertNotIn("neighborhood_visual", songs[0])
        self.assertEqual(comparison_table({}, {})[0]["suggested"], "Unavailable")

    def test_invalid_measurements_never_display_as_audio_facts(self):
        candidate = dict(song(2), energy=-.5, tempo=-120, duration_ms=-1000)
        rows = comparison_table(candidate, song(0))
        for index in (0, 4, 5):
            self.assertEqual(rows[index]["suggested"], "Unavailable")
            self.assertNotEqual(rows[index]["liked"], "Unavailable")
