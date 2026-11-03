"""Small, bounded CPU shadow learner. Never promotes a model into live ranking.

Inputs are measured audio and historical anchor snapshots, not identities, artist
names, reasons, ranking outputs, or outcomes. Artifacts contain arrays and JSON;
loading never executes pickle. Callers must enforce the worker process deadline.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
import uuid
import warnings

import numpy as np
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

from .identity import credited_artists, song_identity
from .song_vectors import FEATURE_NAMES, RAW_FEATURES, TRANSFORM, VERSION, WEIGHTS, SongVectors
from .genres import effective_labels, effective_evidence

MODEL_VERSION = "contextual-shadow-mlp-v3-favorite-positives"
GENRE_BUCKETS = 64
INPUT_WIDTH = 82 + 3 * GENRE_BUCKETS + 10
GENRE_CONTRACT = {"version": "genre-inputs-v1", "buckets": GENRE_BUCKETS,
                  "encoding": "sha256-first8-mod64-binary; candidate,anchor,intersection",
                  "summary": ["candidate_known", "anchor_known", "both_known", "overlap", "jaccard", "disjoint_known",
                              "candidate_recording", "candidate_artist", "anchor_recording", "anchor_artist"],
                  "missing": "explicit unknown; no historical metadata backfill"}
GENRE_CONTRACT["favorite_inputs"] = "anchorless positives; masked-anchor training views for both vote classes"
EXCLUDED_REASONS = {"Already know it", "Too slow", "Too fast"}


def _manifest(manifest):
    manifest = dict(manifest)
    if (manifest.get("version") != VERSION
            or manifest.get("feature_names") != list(FEATURE_NAMES)
            or manifest.get("raw_features") != list(RAW_FEATURES)
            or manifest.get("weights") != WEIGHTS.tolist()
            or manifest.get("transform") != TRANSFORM
            or not manifest.get("source_fingerprint")):
        raise ValueError("Unsupported or missing audio feature manifest.")
    values = manifest.get("centers", []) + manifest.get("scales", [])
    if (len(manifest.get("centers", [])) != 10 or len(manifest.get("scales", [])) != 10
            or not np.isfinite(values).all() or any(x < 0 for x in manifest["scales"])):
        raise ValueError("Invalid audio transform settings.")
    # Ignore storage checksums and catalog row counts in the model's contract.
    return {k: manifest[k] for k in ("version", "source_fingerprint", "feature_names",
            "raw_features", "weights", "transform", "centers", "scales")}


def _fingerprint(manifest):
    return hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()


def record_features_compatible(record, feature_manifest):
    """Allow the one documented v1->v2 raw-snapshot migration.

    v2 only reduced duration's weight. Duration never enters the audio model
    inputs, and identical source fingerprints preserve the same other fitted
    transforms. Reproject the raw snapshot with current settings; checkpoints
    themselves still require an exact current manifest on load.
    """
    manifest = _manifest(feature_manifest)
    if record.get("source_fingerprint") != manifest["source_fingerprint"]:
        return False
    if record.get("feature_version") == manifest["version"]:
        return True
    return (record.get("feature_version") == "rich-audio-vectors-v1"
            and manifest["version"] == "rich-audio-vectors-v2-low-duration"
            and manifest["weights"] == [1., 1., 1., 1., 1., 1., .7, .4, .35, .03])


def _song(song):
    return dict(song, **song.get("measurements", {})) if song else {}


def _event_order(record):
    """Database sequence resolves same-timestamp corrections before UUID fallback."""
    sequence = record.get("event_sequence", 0)
    if not isinstance(sequence, int) or isinstance(sequence, bool):
        sequence = 0
    return str(record.get("judged_at", "")), sequence, str(record.get("event_id", ""))


def feature_matrix(songs, anchors, feature_manifest):
    """Audio and frozen genre evidence; identities and outcomes never enter inputs."""
    if len(songs) != len(anchors):
        raise ValueError("Each candidate needs its historical anchor.")
    transformer = SongVectors()
    transformer.metadata = _manifest(feature_manifest)
    if not songs:
        return np.empty((0, INPUT_WIDTH)), np.empty(0, dtype=bool)
    candidate, cmask = transformer.transform([_song(s) for s in songs])
    anchor, amask = transformer.transform([_song(s) for s in anchors])
    # Duration remains in the versioned source snapshot but never enters this learner.
    candidate = np.delete(candidate, 9, axis=1)
    anchor = np.delete(anchor, 9, axis=1)
    missing_anchor = np.asarray([a is None for a in anchors], dtype=bool)
    delta = candidate - anchor
    # Missing context is not a zero-valued measured anchor or an invented self-match.
    anchor[missing_anchor] = 0.
    delta[missing_anchor] = 0.
    matrix = np.column_stack((candidate, anchor, delta, np.abs(delta),
                              cmask.mean(axis=1), amask.mean(axis=1))).astype(float)
    genre_matrix = np.zeros((len(songs), INPUT_WIDTH - 82), dtype=float)
    for i, (song, seed) in enumerate(zip(songs, anchors)):
        left, right = effective_labels(song), effective_labels(seed or {})
        common = left & right
        for block, tags in enumerate((left, right, common)):
            for tag in tags:
                bucket = int.from_bytes(hashlib.sha256(tag.encode("utf-8")).digest()[:8], "big") % GENRE_BUCKETS
                genre_matrix[i, block * GENRE_BUCKETS + bucket] = 1.
        candidate_level, anchor_level = effective_evidence(song).get("level"), effective_evidence(seed or {}).get("level")
        genre_matrix[i, -10:] = [bool(left), bool(right), bool(left and right), bool(common),
            len(common) / len(left | right) if left or right else 0., bool(left and right and not common),
            candidate_level == "recording", candidate_level == "artist",
            anchor_level == "recording", anchor_level == "artist"]
    matrix = np.column_stack((matrix, genre_matrix))
    return matrix, cmask.all(axis=1) & (amask.all(axis=1) | missing_anchor)


def training_status(output_dir):
    path = Path(output_dir) / "status.json"
    if not path.exists():
        return {"state": "not_started", "mode": "shadow", "enabled": False}
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
        result["enabled"] = False  # This implementation has no promotion pathway.
        return result
    except (ValueError, OSError):
        return {"state": "invalid_status", "mode": "shadow", "enabled": False}


def _write_json(path, value):
    temporary = path.with_name("." + path.name + "-" + uuid.uuid4().hex)
    try:
        temporary.write_text(json.dumps(value, indent=2, allow_nan=False), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def train_candidate(records, output_dir, feature_manifest, *, min_judgments=100,
                    min_per_class=20, min_anchor_families=3, max_iter=100,
                    time_budget_seconds=10, artifact_budget_bytes=50 * 1024**2):
    """Train against a newer-song holdout; produce a shadow artifact only.

    Latest judgment wins per canonical recording identity. All observations of a
    held-out identity stay outside training, including training anchor contexts.
    A caller must pass records from exactly one profile into its private directory.
    """
    start = time.monotonic()
    manifest = _manifest(feature_manifest)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    profiles = {r.get("profile_id") for r in records if r.get("profile_id")}
    if len(profiles) > 1:
        raise ValueError("Training profiles must remain isolated.")
    report = {"version": MODEL_VERSION, "state": "needs_data", "mode": "shadow",
              "genre_feature_contract": GENRE_CONTRACT,
              "enabled": False, "feature_fingerprint": _fingerprint(manifest),
              "profile_id": next(iter(profiles), None),
              "requirements": {"unique_judgments": min_judgments,
                  "per_class": min_per_class, "anchor_artist_families": min_anchor_families},
              "excluded": {}}

    def finish(state, **fields):
        report.update(state=state, elapsed_seconds=time.monotonic() - start, **fields)
        _write_json(output / "status.json", report)
        return report

    latest = {}
    # Sort raw events before filtering so an undo/correction cannot revive an old vote.
    for record in sorted(records, key=_event_order):
        if record.get("song"):
            latest[song_identity(record["song"])] = record
    eligible = []
    for record in latest.values():
        reason = record.get("reason", record.get("feedback_reason"))
        cause = None
        if record.get("liked") not in (True, False, 0, 1) or record.get("liked") is None:
            cause = "not_explicit"
        elif reason in EXCLUDED_REASONS:
            cause = "direction_or_familiarity"
        elif (not record.get("anchor") and record.get("judgment_source") != "favorite") or not record.get("judged_at"):
            cause = "missing_historical_context"
        elif not record_features_compatible(record, manifest):
            cause = "stale_features"
        elif record.get("anchor") and song_identity(record["song"]) == song_identity(record["anchor"]):
            cause = "self_anchor"
        if cause:
            report["excluded"][cause] = report["excluded"].get(cause, 0) + 1
        else:
            eligible.append(record)
    eligible.sort(key=_event_order)
    matrix, complete = feature_matrix([r["song"] for r in eligible], [r["anchor"] for r in eligible], manifest)
    report["excluded"]["missing_measurements"] = int((~complete).sum())
    eligible = [r for r, ok in zip(eligible, complete) if ok]
    matrix = matrix[complete]
    labels = np.array([bool(r["liked"]) for r in eligible], dtype=int)
    families = {credited_artists(r.get("anchor") or r["song"]) for r in eligible if credited_artists(r.get("anchor") or r["song"])}
    report["counts"] = {"eligible": len(eligible), "yes": int(labels.sum()),
                        "no": int(len(labels) - labels.sum()), "anchor_families": len(families),
                        "genre_known_candidates": sum(bool(effective_labels(r["song"])) for r in eligible),
                        "genre_known_anchors": sum(bool(effective_labels(r.get("anchor") or {})) for r in eligible),
                        "genre_known_pairs": sum(bool(effective_labels(r["song"]) and effective_labels(r.get("anchor") or {})) for r in eligible),
                        "favorite_positives": sum(r.get("judgment_source") == "favorite" for r in eligible)}
    if (len(labels) < min_judgments or min(np.bincount(labels, minlength=2)) < min_per_class
            or len(families) < min_anchor_families):
        return finish("needs_data")
    cutoff = int(len(eligible) * .8)
    held = {song_identity(r["song"]) for r in eligible[cutoff:]}
    train_ids = [i for i, r in enumerate(eligible[:cutoff]) if not r.get("anchor") or song_identity(r["anchor"]) not in held]
    test_ids = list(range(cutoff, len(eligible)))
    report["split"] = {"policy": "latest-identity-chronological-80-20-purge-heldout-anchors",
        "training": len(train_ids), "evaluation": len(test_ids),
        "purged_training_anchors": cutoff - len(train_ids),
        "cutoff_judged_at": eligible[cutoff]["judged_at"]}
    if (len(test_ids) < 10 or any(min(np.bincount(labels[ids], minlength=2)) < 3
                                 for ids in (train_ids, test_ids))):
        return finish("needs_data", detail="Need both classes in the chronological holdout.")
    if time.monotonic() - start >= time_budget_seconds:
        return finish("budget_exceeded")
    with threadpool_limits(limits=1), warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", ConvergenceWarning)
        training_matrix = matrix[train_ids]
        training_labels = labels[train_ids]
        if any(r.get("judgment_source") == "favorite" for r in eligible):
            # Without negative masked views, missing anchor context would reveal
            # the positive label of search-added favorites. Augment TRAIN only.
            contextual_ids = [i for i in train_ids if eligible[i].get("anchor")]
            if contextual_ids:
                masked, _ = feature_matrix([eligible[i]["song"] for i in contextual_ids], [None] * len(contextual_ids), manifest)
                training_matrix = np.vstack((training_matrix, masked))
                training_labels = np.concatenate((training_labels, labels[contextual_ids]))
                report["split"]["masked_training_views"] = len(contextual_ids)
        scaler = StandardScaler().fit(training_matrix)
        xtrain, xtest = scaler.transform(training_matrix), scaler.transform(matrix[test_ids])
        # Both baselines receive the same TRAIN-ONLY class balancing. Holdout
        # outcomes never affect weights, normalization, or hyperparameters.
        class_counts = np.bincount(training_labels, minlength=2)
        sample_weights = len(training_labels) / (2 * class_counts[training_labels])
        linear = LogisticRegression(C=.1, max_iter=max_iter, random_state=42).fit(
            xtrain, training_labels, sample_weight=sample_weights)
        neural = MLPClassifier(hidden_layer_sizes=(16,), activation="tanh", solver="lbfgs",
            alpha=1., max_iter=max_iter, max_fun=500, random_state=42).fit(
                xtrain, training_labels, sample_weight=sample_weights)
        prediction = neural.predict_proba(xtest)[:, 1]
        linear_prediction = linear.predict_proba(xtest)[:, 1]
    if time.monotonic() - start >= time_budget_seconds:
        return finish("budget_exceeded")
    neural_auc = float(roc_auc_score(labels[test_ids], prediction))
    linear_auc = float(roc_auc_score(labels[test_ids], linear_prediction))
    baseline = [eligible[i].get("heuristic_score") for i in test_ids]
    baseline_available = all(isinstance(x, (int, float)) and np.isfinite(x) for x in baseline)
    baseline_auc = float(roc_auc_score(labels[test_ids], -np.array(baseline))) if baseline_available else None
    report["evaluation"] = {"metric": "identity-heldout ROC AUC (not a full-list ranking metric)",
        "neural_auc": neural_auc, "logistic_auc": linear_auc, "heuristic_auc": baseline_auc,
        "heuristic_available": baseline_available,
        "beats_baselines": baseline_available and neural_auc > max(linear_auc, baseline_auc) + .01,
        "convergence_warning": any(issubclass(w.category, ConvergenceWarning) for w in caught),
        "automatic_promotion": False}
    # Preserve a reproducible scorer even if it loses; it remains strictly shadow.
    generation = "generation-" + uuid.uuid4().hex
    staging = Path(tempfile.mkdtemp(prefix=".training-", dir=output))
    try:
        np.savez_compressed(staging / "weights.npz", mean=scaler.mean_, scale=scaler.scale_,
                            w0=neural.coefs_[0], b0=neural.intercepts_[0],
                            w1=neural.coefs_[1], b1=neural.intercepts_[1])
        metadata = {"version": MODEL_VERSION, "feature_manifest": manifest,
                    "feature_fingerprint": _fingerprint(manifest), "mode": "shadow", "enabled": False,
                    "input_width": INPUT_WIDTH, "hidden_width": 16, "genre_feature_contract": GENRE_CONTRACT,
                    "array_sha256": hashlib.sha256((staging / "weights.npz").read_bytes()).hexdigest()}
        _write_json(staging / "metadata.json", metadata)
        _write_json(staging / "evaluation.json", report)
        size = sum(p.stat().st_size for p in staging.iterdir())
        # Retain at most two generations and enforce total artifact budget before publish.
        generations = sorted(output.glob("generation-*"), key=lambda p: p.stat().st_mtime)
        if size > artifact_budget_bytes:
            return finish("artifact_budget_exceeded")
        # Never delete a currently published model to make room for its replacement.
        existing_size = sum(p.stat().st_size for g in generations for p in g.iterdir())
        if existing_size + size > artifact_budget_bytes:
            return finish("artifact_budget_exceeded")
        os.replace(staging, output / generation)
        _write_json(output / "manifest.json", {"generation": generation})
        while len(generations) >= 2:
            shutil.rmtree(generations.pop(0))
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return finish("shadow_ready", generation=generation, parameter_count=sum(
        x.size for x in neural.coefs_ + neural.intercepts_), artifact_bytes=size)


class NeuralScorer:
    """NumPy-only inference for experiments; not an active ranking override."""
    @classmethod
    def load(cls, output_dir, feature_manifest):
        output = Path(output_dir)
        pointer = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
        generation = pointer["generation"]
        if (not isinstance(generation, str) or not generation.startswith("generation-")
                or Path(generation).name != generation):
            raise ValueError("Invalid model generation path.")
        base = output / generation
        metadata = json.loads((base / "metadata.json").read_text(encoding="utf-8"))
        if (metadata.get("version") != MODEL_VERSION
                or metadata.get("genre_feature_contract") != GENRE_CONTRACT
                or metadata.get("input_width") != INPUT_WIDTH
                or metadata.get("feature_fingerprint") != _fingerprint(_manifest(feature_manifest))
                or metadata.get("mode") != "shadow"):
            raise ValueError("Model does not match the current feature manifest.")
        if hashlib.sha256((base / "weights.npz").read_bytes()).hexdigest() != metadata.get("array_sha256"):
            raise ValueError("Model checksum mismatch.")
        self = cls()
        self.manifest = _manifest(feature_manifest)
        with np.load(base / "weights.npz", allow_pickle=False) as arrays:
            self.arrays = {key: arrays[key].copy() for key in ("mean", "scale", "w0", "b0", "w1", "b1")}
        expected = {"mean": (INPUT_WIDTH,), "scale": (INPUT_WIDTH,), "w0": (INPUT_WIDTH, 16), "b0": (16,), "w1": (16, 1), "b1": (1,)}
        if (any(value.shape != expected[key] or not np.isfinite(value).all() for key, value in self.arrays.items())
                or np.any(self.arrays["scale"] <= 0)):
            raise ValueError("Invalid model arrays.")
        return self

    def predict_matrix(self, matrix):
        matrix = np.asarray(matrix, dtype=float)
        if matrix.ndim != 2 or matrix.shape[1] != INPUT_WIDTH or not np.isfinite(matrix).all():
            raise ValueError("Invalid numerical model inputs.")
        a = self.arrays
        logits = np.tanh(((matrix - a["mean"]) / a["scale"]) @ a["w0"] + a["b0"]) @ a["w1"] + a["b1"]
        return 1 / (1 + np.exp(-np.clip(logits[:, 0], -700, 700)))

    def score(self, songs, anchors):
        matrix, eligible = feature_matrix(songs, anchors, self.manifest)
        scores = np.full(len(songs), np.nan)
        scores[eligible] = self.predict_matrix(matrix[eligible])
        return scores

