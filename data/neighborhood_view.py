"""Small, saved explanations of real ranking anchors; never a ranking input."""
from __future__ import annotations

import math
import numpy as np

PROJECTION_NOTE = (
    "Approximate 2D view of 21-dimensional audio vectors. Colors show the actual "
    "matching groups; nearby dots may differ in hidden dimensions. Axes are fitted "
    "to this saved batch and cannot be compared across batches. Song genres or "
    "identified artist fallbacks constrain groups separately from the audio coordinates; "
    "unknown genres do not establish genre similarity."
)


def empty_view(message="Generate suggestions to see the neighborhoods used for that batch."):
    return {"available": False, "points": [], "groups": [],
            "projection_note": PROJECTION_NOTE, "message": message}


def comparison_table(song, anchor):
    """Raw values and differences, not confidence or reconstructed contributions."""
    rows = []
    for feature, label, unit in (
        ("energy", "Energy", "percent"), ("valence", "Mood / valence", "percent"),
        ("danceability", "Danceability", "percent"),
        ("acousticness", "Acousticness", "percent"),
        ("tempo", "Recorded tempo", "bpm"), ("duration_ms", "Duration", "duration"),
    ):
        a, b = anchor.get(feature), song.get(feature)
        def valid(value):
            return (isinstance(value, (float, int)) and not isinstance(value, bool)
                    and math.isfinite(value) and
                    (0 <= value <= 1 if unit == "percent" else value > 0))
        def formatted(value):
            if not valid(value):
                return "Unavailable"
            if unit == "percent":
                return f"{value * 100:.1f}%"
            if unit == "bpm":
                return f"{value:.1f} BPM"
            seconds = round(value / 1000)
            return f"{seconds // 60}:{seconds % 60:02d}"
        left, right = formatted(a), formatted(b)
        if not all(valid(v) for v in (a, b)):
            rows.append(dict(feature=label, liked=left, suggested=right,
                             note="A saved measurement is missing or invalid."))
            continue
        if unit == "percent":
            note = f"{abs(b-a)*100:.1f} percentage points apart"
        elif unit == "bpm":
            note = f"{abs(b-a):.1f} BPM apart; recorded tempo can use half/double time"
        else:
            note = f"{abs(b-a)/1000:.0f} seconds apart"
        rows.append(dict(feature=label, liked=left, suggested=right, note=note))
    artist_adjustment = song.get("artist_adjustment", 0)
    rows.append(dict(feature="Artist", liked=anchor.get("artists", "Unknown"),
                     suggested=song.get("artists", "Unknown"),
                     note=(f"Shared artist adjusted the score by {artist_adjustment:+.3f}."
                           if isinstance(artist_adjustment, (float, int)) and artist_adjustment < 0
                           else "No shared-artist bonus for this match.")))
    return rows


def attach_visuals(songs, vectors, max_points=64):
    """Persist a bounded local projection and raw comparison for a new batch.

    Called on the recommendation worker, before saving. Loading history never
    reconstructs an old explanation with today's favorites or vector settings.
    """
    if not songs:
        return
    anchors = songs[0].get("neighborhood_anchors", [])
    if vectors is None or not anchors:
        return
    records = {}
    for entry in anchors:
        song = entry["song"]
        records[song["track_id"]] = (song, int(entry["group"]), entry["kind"], False)
    for song in songs:
        records[song["track_id"]] = (song, int(song["neighborhood_context"]["group"]),
                                      "suggestion", bool(song.get("selection_context", {}).get("discovery")))
    # Include every result and its actual matched anchor before extra anchors.
    priority = list(dict.fromkeys([s["track_id"] for s in songs] +
        [s.get("matched_anchor", {}).get("track_id") for s in songs]))
    priority = [key for key in priority if key in records]
    ordered = priority + sorted(set(records).difference(priority))
    matrix, validity = vectors.transform([records[key][0] for key in ordered])
    complete = validity.all(axis=1) & np.isfinite(matrix).all(axis=1)
    usable = np.flatnonzero(complete)
    # Fit the batch basis before the display cap; no sampling changes group IDs.
    projected = np.zeros((len(usable), 2), dtype=float)
    if len(usable) > 1:
        centered = matrix[usable].astype(float) - matrix[usable].mean(axis=0)
        _, _, basis = np.linalg.svd(centered, full_matrices=False)
        for axis in range(min(2, len(basis))):
            vector = basis[axis]
            if vector[np.argmax(np.abs(vector))] < 0:
                vector = -vector
            projected[:, axis] = centered @ vector
    span = float(np.ptp(projected, axis=0).max()) if len(projected) else 0
    if len(projected) and span > 1e-10:
        midpoint = (projected.min(axis=0) + projected.max(axis=0)) / 2
        projected = .5 + .84 * (projected - midpoint) / span
    else:
        projected[:] = .5
    points = []
    for row, index in enumerate(usable[:max_points]):
        song, group, kind, discovery = records[ordered[index]]
        points.append(dict(track_id=song["track_id"], track_name=song["track_name"],
            artists=song["artists"], x=float(projected[row, 0]), y=float(projected[row, 1]),
            group=group, kind=kind, discovery=discovery))
    groups = {}
    for entry in anchors:
        group = int(entry["group"])
        groups.setdefault(group, []).append(entry["song"])
    omitted_incomplete = len(records) - len(usable)
    omitted_cap = max(0, len(usable) - max_points)
    message = f"{len(points)} songs shown; liked songs and saved Yes ratings shaped these groups."
    if omitted_incomplete:
        message += f" {omitted_incomplete} songs with incomplete features are not plotted."
    if omitted_cap:
        message += f" {omitted_cap} additional anchors are hidden to keep the view readable."
    view = dict(available=bool(points), points=points,
        groups=[dict(id=group, label="Group " + str(group + 1), anchor_count=len(members))
                for group, members in sorted(groups.items())], projection_note=PROJECTION_NOTE,
        message=message, omitted_incomplete=omitted_incomplete, omitted_display=omitted_cap,
        projection_version="batch-pca-v1", feature_version=songs[0].get("feature_version"),
        source_fingerprint=songs[0].get("source_fingerprint"))
    for song in songs:
        song["neighborhood_visual"] = view
        anchor = song.get("matched_anchor")
        if anchor:
            song["match_table"] = comparison_table(song, anchor)
