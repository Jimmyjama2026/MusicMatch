"""Run bounded metadata acquisition separately from the desktop application."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from data.acquisition import DEFAULT_UA, JsonClient, CurlResponse, collect, open_approved


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artist", action="append", help="Limit to selected artist(s); default all 27")
    parser.add_argument("--max-recordings", type=int, default=10000)
    parser.add_argument("--pages-per-artist", type=int, default=100)
    parser.add_argument("--skip-listenbrainz", action="store_true")
    parser.add_argument("--user-agent", default=DEFAULT_UA)
    parser.add_argument("--transport", choices=("urllib", "curl"), default="urllib", help="Native curl is an optional verified-HTTPS Windows fallback")
    parser.add_argument("--artist-ids", type=Path, help="JSON mapping artist name to manually verified MBID")
    args = parser.parse_args()
    names = args.artist or [a["artist"] for a in json.loads((ROOT / "data/coverage_audit.json").read_text(encoding="utf-8"))["artists"]]
    overrides = json.loads(args.artist_ids.read_text(encoding="utf-8")) if args.artist_ids else None
    client = JsonClient(ROOT / "data/enrichment", args.user_agent, response_limit=250_000, opener=CurlResponse if args.transport == "curl" else open_approved)
    with client.exclusive():
        result = collect(client, names, args.max_recordings, args.pages_per_artist, overrides, not args.skip_listenbrainz)
    print(json.dumps({"artists": len(result["artists"]), "tracks": len(result["tracks"]), "related_edges": len(result["related_edges"]), "popularity": len(result["popularity"]), "errors": result["errors"], "payload_bytes_upper_bound": client.ledger["payload_bytes"], "disk_bytes": client.disk_bytes()}, indent=2))


if __name__ == "__main__":
    main()
