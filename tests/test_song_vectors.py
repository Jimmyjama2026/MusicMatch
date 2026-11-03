import json
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from data.song_vectors import RAW_FEATURES, SongVectors


def songs():
    return pd.DataFrame([dict(track_id=str(i), valence=.1 + i * .1, tempo=60 + i * 15,
        energy=.15 + i * .1, danceability=.2 + i * .1, acousticness=.3 + i * .05,
        instrumentalness=.05 + i * .1, speechiness=.05 + i * .05, loudness=-25 + i * 3,
        liveness=.1 + i * .1, duration_ms=120000 + i * 20000, key=i, mode=i % 2,
        time_signature=3 + i % 2) for i in range(6)])


class SongVectorTests(unittest.TestCase):
    def test_duration_has_one_tenth_its_original_squared_distance_weight(self):
        index = SongVectors.build(songs())
        seed = songs().iloc[[0]].copy()
        longer = seed.copy()
        longer["duration_ms"] *= 2
        matrix, _ = index.transform(pd.concat([seed, longer]))
        actual = float((matrix[1, 9] - matrix[0, 9]) ** 2)
        scale = index.metadata["scales"][9]
        raw_delta = np.log2(2) / scale / 3
        # The old squared contribution was raw_delta**2 * .3.
        self.assertAlmostEqual(actual, raw_delta ** 2 * .03, places=6)
        np.testing.assert_array_equal(matrix[0, :9], matrix[1, :9])
        self.assertEqual(index.metadata["weights"][9], .03)

    def test_roundtrip_and_source_mutation_detection(self):
        table = songs()
        index = SongVectors.build(table)
        with tempfile.TemporaryDirectory() as temporary:
            index.save(temporary)
            loaded = SongVectors.load(temporary, table=table)
            np.testing.assert_array_equal(index.matrix, loaded.matrix)
            np.testing.assert_array_equal(index.track_ids, loaded.track_ids)
            changed = table.copy()
            changed.loc[0, "acousticness"] = .99
            with self.assertRaisesRegex(ValueError, "stale"):
                SongVectors.load(temporary, table=changed)
            with self.assertRaisesRegex(ValueError, "stale"):
                SongVectors.load(temporary, table=table.iloc[::-1])

    def test_key_wrap_and_categorical_meter(self):
        index = SongVectors.build(songs())
        seed = songs().iloc[[0]].copy()
        near, far = seed.copy(), seed.copy()
        seed["key"], near["key"], far["key"] = 0, 11, 6
        vectors, valid = index.transform(pd.concat([seed, near, far]))
        self.assertLess(np.linalg.norm(vectors[0, 10:12] - vectors[1, 10:12]),
                        np.linalg.norm(vectors[0, 10:12] - vectors[2, 10:12]))
        seed["time_signature"], near["time_signature"], far["time_signature"] = 3, 4, 7
        vectors, _ = index.transform(pd.concat([seed, near, far]))
        self.assertAlmostEqual(float(np.linalg.norm(vectors[0, 14:] - vectors[1, 14:])),
                               float(np.linalg.norm(vectors[0, 14:] - vectors[2, 14:])))

    def test_missing_and_invalid_never_fake_evidence(self):
        index = SongVectors.build(songs())
        changed = songs().iloc[[0]].copy()
        for name, value in (("energy", 4), ("key", -1), ("mode", 3), ("tempo", 0),
                            ("time_signature", 4.5), ("acousticness", np.nan)):
            changed[name] = value
        vectors, valid = index.transform(changed)
        dims = index.expand_validity(valid)
        self.assertEqual(dims.shape, vectors.shape)
        self.assertFalse(valid[0, 1])
        self.assertFalse(valid[0, 10])
        self.assertTrue(np.isfinite(vectors).all())
        self.assertTrue((vectors[~dims] == 0).all())

    def test_robust_scale_bounds_extremes_and_constant_columns(self):
        table = songs()
        table["duration_ms"] = 100000
        index = SongVectors.build(table)
        changed = songs().iloc[[0]].copy()
        changed["tempo"] = 1e100
        vectors, _ = index.transform(changed)
        self.assertLessEqual(abs(float(vectors[0, 1])), 1)
        self.assertEqual(float(vectors[0, 9]), 0)
        self.assertEqual(index.matrix.dtype, np.float32)

    def test_checksum_rejects_tampering(self):
        index = SongVectors.build(songs())
        with tempfile.TemporaryDirectory() as temporary:
            index.save(temporary)
            base = Path(temporary) / json.loads((Path(temporary) / "manifest.json").read_text())["generation"]
            with (base / "vectors.npz").open("ab") as output:
                output.write(b"corrupted")
            with self.assertRaisesRegex(ValueError, "checksum"):
                SongVectors.load(temporary)

    def test_verified_array_ids_must_align_with_table(self):
        index = SongVectors.build(songs())
        with tempfile.TemporaryDirectory() as temporary:
            index.save(temporary)
            base = Path(temporary) / json.loads((Path(temporary) / "manifest.json").read_text())["generation"]
            np.savez_compressed(base / "vectors.npz", matrix=index.matrix,
                                validity=index.validity, track_ids=index.track_ids[::-1])
            metadata = json.loads((base / "metadata.json").read_text())
            metadata["array_sha256"] = hashlib.sha256((base / "vectors.npz").read_bytes()).hexdigest()
            (base / "metadata.json").write_text(json.dumps(metadata))
            with self.assertRaisesRegex(ValueError, "misaligned"):
                SongVectors.load(temporary, table=songs())

    def test_skewed_instrumentalness_preserves_high_value_distinctions(self):
        table = songs()
        table["instrumentalness"] = [0, 0, 0, .00001, .1, .9]
        index = SongVectors.build(table)
        self.assertGreater(float(index.matrix[-1, 5] - index.matrix[-2, 5]), .7)

    def test_interrupted_publish_preserves_previous_generation(self):
        index = SongVectors.build(songs())
        with tempfile.TemporaryDirectory() as temporary:
            index.save(temporary)
            import os
            real_replace = os.replace
            def fail_pointer(source, target):
                if Path(target).name == "manifest.json":
                    raise OSError("simulated interruption")
                return real_replace(source, target)
            with patch("data.song_vectors.os.replace", side_effect=fail_pointer):
                with self.assertRaises(OSError):
                    index.save(temporary)
            loaded = SongVectors.load(temporary)
            np.testing.assert_array_equal(index.matrix, loaded.matrix)

    def test_duplicate_ids_rejected_and_missing_column_cannot_fit(self):
        table = songs()
        table.loc[1, "track_id"] = "0"
        with self.assertRaises(ValueError):
            SongVectors.build(table)
        with self.assertRaisesRegex(ValueError, "acousticness"):
            SongVectors.build(songs().drop(columns="acousticness"))


if __name__ == "__main__":
    unittest.main()
