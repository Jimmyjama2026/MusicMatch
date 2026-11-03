"""Research-only coverage audit of published Last.fm recording annotations.

Downloads only two compressed annotation tables (under 35 MB combined).
Does not import labels into recommendations or send personal song choices.
"""
import bz2
import csv
import hashlib
import json
from pathlib import Path
import sys
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = ROOT / "data/sources/genre_research"
FILES = (
    ("acousticbrainz-mediaeval-lastfm-train.tsv.bz2", "797a4d6dfcdbe9c405f336225a97fd9e"),
    ("acousticbrainz-mediaeval-lastfm-validation.tsv.bz2", "9fc1ced2b4317993ad91fd59e718f7ef"),
)


def main():
    DIRECTORY.mkdir(parents=True, exist_ok=True)
    transferred = 0
    for name, checksum in FILES:
        path = DIRECTORY / name
        if not path.exists():
            url = "https://zenodo.org/records/2553414/files/" + name + "?download=1"
            temporary = path.with_suffix(path.suffix + ".part")
            request = Request(url, headers={"User-Agent": "MusicMatch/0.2 (https://github.com/Jimmyjama2026/MusicMatch)"})
            with urlopen(request, timeout=30) as response, temporary.open("wb") as output:
                while chunk := response.read(65536):
                    transferred += len(chunk)
                    if transferred > 35_000_000:
                        raise ValueError("Research download budget exceeded")
                    output.write(chunk)
            temporary.replace(path)
        if hashlib.md5(path.read_bytes()).hexdigest() != checksum:
            raise ValueError("Published checksum mismatch: " + name)
        print("Verified " + name, flush=True)
    index_path = ROOT / "data/sources/song_genres/index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))["songs"]
    mbid_to_song = {item["recording_mbid"]: (track_id, item) for track_id, item in index.items()
                    if item.get("recording_mbid") and item.get("status") != "unresolved_identity"}
    matches, unique, rows = {}, set(), 0
    for name, _ in FILES:
        with bz2.open(DIRECTORY / name, "rt", encoding="utf-8") as handle:
            for fields in csv.reader(handle, delimiter="\t"):
                if not fields or fields[0] == "recordingmbid":
                    continue
                rows += 1
                unique.add(fields[0])
                if fields[0] in mbid_to_song:
                    track_id, previous = mbid_to_song[fields[0]]
                    tags = [tag for tag in fields[2:] if tag.strip()]
                    matches[track_id] = {"recording_mbid": fields[0], "track_name": previous["track_name"],
                        "artists": previous["artists"], "previous_status": previous["status"],
                        "genres": [tag for tag in tags if "---" not in tag],
                        "subgenres": [tag for tag in tags if "---" in tag]}
    report = {"source": "https://zenodo.org/records/2553414", "license": "CC-BY-NC-SA-4.0",
        "annotation_basis": "genres inferred from Last.fm recording tags; not artist or album inheritance",
        "published_checksums_verified": True, "annotation_rows": rows, "unique_recordings": len(unique),
        "catalog_tracks": 200000, "catalog_recordings_with_existing_conservative_mbid_join": len(mbid_to_song),
        "matched_catalog_recordings": len(matches),
        "additional_recordings_beyond_current_labels": sum(item["previous_status"] != "labelled" for item in matches.values()),
        "matches": matches, "new_download_bytes": transferred,
        "limitations": ["Only existing conservative recording joins audited; full-catalog overlap remains unmeasured.",
                        "Historical data cannot cover songs first released after its collection.",
                        "No labels imported into recommendations; taxonomy/confidence reconciliation still required."]}
    (DIRECTORY / "lastfm_bulk_audit.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "matches"}, indent=2))


if __name__ == "__main__":
    main()
