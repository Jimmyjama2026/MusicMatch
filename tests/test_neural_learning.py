import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from sklearn.neural_network import MLPClassifier
from sklearn.linear_model import LogisticRegression

from data.neural_learning import (NeuralScorer, feature_matrix, train_candidate, INPUT_WIDTH,
                                  training_status, record_features_compatible)
from data.song_vectors import SongVectors


def song(index, **changes):
    result = {"track_id": str(index), "track_name": "Song " + str(index),
              "artists": "Artist " + str(index % 3), "valence": .5, "tempo": 120.,
              "energy": .5, "danceability": .5, "acousticness": .3,
              "instrumentalness": .1, "speechiness": .2, "loudness": -10.,
              "liveness": .2, "duration_ms": 180000., "key": 2, "mode": 1,
              "time_signature": 4}
    result.update(changes)
    return result


def fixture(count=120):
    catalog = [song(i, tempo=70. + i, loudness=-20 + i / 10,
                    duration_ms=100000 + i * 1000) for i in range(count)]
    manifest = SongVectors.build(catalog).metadata
    records = []
    for i in range(count):
        liked = i % 2 == 0
        records.append({"song": song(i, energy=.85 if liked else .15),
            "anchor": song(1000 + i % 3), "liked": liked,
            "reason": "Not my style" if not liked else "Overall fit",
            "judged_at": f"2026-10-{1 + i // 24:02}T{i % 24:02}:00:00Z",
            "event_id": str(i), "profile_id": "test", "feature_version": manifest["version"],
            "source_fingerprint": manifest["source_fingerprint"],
            "heuristic_score": .8 if liked else .2})
    return manifest, records


