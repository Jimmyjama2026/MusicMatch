"""Read-only profile replay; all generated output/cache stays under sources/."""
import copy
from contextlib import closing
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from data.hybrid import MusicRecommender
from data.identity import artist_ids, credited_artists
from data.ranking_config import DEFAULT_RANKING
from data.title_language import TitleLanguageScreen


def main():
    database = ROOT / "data/feedback.sqlite3"
    output = ROOT / "data/sources/feedback_fix_audit.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        connection.execute("BEGIN")
        profile = connection.execute("SELECT value FROM app_settings WHERE key='active_profile'").fetchone()[0]
        favorites = json.loads(connection.execute(
            "SELECT favorites_json FROM profile_state WHERE profile_id=?", (profile,)).fetchone()[0])
        rows = connection.execute("""SELECT song_json,liked,reason FROM (
            SELECT r.song_json,f.liked,f.reason,f.updated_at,f.rowid AS ordering,
                ROW_NUMBER() OVER(PARTITION BY f.track_id ORDER BY f.updated_at DESC,f.rowid DESC) AS latest
            FROM feedback f JOIN recommendations r ON r.batch_id=f.batch_id AND r.track_id=f.track_id
            JOIN recommendation_batches b ON b.batch_id=f.batch_id WHERE b.profile_id=?
            ) WHERE latest=1 ORDER BY updated_at DESC,ordering DESC LIMIT 500""", (profile,)).fetchall()
        feedback = [dict(json.loads(song), liked=bool(liked), feedback_reason=reason) for song, liked, reason in rows]
        has_pairs = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='pairwise_comparisons'").fetchone()
        pair_rows = connection.execute("""SELECT payload_json,choice FROM pairwise_comparisons
            WHERE profile_id=? AND choice IN ('a','b') ORDER BY updated_at DESC,rowid DESC LIMIT 32""",
            (profile,)).fetchall() if has_pairs else []
    comparisons = []
    for text, choice in pair_rows:
        pair = json.loads(text)
        comparisons.append(dict(choice=choice, winner=pair[choice],
            loser=pair['b' if choice == 'a' else 'a'], anchor=pair['anchor']))
    known = favorites + [song for song in feedback if song['liked']]
    names = {name for song in known for name in credited_artists(song)}
    ids = {item for song in known for item in artist_ids(song)}
    exclusions = {song['track_id'] for song in favorites + feedback}
    report = dict(profile=profile, favorite_count=len(favorites), feedback_count=len(feedback),
                  pairwise_count=len(comparisons), personal_database_writes=False, modes={})
    engine = MusicRecommender()
    with tempfile.TemporaryDirectory(dir=output.parent) as directory:
        cache = Path(directory) / 'language.sqlite3'
        original_cache = ROOT / 'data/sources/title_language.sqlite3'
        if original_cache.exists():
            with closing(sqlite3.connect(original_cache.resolve().as_uri()+'?mode=ro', uri=True)) as source:
                with closing(sqlite3.connect(cache)) as target:
                    source.backup(target)
        screen = TitleLanguageScreen(cache)
        for family, directional, label in (
            (False, False, 'prior_rules_emulated'),
            (True, False, 'family_coverage_only'),
            (True, True, 'coverage_and_directional_feedback'),
        ):
            configuration = replace(DEFAULT_RANKING, anchor_family_diversity=family)
            engine.config = engine.audio.config = configuration
            votes = copy.deepcopy(feedback)
            if not directional:
                for vote in votes:
                    if vote.get('feedback_reason') in ('Too slow', 'Too fast'):
                        vote['feedback_reason'] = None
            started = time.perf_counter()
            with screen.session():
                results = engine.recommend([song['track_id'] for song in favorites],
                    favorite_songs=favorites, feedback=votes, exclude_ids=exclusions,
                    known_artist_names=names, known_artist_ids=ids,
                    candidate_filter=screen.allows, pairwise_feedback=comparisons)
            report['modes'][label] = dict(seconds=time.perf_counter()-started,
                distinct_anchor_credits=len({song.get('matched_anchor', {}).get('artists') for song in results}),
                results=[dict(track=song['track_name'], artists=song['artists'],
                    anchor=song.get('matched_anchor', {}).get('artists'),
                    distance=song.get('distance'), score=song.get('ranking_score'),
                    components=song.get('score_components'),
                    selection=song.get('selection_context')) for song in results])
    report['limitation'] = ('Fixed-input ablation emulates prior selection by disabling family coverage and treating tempo reasons as generic No. '
        'Different cache warmth prevents a timing comparison; this is not a blinded quality evaluation.')
    output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
