"""Read-only exports of explicit judgments and their immutable historical context.

Reasons are policy/audit metadata, never predictor features. Older databases can
be inspected without migrating them; their overwritten votes cannot be recovered.
"""
from contextlib import closing
import json
import math
from pathlib import Path
import sqlite3
from functools import lru_cache

if __package__:
    from .identity import song_identity
    from .comparisons import snapshot
else:
    from identity import song_identity
    from comparisons import snapshot

NON_BINARY_REASONS = frozenset(("Already know it", "Too slow", "Too fast"))


def load_favorite_judgments(db_path, profile_id):
    """Current favorites are explicit positives; removal is not a negative vote."""
    with closing(_connect(db_path, profile_id)) as connection:
        row = connection.execute("SELECT favorites_json FROM profile_state WHERE profile_id=?", (profile_id,)).fetchone()
        if not row:
            return []
        active = {song_identity(s): s for s in json.loads(row[0])}
        exists = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='favorite_events'").fetchone()
        events = connection.execute("SELECT sequence,event_id,favorites_json,changed_at FROM favorite_events WHERE profile_id=? ORDER BY sequence", (profile_id,)).fetchall() if exists else []
        fallback_time = connection.execute("SELECT MIN(created_at) FROM recommendation_batches WHERE profile_id=?", (profile_id,)).fetchone()[0]
    additions, previous = {}, set()
    for sequence, event_id, payload, when in events:
        current = {song_identity(s): s for s in json.loads(payload)}
        for key in current.keys() - previous:
            additions[key] = (sequence, event_id, when, current[key])
        previous = set(current)
    result = []
    for key, saved in active.items():
        sequence, event_id, when, candidate = additions.get(key, (0, "existing-favorite:" + str(saved["track_id"]), fallback_time or "1970-01-01T00:00:00.000Z", saved))
        result.append(dict(event_id=event_id, event_sequence=sequence, batch_id=None, profile_id=profile_id,
            liked=True, reason="Added to liked songs", feedback_reason=None, judgment_source="favorite",
            judged_at=when, shown_at=None, song=snapshot(candidate), anchor=None, favorites=[],
            model_version=None, feature_version=candidate.get("feature_version"),
            source_fingerprint=candidate.get("source_fingerprint"), heuristic_score=None,
            time_basis="favorite_add_event" if key in additions else "existing_favorite_first_observed_batch"))
    return result


@lru_cache(maxsize=1)
def _catalog_snapshots(path, modified, size, wanted):
    import pandas as pd
    from .song_vectors import RAW_FEATURES
    result = {}
    for table in pd.read_csv(path, usecols=["track_id", "track_name", "artists", *RAW_FEATURES], chunksize=20000):
        result.update({s["track_id"]: s for s in table.loc[table.track_id.isin(wanted)].to_dict("records")})
    return result


def resolve_favorite_features(records, manifest):
    """Version old favorite measurements only after an exact catalog check."""
    from .song_vectors import RAW_FEATURES
    import numpy as np
    catalog_path = Path(__file__).with_name("dataset.csv")
    unresolved = [r for r in records if r.get("judgment_source") == "favorite" and not r.get("source_fingerprint")]
    if not unresolved or not catalog_path.exists():
        return records
    stat = catalog_path.stat()
    wanted = tuple(sorted({r["song"]["track_id"] for r in unresolved}))
    catalog = _catalog_snapshots(str(catalog_path), stat.st_mtime_ns, stat.st_size, wanted)
    # Do not stamp a custom manifest onto the production catalog.
    metadata_path = catalog_path.with_name("vectors") / "manifest.json"
    if not metadata_path.exists():
        return records
    pointer = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata = json.loads((metadata_path.parent / pointer["generation"] / "metadata.json").read_text(encoding="utf-8"))
    if metadata.get("source_fingerprint") != manifest.get("source_fingerprint"):
        return records
    result = []
    for record in records:
        current = catalog.get(record["song"].get("track_id")) if record in unresolved else None
        if current and song_identity(current) == song_identity(record["song"]):
            try:
                matches = np.allclose([float(record["song"][k]) for k in RAW_FEATURES],
                                      [float(current[k]) for k in RAW_FEATURES], rtol=1e-8, atol=1e-7)
            except (TypeError, ValueError, KeyError):
                matches = False
            if matches:
                record = dict(record, feature_version=manifest["version"], source_fingerprint=manifest["source_fingerprint"],
                              feature_resolution="saved favorite measurements match current catalog; no metadata backfill")
        result.append(record)
    return result


def _connect(path, profile_id):
    if profile_id not in ("personal", "test"):
        raise ValueError("Unknown profile.")
    return sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)