class NeuralLearningTests(unittest.TestCase):
    def test_anchorless_favorites_train_with_negative_masked_views(self):
        manifest, records = fixture()
        for i in range(0, 40, 2):
            records[i].update(anchor=None, judgment_source="favorite", heuristic_score=None)
        matrix, eligible = feature_matrix([records[0]["song"]], [None], manifest)
        self.assertTrue(eligible[0])
        np.testing.assert_array_equal(matrix[0, 20:80], np.zeros(60))
        self.assertEqual(matrix[0, 81], 0.)
        captured = []
        original = MLPClassifier.fit
        def capture(model, x, y, **kwargs):
            captured.append((x.copy(), y.copy()))
            return original(model, x, y, **kwargs)
        with tempfile.TemporaryDirectory() as directory, patch.object(MLPClassifier, "fit", capture):
            result = train_candidate(records, directory, manifest)
            self.assertEqual(result["state"], "shadow_ready")
            self.assertEqual(result["counts"]["favorite_positives"], 20)
            self.assertGreater(result["split"]["masked_training_views"], 0)
            scorer = NeuralScorer.load(directory, manifest)
            values = scorer.score([records[0]["song"]], [None])
            self.assertTrue(np.isfinite(values[0]))
            unscaled = captured[0][0] * scorer.arrays["scale"] + scorer.arrays["mean"]
            missing = np.isclose(unscaled[:, 81], 0.)
            self.assertEqual(set(captured[0][1][missing]), {0, 1})

    def test_genres_sources_and_unknowns_enter_inputs_without_identity_or_outcomes(self):
        manifest, _ = fixture()
        base = song(1)
        country = dict(base, artist_genre_evidence={"level": "artist", "genres": ["country"]})
        metal = dict(base, artist_genre_evidence={"level": "artist", "genres": ["metal"]})
        matrix, valid = feature_matrix([country, metal, base], [country] * 3, manifest)
        self.assertTrue(valid.all())
        np.testing.assert_array_equal(matrix[0, :82], matrix[1, :82])
        self.assertFalse(np.array_equal(matrix[0, 82:], matrix[1, 82:]))
        self.assertEqual(matrix[0, -7], 1.)  # Shared known genre.
        self.assertEqual(matrix[1, -5], 1.)  # Known conflict.
        self.assertEqual(matrix[2, -10], 0.)  # Unknown, not conflict.
        self.assertEqual(matrix[2, -5], 0.)
        renamed = dict(country, track_id="different", track_name="Other", artists="Somebody", liked=False, ranking_score=123)
        changed, _ = feature_matrix([renamed], [country], manifest)
        np.testing.assert_array_equal(changed[0], matrix[0])
        override = dict(metal, genre_evidence={"level": "recording", "genres": ["country"]})
        preferred, _ = feature_matrix([override], [country], manifest)
        np.testing.assert_array_equal(preferred[0, 82:82 + 192], matrix[0, 82:82 + 192])
        self.assertEqual(preferred[0, -4], 1.)

    def test_neural_model_can_learn_genre_when_audio_is_identical(self):
        manifest, records = fixture()
        for i, record in enumerate(records):
            record["song"] = song(i, artist_genre_evidence={"level": "artist", "genres": ["country" if record["liked"] else "metal"]})
            record["anchor"] = song(1000 + i % 3, artist_genre_evidence={"level": "artist", "genres": ["country"]})
        with tempfile.TemporaryDirectory() as directory:
            result = train_candidate(records, directory, manifest)
            self.assertEqual(result["state"], "shadow_ready")
            self.assertGreater(result["evaluation"]["neural_auc"], .95)
            self.assertFalse(result["enabled"])
            scorer = NeuralScorer.load(directory, manifest)
            scores = scorer.score([records[0]["song"], records[1]["song"]], [records[0]["anchor"]] * 2)
            self.assertGreater(scores[0], scores[1])
            pointer = json.loads((Path(directory) / "manifest.json").read_text())
            path = Path(directory) / pointer["generation"] / "metadata.json"
            metadata = json.loads(path.read_text())
            metadata["genre_feature_contract"]["buckets"] = 32
            path.write_text(json.dumps(metadata))
            with self.assertRaises(ValueError):
                NeuralScorer.load(directory, manifest)

    def test_low_data_and_reasons_are_counted_without_fit(self):
        manifest, records = fixture(30)
        records[0]["reason"] = "Too slow"
        records[1]["reason"] = "Too fast"
        records[2]["reason"] = "Already know it"
        records[3]["song"]["energy"] = None
        records[4]["feature_version"] = "stale"
        with tempfile.TemporaryDirectory() as temporary, patch(
                "data.neural_learning.MLPClassifier.fit", side_effect=AssertionError("must not fit")):
            result = train_candidate(records, temporary, manifest)
            self.assertEqual(result["state"], "needs_data")
            self.assertEqual(result["counts"]["eligible"], 25)
            self.assertEqual(result["excluded"]["direction_or_familiarity"], 3)
            self.assertFalse(training_status(temporary)["enabled"])
            self.assertFalse((Path(temporary) / "manifest.json").exists())

    def test_known_v1_raw_snapshot_migration_preserves_nonduration_inputs(self):
        manifest, records = fixture(30)
        legacy = copy.deepcopy(records)
        for record in legacy:
            record["feature_version"] = "rich-audio-vectors-v1"
            self.assertTrue(record_features_compatible(record, manifest))
        current_matrix, _ = feature_matrix([r["song"] for r in records],
            [r["anchor"] for r in records], manifest)
        legacy_matrix, _ = feature_matrix([r["song"] for r in legacy],
            [r["anchor"] for r in legacy], manifest)
        np.testing.assert_array_equal(current_matrix, legacy_matrix)
        with tempfile.TemporaryDirectory() as temporary:
            accepted = train_candidate(legacy, temporary, manifest)
            self.assertEqual(accepted["counts"]["eligible"], 30)
            self.assertEqual(accepted["state"], "needs_data")
            legacy[0]["feature_version"] = "unknown-future-version"
            legacy[1]["source_fingerprint"] = "different-dataset"
            rejected = train_candidate(legacy, temporary, manifest)
            self.assertEqual(rejected["excluded"]["stale_features"], 2)
            self.assertEqual(rejected["counts"]["eligible"], 28)

    def test_shadow_numpy_parity_and_duration_does_not_enter_inputs(self):
        manifest, records = fixture()
        fitted = []
        original = MLPClassifier.fit
        def capture(model, x, y, **kwargs):
            result = original(model, x, y, **kwargs)
            fitted.append(model)
            return result
        with tempfile.TemporaryDirectory() as temporary, patch.object(MLPClassifier, "fit", capture):
            result = train_candidate(records, temporary, manifest)
            self.assertEqual(result["state"], "shadow_ready")
            self.assertFalse(result["enabled"])
            self.assertLess(result["parameter_count"], 6000)
            scorer = NeuralScorer.load(temporary, manifest)
            matrix, valid = feature_matrix([r["song"] for r in records], [r["anchor"] for r in records], manifest)
            self.assertEqual(matrix.shape, (120, INPUT_WIDTH))
            self.assertTrue(valid.all())
            arrays = scorer.arrays
            expected = fitted[0].predict_proba((matrix - arrays["mean"]) / arrays["scale"])[:, 1]
            np.testing.assert_allclose(scorer.predict_matrix(matrix), expected, atol=1e-12)
            changed = copy.deepcopy(records)
            for record in changed:
                record["song"]["duration_ms"] *= 10
                record["anchor"]["duration_ms"] /= 10
            altered, _ = feature_matrix([r["song"] for r in changed], [r["anchor"] for r in changed], manifest)
            np.testing.assert_array_equal(matrix, altered)
            self.assertFalse(result["evaluation"]["automatic_promotion"])
            self.assertLess(result["artifact_bytes"], 100000)

    def test_latest_undo_and_canonical_alias_do_not_revive_old_vote(self):
        manifest, records = fixture(30)
        alias = copy.deepcopy(records[0])
        alias.update(liked=None, judged_at="2026-11-01", event_id="undo")
        alias["song"].update(track_id="alias", track_name=" SONG 0 ")
        with tempfile.TemporaryDirectory() as temporary:
            result = train_candidate(records + [alias], temporary, manifest)
            self.assertEqual(result["counts"]["eligible"], 29)
            self.assertEqual(result["excluded"]["not_explicit"], 1)

    def test_same_timestamp_correction_uses_database_sequence_before_uuid(self):
        manifest, records = fixture(30)
        records[0].update(event_sequence=10, event_id="zzzz")
        correction = copy.deepcopy(records[0])
        correction.update(event_sequence=11, event_id="aaaa", liked=None)
        with tempfile.TemporaryDirectory() as temporary:
            result = train_candidate(records + [correction], temporary, manifest)
            self.assertEqual(result["counts"]["eligible"], 29)
            self.assertEqual(result["excluded"]["not_explicit"], 1)

    def test_both_models_share_train_only_balancing_weights(self):
        manifest, records = fixture(150)
        for i, record in enumerate(records):
            record["liked"] = i % 5 != 0
        observed = {}
        mlp_fit, logistic_fit = MLPClassifier.fit, LogisticRegression.fit
        def capture_mlp(model, x, y, **kwargs):
            observed["mlp"] = (y.copy(), kwargs["sample_weight"].copy())
            return mlp_fit(model, x, y, **kwargs)
        def capture_linear(model, x, y, **kwargs):
            observed["logistic"] = (y.copy(), kwargs["sample_weight"].copy())
            return logistic_fit(model, x, y, **kwargs)
        with tempfile.TemporaryDirectory() as temporary, patch.object(
                MLPClassifier, "fit", capture_mlp), patch.object(LogisticRegression, "fit", capture_linear):
            result = train_candidate(records, temporary, manifest)
            self.assertEqual(result["state"], "shadow_ready")
        np.testing.assert_array_equal(observed["mlp"][0], observed["logistic"][0])
        np.testing.assert_array_equal(observed["mlp"][1], observed["logistic"][1])
        labels, weights = observed["mlp"]
        self.assertEqual(len(labels), 120)
        self.assertAlmostEqual(weights[labels == 0].sum(), 60.)
        self.assertAlmostEqual(weights[labels == 1].sum(), 60.)

    def test_self_and_heldout_anchor_leakage_purged(self):
        manifest, records = fixture()
        records[0]["anchor"] = copy.deepcopy(records[0]["song"])
        records[1]["anchor"] = copy.deepcopy(records[-1]["song"])
        with tempfile.TemporaryDirectory() as temporary:
            result = train_candidate(records, temporary, manifest)
            self.assertEqual(result["state"], "shadow_ready")
            self.assertEqual(result["excluded"]["self_anchor"], 1)
            self.assertEqual(result["split"]["purged_training_anchors"], 1)

    def test_invalid_manifest_and_profiles_rejected(self):
        manifest, records = fixture()
        with tempfile.TemporaryDirectory() as temporary:
            invalid = dict(manifest, weights=[])
            with self.assertRaises(ValueError):
                train_candidate(records, temporary, invalid)
            records[0]["profile_id"] = "personal"
            with self.assertRaises(ValueError):
                train_candidate(records, temporary, manifest)

    def test_frozen_manifest_checksum_and_corruption_checked(self):
        manifest, records = fixture()
        with tempfile.TemporaryDirectory() as temporary:
            result = train_candidate(records, temporary, manifest)
            with self.assertRaises(ValueError):
                NeuralScorer.load(temporary, dict(manifest, source_fingerprint="changed"))
            weights = Path(temporary) / result["generation"] / "weights.npz"
            weights.write_bytes(b"corrupt")
            with self.assertRaises(ValueError):
                NeuralScorer.load(temporary, manifest)

    def test_unlearnable_labels_cannot_enable_and_artifacts_bounded(self):
        manifest, records = fixture()
        for record in records:
            record["song"]["energy"] = .5
        with tempfile.TemporaryDirectory() as temporary:
            for _ in range(3):
                result = train_candidate(records, temporary, manifest)
            self.assertFalse(result["evaluation"]["beats_baselines"])
            self.assertFalse(training_status(temporary)["enabled"])
            self.assertEqual(len(list(Path(temporary).glob("generation-*"))), 2)
            pointer = (Path(temporary) / "manifest.json").read_bytes()
            result = train_candidate(records, temporary, manifest, artifact_budget_bytes=1)
            self.assertEqual(result["state"], "artifact_budget_exceeded")
            self.assertEqual((Path(temporary) / "manifest.json").read_bytes(), pointer)
            NeuralScorer.load(temporary, manifest)

    def test_deadline_and_incomplete_scoring(self):
        manifest, records = fixture()
        with tempfile.TemporaryDirectory() as temporary:
            result = train_candidate(records, temporary, manifest, time_budget_seconds=0)
            self.assertEqual(result["state"], "budget_exceeded")
            train_candidate(records, temporary, manifest)
            scorer = NeuralScorer.load(temporary, manifest)
            broken = dict(records[0]["song"], tempo=None)
            self.assertTrue(np.isnan(scorer.score([broken], [records[0]["anchor"]])[0]))

    def test_holdout_missing_one_class_defers_fit(self):
        manifest, records = fixture()
        for record in records[96:]:
            record["liked"] = True
        with tempfile.TemporaryDirectory() as temporary, patch(
                "data.neural_learning.MLPClassifier.fit", side_effect=AssertionError("must not fit")):
            result = train_candidate(records, temporary, manifest)
            self.assertEqual(result["state"], "needs_data")
            self.assertIn("chronological holdout", result["detail"])


if __name__ == "__main__":
    unittest.main()
