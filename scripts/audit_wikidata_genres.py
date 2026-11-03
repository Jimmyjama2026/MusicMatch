"""Research-only catalog overlap with Wikidata song genres and exact Spotify IDs."""
import json
from pathlib import Path
import sys
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = ROOT / "data/sources/genre_research"
QUERY = '''SELECT DISTINCT ?song ?spotify ?genre ?genreLabel WHERE {
  ?song wdt:P2207 ?spotify; wdt:P136 ?genre.
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
} LIMIT 50000'''


def main():
    DIRECTORY.mkdir(parents=True, exist_ok=True)
    path = DIRECTORY / "wikidata_song_genres.json"
    if not path.exists():
        request = Request("https://query.wikidata.org/sparql?" + urlencode({"query": QUERY, "format": "json"}),
            headers={"User-Agent": "MusicMatch/0.2 (https://github.com/Jimmyjama2026/MusicMatch)",
                     "Accept": "application/sparql-results+json"})
        with urlopen(request, timeout=45) as response:
            raw = response.read(15_000_001)
        if len(raw) > 15_000_000:
            raise ValueError("Research response exceeds 15 MB cap")
        payload = json.loads(raw)
        path.write_bytes(raw)
    else:
        payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload["results"]["bindings"]
    catalog = pd.read_csv(ROOT / "data/dataset.csv", usecols=["track_id", "track_name", "artists"])
    ids = set(catalog.track_id)
    matches = {}
    for row in rows:
        spotify = row["spotify"]["value"]
        if spotify in ids:
            matches.setdefault(spotify, []).append({"song": row["song"]["value"], "genre": row["genre"]["value"],
                                                    "genre_label": row["genreLabel"]["value"]})
    report = {"source": "https://query.wikidata.org/", "license": "CC0-1.0", "query": QUERY,
              "query_truncated": len(rows) >= 50000, "source_rows": len(rows),
              "source_spotify_tracks": len({row["spotify"]["value"] for row in rows}),
              "catalog_tracks": len(ids), "catalog_spotify_id_matches": len(matches),
              "catalog_match_percent": round(100 * len(matches) / len(ids), 4), "matches": matches,
              "limitations": ["Song/work-level entities may combine versions; identity and statement sourcing need review.",
                              "Research candidates only; not imported as recording-confirmed genre labels."]}
    (DIRECTORY / "wikidata_audit.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "matches"}, indent=2))


if __name__ == "__main__":
    main()
