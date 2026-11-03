"""Bounded request steering and local pairwise evidence; no model training."""
import math
import numpy as np

STEERING = ("same", "slower", "faster", "energetic", "less_artist")
POLICY_VERSION = "request-preferences-v1"


class PairEvidence(list):
    """Small evidence list with a compiled, deduplicated seed matrix."""


def validate_steering(value):
    if value not in STEERING:
        raise ValueError("Unknown request steering option.")
    return value


def steering_target(anchor, option):
    validate_steering(option)
    feature = "tempo" if option in ("slower", "faster") else "energy" if option == "energetic" else None
    if feature is None:
        return None
    try:
        original = float(anchor[feature])
    except (KeyError, TypeError, ValueError):
        return None
    if not math.isfinite(original) or (feature == "tempo" and original <= 0) or (feature == "energy" and not 0 <= original <= 1):
        return None
    target = original * (.9 if option == "slower" else 1.1) if feature == "tempo" else min(1., original + .10)
    return {"feature": feature, "original": original, "target": target,
            "scale": original * .2 if feature == "tempo" else .2}


def steering_adjustment(values, target, bound=.025):
    values = np.asarray(values, dtype=float)
    if target is None:
        return np.zeros(len(values), dtype=np.float32)
    adjustment = bound * np.clip((np.abs(values - target["target"]) - np.abs(values - target["original"])) / target["scale"], -1, 1)
    adjustment[~np.isfinite(values)] = 0
    return adjustment.astype(np.float32)


def prepare_pairs(records, vectors):
    """Latest unique ordered context pairs; invalid/equal records have no effect."""
    prepared, seen = PairEvidence(), set()
    for record in records or ():
        if not isinstance(record, dict) or record.get("choice") not in ("a", "b", "equal"):
            continue
        songs = [record.get(name) for name in ("winner", "loser", "anchor")]
        if not all(isinstance(song, dict) and song.get("track_id") for song in songs):
            continue
        winner, loser, anchor = songs
        expected_version = vectors.metadata.get("feature_version", vectors.metadata.get("version"))
        expected_source = vectors.metadata.get("source_fingerprint")
        if any((song.get("feature_version") is not None and song["feature_version"] != expected_version)
               or (song.get("source_fingerprint") is not None and song["source_fingerprint"] != expected_source)
               for song in songs):
            continue
        if winner["track_id"] == loser["track_id"]:
            continue
        key = (anchor["track_id"], tuple(sorted((winner["track_id"], loser["track_id"]))))
        if key in seen:
            continue
        seen.add(key)
        if record["choice"] == "equal":
            continue
        matrix, validity = vectors.transform(songs)
        if not ((validity.mean(axis=1) >= .70) & (validity[:, :10].sum(axis=1) >= 7)).all():
            continue
        prepared.append((matrix, vectors.expand_validity(validity), {name: dict(song) for name, song in zip(("winner", "loser", "anchor"), songs)}))
        if len(prepared) >= 32:
            break
    seeds, masks, positions, unique = [], [], [], {}
    for matrix, validity, _ in prepared:
        locations = []
        for row, mask in zip(matrix, validity):
            key = (row.tobytes(), mask.tobytes())
            if key not in unique:
                unique[key] = len(seeds)
                seeds.append(row)
                masks.append(mask)
            locations.append(unique[key])
        positions.append(locations)
    prepared.seed_matrix = np.asarray(seeds)
    prepared.seed_masks = np.asarray(masks)
    prepared.positions = np.asarray(positions, dtype=np.int32)
    return prepared


def pairwise_adjustment(matrix, masks, pairs, distance, radius=.10, bound=.02):
    distances = distance(matrix, masks, pairs.seed_matrix, pairs.seed_masks)
    winners, losers, anchors = (distances[:, pairs.positions[:, column]] for column in range(3))
    eligible = np.isfinite(winners) & np.isfinite(losers) & np.isfinite(anchors) & (anchors <= radius)
    # One bounded chunk × unique-seeds matrix, sharing repeated context anchors.
    preference = np.exp(-losers ** 2 / .01) - np.exp(-winners ** 2 / .01)
    total = np.where(eligible, preference, 0).sum(axis=1)
    active = eligible.sum(axis=1)
    return bound * total / np.maximum(active, 1), active