def load_feedback_events(db_path, profile_id):
    """All retained vote events, ordered by actual vote time and stable sequence."""
    with closing(_connect(db_path, profile_id)) as connection:
        has_events = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='feedback_events'").fetchone()
        if has_events:
            rows = connection.execute("""SELECT e.event_id,e.sequence,e.batch_id,e.liked,e.reason,
                    e.judged_at,r.song_json,b.favorites_json,b.model_version,b.created_at
                FROM feedback_events e JOIN recommendations r USING(batch_id,track_id)
                JOIN recommendation_batches b USING(batch_id)
                WHERE e.profile_id=? ORDER BY e.judged_at,e.sequence""", (profile_id,)).fetchall()
        else:
            rows = connection.execute("""SELECT 'legacy:' || f.batch_id || ':' || f.track_id,
                    f.rowid,f.batch_id,f.liked,f.reason,f.updated_at,r.song_json,
                    b.favorites_json,b.model_version,b.created_at
                FROM feedback f JOIN recommendations r USING(batch_id,track_id)
                JOIN recommendation_batches b USING(batch_id)
                WHERE b.profile_id=? ORDER BY f.updated_at,f.rowid""", (profile_id,)).fetchall()
    result = []
    for event, sequence, batch, liked, reason, judged, song_json, favorites_json, model, shown in rows:
        song = json.loads(song_json)
        result.append(dict(event_id=event, event_sequence=sequence, batch_id=batch,
            profile_id=profile_id, liked=bool(liked), reason=reason, feedback_reason=reason,
            judged_at=judged, shown_at=shown, song=song, favorites=json.loads(favorites_json),
            model_version=model, feature_version=song.get("feature_version"),
            source_fingerprint=song.get("source_fingerprint")))
    return result


def load_training_records(db_path, profile_id, *, include_favorites=True):
    """Latest canonical votes eligible for the binary contextual neural pilot.

Resolve conflicts *before* excluding familiarity/pace feedback so an older Yes
cannot reappear when its latest correction is unsuitable for binary learning.
Candidate and matched anchor are measurements-only snapshots; no ranking scores
or reason strings are model inputs. No self-anchor or invented current context.
The evaluator must additionally remove held-out identities from training anchors.
"""
    latest = {}
    for record in load_feedback_events(db_path, profile_id):
        latest[song_identity(record["song"])] = record
    for record in (load_favorite_judgments(db_path, profile_id) if include_favorites else []):
        key = song_identity(record["song"])
        prior = latest.get(key)
        if prior is None or record["judged_at"] > prior["judged_at"]:
            latest[key] = record
    result = []
    for record in latest.values():
        if not record["liked"] and record["reason"] in NON_BINARY_REASONS:
            continue
        candidate = record["song"]
        if record.get("judgment_source") == "favorite":
            result.append(record)
            continue
        anchor = candidate.get("matched_anchor")
        if not isinstance(anchor, dict) or not anchor.get("track_id"):
            anchor_id = (candidate.get("neighborhood_context") or {}).get("anchor_id")
            anchor = next((s for s in record["favorites"] if s.get("track_id") == anchor_id), None)
        if not anchor or song_identity(anchor) == song_identity(candidate):
            continue
        try:
            heuristic_score = float(candidate.get("ranking_score"))
            if not math.isfinite(heuristic_score):
                heuristic_score = None
        except (TypeError, ValueError, OverflowError):
            heuristic_score = None
        # Historical baseline output is audit-only, outside predictor snapshots.
        cleaned = dict(record, song=snapshot(candidate), anchor=snapshot(anchor),
                       heuristic_score=heuristic_score,
                       favorites=[snapshot(s) for s in record["favorites"]])
        result.append(cleaned)
    return sorted(result, key=lambda item: (item["judged_at"], item["event_sequence"]))


def load_comparison_records(db_path, profile_id):
    """All active directional A/B choices; no 32-row live-ranking truncation.

Equal, skipped and undone comparisons carry no directional target and are
excluded. Winners and losers remain separate from binary Yes/No training.
"""
    with closing(_connect(db_path, profile_id)) as connection:
        rows = connection.execute("""SELECT comparison_id,payload_json,choice,updated_at,batch_id
            FROM pairwise_comparisons WHERE profile_id=? AND choice IN ('a','b')
            ORDER BY updated_at,rowid""", (profile_id,)).fetchall()
    result = []
    for comparison_id, payload, choice, judged, batch in rows:
        pair = json.loads(payload)
        result.append(dict(event_id=comparison_id, comparison_id=comparison_id,
            profile_id=profile_id, batch_id=batch, judged_at=judged, choice=choice,
            anchor=snapshot(pair["anchor"]), winner=snapshot(pair[choice]),
            loser=snapshot(pair["b" if choice == "a" else "a"]),
            feature_version=pair.get("feature_version"), source_fingerprint=pair.get("source_fingerprint")))
    return result
