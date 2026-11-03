"""Build a small, contextual comparison without turning preference into dislike."""
import hashlib
import json
import math
from copy import deepcopy

if __package__:
    from .identity import song_identity
    from .song_vectors import RAW_FEATURES
else:
    from identity import song_identity
    from song_vectors import RAW_FEATURES

SNAPSHOT_FIELDS = set(RAW_FEATURES) | {
    "track_id", "track_name", "artists", "id_artists", "artist_mbids",
    "feature_version", "source_fingerprint", "recording_mbid",
    "genre_evidence", "artist_genre_evidence",
}


def snapshot(song):
    return {key: deepcopy(value) for key, value in song.items() if key in SNAPSHOT_FIELDS}


def candidate_pair(songs, seen_keys=()):
    """Choose comparably scored songs with the same actual matched anchor.

    A request offers at most one pair. Seen pairs are keyed independently of
    left/right order, aliases and batch IDs, and scoped by the feature source.
    """
    seen = set(seen_keys)
    candidates = []
    for song in songs:
        anchor = song.get("matched_anchor")
        distance, score = song.get("distance"), song.get("ranking_score")
        if (song.get("liked") is not None or not anchor or not anchor.get("track_id")
                or not all(isinstance(value, (int, float)) and not isinstance(value, bool)
                           and math.isfinite(value) for value in (distance, score))
                or not 0 <= distance <= .10):
            continue
        candidates.append(song)
    pairs = []
    for index, a in enumerate(candidates):
        for b in candidates[index + 1:]:
            if (song_identity(a) == song_identity(b)
                    or song_identity(a["matched_anchor"]) != song_identity(b["matched_anchor"])
                    or a.get("source_fingerprint") != b.get("source_fingerprint")
                    or a.get("feature_version") != b.get("feature_version")):
                continue
            gap = abs(a["ranking_score"] - b["ranking_score"])
            if gap > .08:
                continue
            ordered = sorted((a, b), key=lambda s: json.dumps(song_identity(s)))
            identity = [song_identity(a["matched_anchor"]),
                        [song_identity(s) for s in ordered],
                        a.get("feature_version"), a.get("source_fingerprint")]
            key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
            if key not in seen:
                pairs.append((gap, key, ordered))
    if not pairs:
        return None
    _, key, ordered = min(pairs, key=lambda pair: (pair[0], pair[1]))
    return {"pair_key": key, "a": snapshot(ordered[0]), "b": snapshot(ordered[1]),
            "anchor": snapshot(ordered[0]["matched_anchor"]),
            "feature_version": ordered[0].get("feature_version"),
            "source_fingerprint": ordered[0].get("source_fingerprint")}
