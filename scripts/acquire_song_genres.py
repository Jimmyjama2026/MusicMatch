"""Bounded, resumable MusicBrainz recording genre acquisition. No artist fallback."""
import argparse
import json
from pathlib import Path
import sys
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from data.acquisition import JsonClient, CurlResponse, MB, utc_now, valid_mbid
from data.genres import VERSION
from data.identity import song_identity

LICENSE = "CC-BY-NC-SA-3.0"


def supported_genres(recording):
    votes = {g["name"].strip().casefold(): g["count"] for g in recording.get("genres", [])
             if isinstance(g, dict) and isinstance(g.get("name"), str) and g["name"].strip()
             and isinstance(g.get("count"), (int, float)) and g["count"] > 0}
    # A single vote is retained for review, not sufficient for a hard boundary.
    threshold = max(2, .75 * max(votes.values(), default=0))
    return sorted(g for g, count in votes.items() if count >= threshold), votes


def recording_song(recording):
    credits = recording.get("artist-credit", [])
    return {"track_name": recording.get("title", ""),
            "artists": "; ".join(c.get("artist", {}).get("name", "") for c in credits if isinstance(c, dict))}


def matching_recording(song, recordings):
    """Reject namesakes, incomplete credits, wrong durations and ambiguous versions."""
    matches = []
    for item in recordings:
        if not valid_mbid(item.get("id")) or song_identity(song) != song_identity(recording_song(item)):
            continue
        duration, measured = item.get("length"), song.get("duration_ms")
        if not isinstance(duration, (float, int)) or not isinstance(measured, (float, int)):
            continue
        if abs(duration - measured) > 2000 or item.get("disambiguation"):
            continue
        matches.append(item)
    unique = {r["id"]: r for r in matches}
    return next(iter(unique.values())) if len(unique) == 1 else None


def fetch_song(client, song, mbid=None):
    basis = "existing_exact_title_full_credit_duration_join"
    if mbid is None:
        def escape(value):
            return value.replace("\\", "\\\\").replace('"', '\\"')
        query = 'recording:"{}" AND artist:"{}"'.format(escape(song["track_name"]), escape(song["artists"].split(";")[0].strip()))
        response = client.get(MB, "recording/", {"query": query, "fmt": "json", "limit": 100})
        # A truncated search is ambiguous even if one returned recording matches.
        found = matching_recording(song, response.get("recordings", [])) if response.get("count", 0) <= 100 else None
        if found is None:
            return {"status": "unresolved_identity", "level": "recording", "genres": []}
        mbid = found["id"]
        basis = "unique_exact_title_full_credit_duration_search"
    recording = client.get(MB, "recording/" + mbid, {"inc": "genres+artist-credits", "fmt": "json"})
    # Revalidate the detail response, rather than trusting the supplied mapping.
    if recording.get("id") != mbid or matching_recording(song, [recording]) is None:
        return {"status": "unresolved_identity", "level": "recording", "genres": []}
    genres, votes = supported_genres(recording)
    return {"status": "labelled" if genres else "insufficient_genre_votes" if votes else "no_recording_genres", "level": "recording",
            "genre_votes": votes, "label_policy": "at least 2 votes and at least 75% of strongest genre vote count; heuristic, not calibrated confidence",
            "genres": genres, "recording_mbid": mbid, "identity_basis": basis,
            "source": "musicbrainz", "source_url": "https://musicbrainz.org/recording/" + mbid,
            "license": LICENSE, "attribution": "MusicBrainz contributors",
            "retrieved_at": client.last_retrieved_at, "track_name": song["track_name"], "artists": song["artists"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=50, help="Maximum new songs to inspect per run")
    parser.add_argument("--artist", help="Optional artist text filter")
    parser.add_argument("--refresh", action="store_true", help="Reprocess existing entries (responses remain cached)")
    parser.add_argument("--include-saved-favorites", action="store_true", help="Explicitly authorize sending saved-favorite song identities to MusicBrainz")
    parser.add_argument("--transport", choices=("urllib", "curl"), default="curl")
    args = parser.parse_args()
    if not 1 <= args.limit <= 1000:
        parser.error("--limit must be between 1 and 1000")
    from data.hybrid import MusicRecommender
    engine = MusicRecommender()
    directory = ROOT / "data/sources/song_genres"
    client = JsonClient(directory, response_limit=2_000_000,
                        **({"opener": CurlResponse} if args.transport == "curl" else {}))
    path = directory / "index.json"
    document = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"version": VERSION, "songs": {}}
    songs = list(engine.audio._songs)
    favorite_ids = set()
    feedback_path = ROOT / "data/feedback.sqlite3"
    if args.include_saved_favorites and feedback_path.exists():
        connection = sqlite3.connect(feedback_path.as_uri() + "?mode=ro", uri=True)
        try:
            for (snapshot,) in connection.execute("SELECT favorites_json FROM profile_state"):
                favorite_ids.update(s["track_id"] for s in json.loads(snapshot))
        finally:
            connection.close()
    songs.sort(key=lambda s: (s["track_id"] not in favorite_ids,
                              s["track_id"] not in engine.audio_to_mbid, -float(s.get("popularity", 0))))
    if args.artist:
        songs = [s for s in songs if args.artist.casefold() in s["artists"].casefold()]
    attempted, errors = 0, []
    with client.exclusive():
        for song in songs:
            track_id = song["track_id"]
            if track_id in document["songs"] and not args.refresh:
                continue
            if attempted >= args.limit:
                break
            attempted += 1
            try:
                evidence = fetch_song(client, song, engine.audio_to_mbid.get(track_id))
                document["songs"][track_id] = evidence
                client.save(path, document)
                print(json.dumps({"number": attempted, "title": song["track_name"], "status": evidence["status"], "genres": evidence["genres"]}), flush=True)
            except Exception as error:
                errors.append({"track_id": track_id, "error": str(error)})
                print("Acquisition stopped: " + str(error), flush=True)
                break  # Network/budget failures never become permanent missing labels.
        counts = {}
        for evidence in document["songs"].values():
            counts[evidence["status"]] = counts.get(evidence["status"], 0) + 1
        report = {"version": VERSION, "updated_at": utc_now(), "catalog_tracks": len(engine.audio._songs),
                  "inspected": len(document["songs"]), "statuses": counts, "errors": errors,
                  "payload_bytes_upper_bound": client.ledger["payload_bytes"],
                  "note": "Targeted pilot, not a representative coverage estimate. No artist/album genres inherited."}
        client.save(directory / "report.json", report)
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
