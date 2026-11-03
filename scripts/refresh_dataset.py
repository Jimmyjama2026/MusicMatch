"""Build a 200k catalog by snapshot popularity from a cached public source.

This is not an all-time chart or a live popularity ranking. Raw download and the
original dataset remain local, ignored by Git. Run manually to refresh.
"""
import ast
import hashlib
import json
from pathlib import Path
import shutil
import sys
import urllib.request
import zipfile

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "https://www.kaggle.com/datasets/yamaerenay/spotify-dataset-19212020-600k-tracks"
DOWNLOAD = "https://www.kaggle.com/api/v1/datasets/download/yamaerenay/spotify-dataset-19212020-600k-tracks"
TARGET_TRACKS = 200000


def sha256(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def artists(value):
    try:
        result = ast.literal_eval(value)
        return "; ".join(str(item) for item in result) if isinstance(result, list) else str(value)
    except (ValueError, SyntaxError, TypeError):
        return str(value)


def main():
    directory = ROOT / "data" / "sources"
    directory.mkdir(exist_ok=True)
    archive = directory / "spotify-600k.zip"
    if not archive.exists() or not zipfile.is_zipfile(archive):
        print("Downloading public Spotify 600k catalog...", flush=True)
        partial = archive.with_suffix(".zip.part")
        with urllib.request.urlopen(DOWNLOAD, timeout=60) as response, partial.open("wb") as handle:
            shutil.copyfileobj(response, handle)
        if not zipfile.is_zipfile(partial):
            raise ValueError("Download is not a valid ZIP archive; the catalog was not replaced.")
        with zipfile.ZipFile(partial) as package:
            if package.testzip() is not None:
                raise ValueError("Downloaded ZIP is incomplete; the catalog was not replaced.")
        partial.replace(archive)
    with zipfile.ZipFile(archive) as package:
        candidates = [name for name in package.namelist() if name.rsplit("/", 1)[-1] == "tracks.csv"]
        if len(candidates) != 1:
            raise ValueError(f"Expected tracks.csv in archive, found: {package.namelist()}")
        with package.open(candidates[0]) as handle:
            table = pd.read_csv(handle)
    source_columns = list(table.columns)
    table = table.rename(columns={"id": "track_id", "name": "track_name"})
    source_rows = len(table)
    table = table.dropna(subset=["track_id", "track_name", "artists"])
    table["artists"] = table["artists"].map(artists)
    features = ["valence", "tempo", "energy", "danceability"]
    for name in features + ["popularity"]:
        table[name] = pd.to_numeric(table[name], errors="coerce")
    valid = np.isfinite(table[features + ["popularity"]]).all(axis=1)
    valid &= table["tempo"].gt(0)
    for name in ("valence", "energy", "danceability"):
        valid &= table[name].between(0, 1)
    table = table.loc[valid].copy()
    for name in ("track_id", "track_name", "artists"):
        table[name] = table[name].astype(str).str.strip()
        table = table.loc[table[name].ne("")]
    table = table.sort_values(["popularity", "track_id"], ascending=[False, True], kind="stable")
    table = table.drop_duplicates("track_id")
    key = table["track_name"].str.casefold() + "\0" + table["artists"].str.casefold()
    table = table.loc[~key.duplicated()]
    usable = len(table)
    selected = table.head(TARGET_TRACKS).copy()
    selected["dataset_notice"] = "Modified popularity subset; normalized metadata. Yamac Eren Ay; CDLA-Sharing-1.0; see DATASET_SOURCE.md"
    if len(selected) != TARGET_TRACKS:
        raise ValueError(f"Need {TARGET_TRACKS} valid unique tracks; found {len(selected)}")
    temporary = ROOT / "data" / "dataset.next.csv"
    selected.to_csv(temporary, index=False)
    sys.path.insert(0, str(ROOT))
    from data.backend import MusicRecommender
    engine = MusicRecommender(temporary)
    if len(engine.table) != TARGET_TRACKS:
        raise ValueError("Catalog failed recommender validation")
    original = ROOT / "data" / "dataset.original.csv"
    if not original.exists():
        shutil.copy2(ROOT / "data" / "dataset.csv", original)
    metadata = {"source": SOURCE, "download": DOWNLOAD, "source_rows": source_rows,
                "valid_unique_source_tracks": usable, "selected_tracks": len(selected),
                "selection": "Highest Spotify popularity snapshot; stable ID tiebreak; unique title/artist and track ID",
                "creator": "Yamac Eren Ay", "source_version": 1,
                "source_updated_at": "2022-03-13T21:12:47.437Z",
                "license": "CDLA-Sharing-1.0", "license_url": "https://cdla.dev/sharing-1-0/",
                "coverage": "Historical international snapshot including early 2021 releases; not top 200k ever or current charts",
                "source_columns": source_columns,
                "source_archive_sha256": sha256(archive),
                "selected_csv_sha256": sha256(temporary),
                "language_country_filter_applied": False,
                "language_country_coverage": "Unknown: source has no track-language, artist-country, or US-market fields. No title/script inference applied.",
                "selected_release_date_min": str(selected.release_date.min()),
                "selected_release_date_max": str(selected.release_date.max()),
                "popularity_min": int(selected.popularity.min()), "popularity_max": int(selected.popularity.max())}
    temporary.replace(ROOT / "data" / "dataset.csv")
    (ROOT / "data" / "dataset_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(json.dumps(metadata, indent=2), flush=True)
    print(selected[["track_name", "artists", "popularity"]].head(8).to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
