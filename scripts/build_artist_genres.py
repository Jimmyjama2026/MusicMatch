"""Build an offline artist-genre fallback from the already cached source ZIP."""
import ast
from pathlib import Path
import json
import sys
import zipfile

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from data.genres import ARTIST_VERSION


def build(table, artists):
    wanted = {i for value in table["id_artists"] for i in ast.literal_eval(value)}
    selected = {}
    for row in artists.itertuples(index=False):
        if row.id not in wanted:
            continue
        genres = ast.literal_eval(row.genres) if isinstance(row.genres, str) else []
        if genres:
            selected[row.id] = {"name": row.name, "genres": sorted(set(genres))}
    return {"version": ARTIST_VERSION, "artists": selected,
            "source": "https://www.kaggle.com/datasets/yamaerenay/spotify-dataset-19212020-600k-tracks",
            "attribution": "Yamac Eren Ay", "license": "CDLA-Sharing-1.0",
            "note": "Historical artist genres; not verified recording genres. Joined by exact Spotify artist IDs."}


def main():
    from data.genres import attach_artist_evidence, effective_labels
    table = pd.read_csv(ROOT / "data/dataset.csv", usecols=["track_id", "id_artists"])
    with zipfile.ZipFile(ROOT / "data/sources/spotify-600k.zip") as archive:
        with archive.open("artists.csv") as handle:
            artists = pd.read_csv(handle, usecols=["id", "name", "genres"])
    document = build(table, artists)
    directory = ROOT / "data/sources/artist_genres"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "index.json"
    temporary = directory / "index.next.json"
    temporary.write_text(json.dumps(document, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    temporary.replace(path)
    songs = table.to_dict("records")
    attach_artist_evidence(songs, path)
    covered = sum(bool(effective_labels(song)) for song in songs)
    complete = sum(song.get("artist_genre_evidence", {}).get("all_credited_artists_covered", False) for song in songs)
    report = {"catalog_tracks": len(songs), "covered_tracks": covered, "covered_percent": round(100 * covered / len(songs), 4),
              "all_credited_artists_covered": complete, "unknown_tracks": len(songs) - covered,
              "indexed_artists": len(document["artists"]), "index_bytes": path.stat().st_size,
              "join": "exact Spotify artist IDs", "network_requests": 0}
    (directory / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
