"""Recording labels take priority over explicitly identified artist fallbacks."""
import ast
import json
from pathlib import Path

if __package__:
    from .identity import normalized
else:
    from identity import normalized

VERSION = "recording-genres-v1"
ARTIST_VERSION = "artist-genre-fallback-v1"


def labels(song):
    evidence = song.get("genre_evidence")
    if not isinstance(evidence, dict) or evidence.get("level") != "recording":
        return frozenset()
    return frozenset(normalized(g) for g in evidence.get("genres", []) if isinstance(g, str) and g.strip())


def compatible(left, right):
    """Require actual shared genre evidence. Unknown is not a shared genre."""
    return bool(effective_labels(left) & effective_labels(right))


def effective_evidence(song):
    if labels(song):
        return song["genre_evidence"]
    item = song.get("artist_genre_evidence")
    return item if isinstance(item, dict) and item.get("level") == "artist" else {}


def effective_labels(song):
    return frozenset(normalized(g) for g in effective_evidence(song).get("genres", [])
                     if isinstance(g, str) and g.strip())


def attach_artist_evidence(songs, path):
    path = Path(path)
    if not path.exists():
        return
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("version") != ARTIST_VERSION:
        raise ValueError("Unsupported artist genre index")
    artists = document["artists"]
    cache = {}
    for song in songs:
        raw = song.get("id_artists", [])
        try:
            ids = ast.literal_eval(raw) if isinstance(raw, str) else raw
        except (SyntaxError, ValueError):
            continue
        if not isinstance(ids, (list, tuple)) or not all(isinstance(i, str) for i in ids):
            continue
        key = tuple(sorted(set(ids)))
        if key not in cache:
            matched = [i for i in key if i in artists and artists[i].get("genres")]
            genres = sorted({g for i in matched for g in artists[i]["genres"] if isinstance(g, str) and g.strip()})
            cache[key] = {"level": "artist", "genres": genres, "artist_ids": matched,
                          "all_credited_artists_covered": bool(key) and len(matched) == len(key),
                          "source": document["source"], "license": document["license"],
                          "version": ARTIST_VERSION} if genres else None
        if cache[key]:
            song["artist_genre_evidence"] = cache[key]


def load_evidence(path):
    path = Path(path)
    if not path.exists():
        return {}
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("version") != VERSION:
        raise ValueError("Unsupported recording genre index")
    result = {}
    for track_id, evidence in document.get("songs", {}).items():
        if evidence.get("status") == "labelled" and labels({"genre_evidence": evidence}):
            result[track_id] = evidence
    return result
