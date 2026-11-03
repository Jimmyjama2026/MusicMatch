"""Local read-only diagnosis; never saves batches, votes or training artifacts."""
from collections import Counter
import argparse
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from data.backend import FeedbackStore
from data.hybrid import MusicRecommender
from data.identity import credited_artists, artist_ids
from data.title_language import TitleLanguageScreen


class ReadOnlyStore(FeedbackStore):
    def __init__(self, path):
        self.path = Path(path)

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            yield connection
        finally:
            connection.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wide", action="store_true", help="Also inspect a 200-result request")
    args = parser.parse_args()
    store = ReadOnlyStore(ROOT / "data/feedback.sqlite3")
    profile = store.get_active_profile()
    state = store.load_profile(profile)
    engine = MusicRecommender()
    favorites = [engine.get_song(s["track_id"]) for s in state["favorites"]]
    feedback = store.training_feedback(profile)
    names = {name for s in favorites + [r for r in feedback if r["liked"]] for name in credited_artists(s)}
    ids = {i for s in favorites + [r for r in feedback if r["liked"]] for i in artist_ids(s)}
    screen = TitleLanguageScreen()
    diagnostics = {"profile": profile, "favorites": len(favorites), "live_feedback": len(feedback), "runs": []}
    for fresh in (False, True):
        exclusions = store.recommendation_exclusions(profile, fresh)
        exclusions.update(s["track_id"] for s in favorites + [r for r in feedback if r["liked"]])
        for limit in ((5, 200) if args.wide else (5,)):
            counts = Counter()
            def check(song):
                result = screen.screen(song)
                counts["checked"] += 1
                counts["allowed" if result["allowed"] else "rejected"] += 1
                if not result["allowed"]:
                    counts[str(result.get("reason", result.get("language")))] += 1
                return result["allowed"]
            results = engine.recommend([s["track_id"] for s in favorites], limit,
                favorite_songs=favorites, feedback=feedback, exclude_ids=exclusions,
                known_artist_names=names, known_artist_ids=ids,
                pairwise_feedback=store.training_comparisons(profile), candidate_filter=check)
            diagnostics["runs"].append(dict(fresh=fresh, limit=limit, exclusions=len(exclusions),
                                            returned=len(results), title_filter=dict(counts)))
            print(json.dumps(diagnostics["runs"][-1]), flush=True)
    directory = ROOT / "data/sources/recommendation_diagnostics"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "report.json").write_text(json.dumps(diagnostics, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
