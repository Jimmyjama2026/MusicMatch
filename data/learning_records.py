"""Read-only, identity-grouped examples for future offline neural-model training.

Splitting these examples does not train a model or change live profile state.
An evaluator must train a fresh model on the training partition only.
"""
import hashlib
import json
from contextlib import closing
from pathlib import Path
import sqlite3

if __package__:
    from .song_vectors import RAW_FEATURES
    from .identity import song_identity as identity_key
else:
    from song_vectors import RAW_FEATURES
    from identity import song_identity as identity_key


SPLIT_VERSION = "song-identity-holdout-v2"


def partition_examples(examples, evaluation_fraction=.2):
    """Partition audit records by identity; use prepare_model_inputs for clean inputs."""
    if not 0 <= evaluation_fraction < 1:
        raise ValueError("Evaluation fraction must be between zero and one.")
    partitions = {"training": [], "evaluation": [], "exclusion_only": []}
    for example in examples:
        if not example["liked"] and example.get("feedback_reason") in ("Already know it", "Too slow", "Too fast"):
            role = "exclusion_only"
        else:
            digest = hashlib.sha256(json.dumps(identity_key(example["song"])).encode()).digest()
            role = "evaluation" if int.from_bytes(digest[:8], "big") / 2**64 < evaluation_fraction else "training"
        partitions[role].append(dict(example, learning_role=role, split_version=SPLIT_VERSION))
    return partitions


def prepare_model_inputs(partitions):
    """Discard historical ranking outputs and remove held-out likes from all contexts.

    Raw exported records preserve provenance for audit, not direct training. A
    fresh evaluator must rebuild neighborhoods using only these training likes.
    """
    held_out = {identity_key(example["song"]) for example in partitions["evaluation"]}
    def features(song):
        return {"track_id": song["track_id"], "track_name": song["track_name"],
                "artists": song["artists"],
                "measurements": {name: song.get(name) for name in RAW_FEATURES}}
    result = {"training": [], "evaluation": []}
    for role in result:
        for example in partitions[role]:
            result[role].append({"song": features(example["song"]), "liked": example["liked"],
                "favorites": [features(song) for song in example.get("favorites", [])
                              if identity_key(song) not in held_out
                              and identity_key(song) != identity_key(example["song"])],
                "feature_version": example.get("feature_version"),
                "source_fingerprint": example.get("source_fingerprint"),
                "feedback_reason": example.get("feedback_reason"),
                "judged_at": example.get("judged_at"), "event_id": example.get("event_id"),
                "profile_id": example.get("profile_id")})
    return result


def load_examples(db_path, profile_id):
    """Latest vote per track, original song/context snapshots; never migrate/write DB."""
    if profile_id not in ("personal", "test"):
        raise ValueError("Unknown profile.")
    uri = Path(db_path).resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as connection:
        rows = connection.execute("""
            SELECT song_json, liked, reason, batch_id, created_at, favorites_json, model_version, updated_at
            FROM (
                SELECT r.song_json, f.liked, f.reason, b.batch_id, b.created_at,
                       b.favorites_json, b.model_version, f.updated_at,
                       ROW_NUMBER() OVER (PARTITION BY f.track_id
                           ORDER BY f.updated_at DESC, f.rowid DESC) AS rank
                FROM feedback f JOIN recommendations r USING(batch_id, track_id)
                JOIN recommendation_batches b USING(batch_id) WHERE b.profile_id=?
            ) WHERE rank=1 ORDER BY created_at, batch_id
        """, (profile_id,)).fetchall()
    examples = []
    for song_json, liked, reason, batch, created, favorites_json, model, judged in rows:
        song = json.loads(song_json)
        favorites = json.loads(favorites_json)
        examples.append({"song": song, "liked": bool(liked), "feedback_reason": reason,
            "profile_id": profile_id, "batch_id": batch, "shown_at": created,
            "judged_at": judged,
            "favorites": favorites, "model_version": model,
            "feature_version": song.get("feature_version"),
            "source_fingerprint": song.get("source_fingerprint"),
            "neighborhood_context": song.get("neighborhood_context"),
            "evaluation_context_contains_same_song": identity_key(song) in {identity_key(s) for s in favorites}})
    return examples
