"""Versioned, offline audio vectors. Unknown measurements remain explicitly masked."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import uuid

import numpy as np
import pandas as pd

VERSION = "rich-audio-vectors-v2-low-duration"
CONTINUOUS = ("valence", "tempo", "energy", "danceability", "acousticness",
              "instrumentalness", "speechiness", "loudness", "liveness", "duration_ms")
RAW_FEATURES = CONTINUOUS + ("key", "mode", "time_signature")
FEATURE_NAMES = CONTINUOUS + ("key_sin", "key_cos", "mode_minor", "mode_major") + tuple(
    f"meter_{i}" for i in range(1, 8))
WEIGHTS = np.array([1, 1, 1, 1, 1, 1, .7, .4, .35, .03], dtype=np.float64)
TRANSFORM = "bounded features: median centered natural range; tempo/duration: log2; other unbounded: median/IQR clipped +/-3 divided3; sqrt weights"


def _raw(table):
    table = pd.DataFrame(table)
    values = np.column_stack([pd.to_numeric(table.get(name, pd.Series(np.nan, index=table.index)),
                                           errors="coerce").to_numpy(dtype=float)
                              for name in RAW_FEATURES])
    valid = np.isfinite(values)
    for j, name in enumerate(RAW_FEATURES):
        if name in ("tempo", "duration_ms"):
            valid[:, j] &= values[:, j] > 0
        elif name == "loudness":
            valid[:, j] &= (values[:, j] >= -100) & (values[:, j] <= 10)
        elif name == "key":
            valid[:, j] &= (values[:, j] >= 0) & (values[:, j] <= 11) & (values[:, j] == np.floor(values[:, j]))
        elif name == "mode":
            valid[:, j] &= (values[:, j] == 0) | (values[:, j] == 1)
        elif name == "time_signature":
            valid[:, j] &= (values[:, j] >= 1) & (values[:, j] <= 7) & (values[:, j] == np.floor(values[:, j]))
        else:
            valid[:, j] &= (values[:, j] >= 0) & (values[:, j] <= 1)
    values[~valid] = np.nan
    return values, valid


def source_fingerprint(table):
    """Hash ordered IDs and numeric measurements; nonnumeric values canonicalize to NaN."""
    table = pd.DataFrame(table)
    canonical = table.reindex(columns=("track_id",) + RAW_FEATURES).copy()
    canonical["track_id"] = canonical["track_id"].astype(str)
    for name in RAW_FEATURES:
        canonical[name] = pd.to_numeric(canonical[name], errors="coerce").astype("float64")
    digest = hashlib.sha256()
    digest.update(json.dumps(list(canonical.columns)).encode())
    digest.update(pd.util.hash_pandas_object(canonical, index=False).values.tobytes())
    return digest.hexdigest()


class SongVectors:
    @classmethod
    def build(cls, table):
        table = pd.DataFrame(table)
        if table.empty or "track_id" not in table:
            raise ValueError("Song vectors require nonempty songs with stable track IDs.")
        ids = np.asarray(table["track_id"].astype(str), dtype=str)
        if table["track_id"].isna().any() or any(not item.strip() for item in ids) or len(set(ids)) != len(ids):
            raise ValueError("Song vector IDs must be nonempty and unique.")
        values, valid = _raw(table)
        centers, scales = [], []
        for j, name in enumerate(CONTINUOUS):
            observed = values[valid[:, j], j]
            if name in ("tempo", "duration_ms"):
                observed = np.log2(observed)
            if not len(observed):
                raise ValueError(f"Cannot fit vectors: no valid {name} measurements.")
            q1, median, q3 = np.percentile(observed, [25, 50, 75])
            # A constant feature contributes zero until a subsequent version rebuild.
            centers.append(float(median))
            # Unit-scale measurements already have a meaningful common range.
            # IQR scaling would saturate instrumentalness because most values are near zero.
            scales.append(1 / 3 if name not in ("tempo", "duration_ms", "loudness") else float(q3 - q1))
        self = cls()
        self.metadata = {"version": VERSION, "source_fingerprint": source_fingerprint(table),
                         "rows": len(table), "raw_features": list(RAW_FEATURES),
                         "feature_names": list(FEATURE_NAMES), "centers": centers,
                         "scales": scales, "weights": WEIGHTS.tolist(),
                         "active_continuous_features": [name for name, scale in zip(CONTINUOUS, scales) if scale > 1e-12],
                         "transform": TRANSFORM,
                         "invalid_counts": {name: int((~valid[:, j]).sum()) for j, name in enumerate(RAW_FEATURES)}}
        self.track_ids = ids
        self.feature_names = FEATURE_NAMES
        self.matrix, self.validity = self.transform(table)
        return self

    def transform(self, songs):
        values, valid = _raw(songs)
        output = np.zeros((len(values), len(FEATURE_NAMES)), dtype=np.float32)
        for j, name in enumerate(CONTINUOUS):
            observed = values[:, j].copy()
            if name in ("tempo", "duration_ms"):
                observed = np.log2(observed)
            scale = self.metadata["scales"][j]
            if scale > 1e-12:
                output[:, j] = np.where(valid[:, j], np.clip(
                    (observed - self.metadata["centers"][j]) / scale, -3, 3) / 3 * np.sqrt(WEIGHTS[j]), 0)
        key = np.nan_to_num(values[:, 10]) * 2 * np.pi / 12
        output[:, 10] = np.where(valid[:, 10], np.sin(key) * np.sqrt(.08), 0)
        output[:, 11] = np.where(valid[:, 10], np.cos(key) * np.sqrt(.08), 0)
        for mode in range(2):
            output[:, 12 + mode] = (valid[:, 11] & (values[:, 11] == mode)) * np.sqrt(.04 / 2)
        for meter in range(1, 8):
            output[:, 13 + meter] = (valid[:, 12] & (values[:, 12] == meter)) * np.sqrt(.04 / 2)
        return output, valid

    @property
    def dimension_validity(self):
        return self.expand_validity(self.validity)

    @staticmethod
    def expand_validity(valid):
        return np.column_stack((valid[:, :10], valid[:, 10], valid[:, 10],
                                valid[:, 11], valid[:, 11], *([valid[:, 12]] * 7)))

    @property
    def coverage(self):
        return self.validity.mean(axis=1)

    def save(self, directory):
        """Publish a complete generation by atomically replacing a tiny pointer manifest."""
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        generation = "generation-" + uuid.uuid4().hex
        staging = Path(tempfile.mkdtemp(prefix=".building-", dir=directory))
        pointer_temp = directory / (".manifest-" + uuid.uuid4().hex)
        try:
            np.savez_compressed(staging / "vectors.npz", matrix=self.matrix,
                                validity=self.validity, track_ids=self.track_ids.astype(str))
            metadata = dict(self.metadata)
            metadata["array_sha256"] = hashlib.sha256((staging / "vectors.npz").read_bytes()).hexdigest()
            (staging / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
            os.replace(staging, directory / generation)
            pointer_temp.write_text(json.dumps({"generation": generation}), encoding="utf-8")
            os.replace(pointer_temp, directory / "manifest.json")
        finally:
            if staging.exists():
                shutil.rmtree(staging)
            pointer_temp.unlink(missing_ok=True)

    @classmethod
    def load(cls, directory, table=None):
        directory = Path(directory)
        pointer = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        generation = pointer["generation"]
        if not isinstance(generation, str) or not generation.startswith("generation-") or Path(generation).name != generation:
            raise ValueError("Invalid vector generation path.")
        base = directory / generation
        metadata = json.loads((base / "metadata.json").read_text(encoding="utf-8"))
        if (metadata.get("version") != VERSION or metadata.get("feature_names") != list(FEATURE_NAMES)
                or metadata.get("raw_features") != list(RAW_FEATURES) or metadata.get("weights") != WEIGHTS.tolist()
                or metadata.get("transform") != TRANSFORM):
            raise ValueError("Vector index version is unsupported; rebuild it offline.")
        if table is not None and metadata.get("source_fingerprint") != source_fingerprint(table):
            raise ValueError("Vector index is stale; rebuild it offline.")
        if hashlib.sha256((base / "vectors.npz").read_bytes()).hexdigest() != metadata.get("array_sha256"):
            raise ValueError("Vector index checksum mismatch.")
        with np.load(base / "vectors.npz", allow_pickle=False) as arrays:
            matrix, validity, ids = arrays["matrix"], arrays["validity"], arrays["track_ids"]
        if (matrix.shape != (metadata["rows"], len(FEATURE_NAMES)) or matrix.dtype != np.float32 or
                validity.shape != (len(matrix), len(RAW_FEATURES)) or validity.dtype != bool or
                ids.shape != (len(matrix),) or ids.dtype.kind != "U" or len(set(ids)) != len(ids)
                or any(not item.strip() for item in ids) or not np.isfinite(matrix).all()):
            raise ValueError("Vector index arrays are invalid.")
        if table is not None and not np.array_equal(ids, pd.DataFrame(table)["track_id"].astype(str).to_numpy()):
            raise ValueError("Vector index song IDs are misaligned with the source table.")
        if len(metadata.get("centers", [])) != 10 or len(metadata.get("scales", [])) != 10 or not np.isfinite(
                metadata["centers"] + metadata["scales"]).all() or any(s < 0 for s in metadata["scales"]):
            raise ValueError("Vector transformation settings are invalid.")
        self = cls()
        self.metadata, self.matrix, self.validity, self.track_ids = metadata, matrix, validity, ids
        self.feature_names = FEATURE_NAMES
        return self
