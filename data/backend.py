"""Audio-feature recommendations and durable, human-labelled context.

Profile feedback provides a small, bounded audio-feature ranking adjustment.
"""
from __future__ import annotations

from difflib import get_close_matches
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

import numpy as np
import pandas as pd
if __package__:
    from .comparisons import candidate_pair
else:
    from comparisons import candidate_pair
from sklearn.metrics.pairwise import euclidean_distances
from sklearn.preprocessing import MinMaxScaler

FEATURES = ("valence", "tempo", "energy", "danceability")
MODEL_VERSION = "audio-four-features-feedback-v2"
DATA_DIR = Path(__file__).resolve().parent
FEEDBACK_REASONS = ("Too slow", "Too fast", "Wrong mood", "Not my style", "Already know it", "Other")


class MusicRecommender:
    def __init__(self, dataset_path=None):
        table = pd.read_csv(dataset_path or DATA_DIR / "dataset.csv")
        required = {"track_id", "track_name", "artists", *FEATURES}
        missing = required.difference(table.columns)
        if missing:
            raise ValueError("Dataset is missing columns: " + ", ".join(sorted(missing)))
        table = table.dropna(subset=["track_id", "track_name", "artists"]).copy()
        for name in ("track_id", "track_name", "artists"):
            table[name] = table[name].astype(str).str.strip()
            table = table[table[name] != ""]
        for name in FEATURES:
            table[name] = pd.to_numeric(table[name], errors="coerce")
        values = table[list(FEATURES)]
        valid = np.isfinite(values).all(axis=1)
        for name in ("valence", "energy", "danceability"):
            valid &= table[name].between(0, 1)
        valid &= table["tempo"].gt(0)
        table = table.loc[valid].drop_duplicates("track_id")
        # Same recording can occur under different IDs in compilation albums.
        keys = table["track_name"].str.casefold() + "\0" + table["artists"].str.casefold()
        table = table.loc[~keys.duplicated()].reset_index(drop=True)
        if table.empty:
            raise ValueError("Dataset contains no songs with valid audio features.")
        self.table = table
        # Bound each C-level JSON conversion so loading on the worker cannot
        # hold Python's GIL across the entire catalog and stall the Qt thread.
        self._songs = []
        for start in range(0, len(table), 2000):
            self._songs.extend(json.loads(table.iloc[start:start + 2000].to_json(orient="records")))
        self._indices = {song["track_id"]: i for i, song in enumerate(self._songs)}
        self._titles = table["track_name"].str.casefold()
        self._artists = table["artists"].str.casefold()
        self.scaler = MinMaxScaler()
        self.scaled = self.scaler.fit_transform(table[list(FEATURES)])

    def get_song(self, track_id):
        try:
            return dict(self._songs[self._indices[track_id]])
        except KeyError:
            raise ValueError("Selected song is not available in this dataset.") from None

    def search(self, query, artist_query="", title_only=False):
        """Search title/artist, or constrain title matches to an explicit artist.

        With an artist filter, fuzzy title matches also stay inside that filter.
        An empty title is supported for artist-only searches.
        """
        query = query.strip().casefold()
        artist_query = artist_query.strip().casefold()
        if not query and not artist_query:
            return []
        artist_mask = self._artists.str.contains(artist_query, regex=False)
        if not query:
            exact_artist = self._artists.eq(artist_query)
            indices = self.table.index[exact_artist].tolist()
            indices += self.table.index[artist_mask & ~exact_artist].tolist()
            return [dict(self._songs[i]) for i in indices[:10]]
        exact = self._titles.eq(query) & artist_mask
        contains = self._titles.str.contains(query, regex=False)
        if not artist_query and not title_only:
            contains |= self._artists.str.contains(query, regex=False)
        contains &= artist_mask
        indices = self.table.index[exact].tolist()
        indices += self.table.index[contains & ~exact].tolist()
        if len(indices) < 10:
            close = get_close_matches(query, self._titles[artist_mask].unique().tolist(), n=5, cutoff=0.65)
            for index in self.table.index[self._titles.isin(close) & artist_mask]:
                if index not in indices:
                    indices.append(index)
        return [dict(self._songs[i]) for i in indices[:10]]

    @staticmethod
    def _snapshot_features(song):
        try:
            values = np.array([float(song[name]) for name in FEATURES], dtype=float)
        except (KeyError, TypeError, ValueError):
            raise ValueError("A saved song is missing valid audio features.") from None
        if not np.isfinite(values).all() or values[1] <= 0 or any(
            not 0 <= values[index] <= 1 for index in (0, 2, 3)
        ):
            raise ValueError("A saved song has invalid audio features.")
        return values

    def recommend(self, favorite_ids, limit=5, favorite_songs=None, feedback=None, exclude_ids=None):
        favorite_ids = list(dict.fromkeys(favorite_ids))
        if not favorite_ids:
            raise ValueError("Add at least one favorite before asking for recommendations.")
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
            raise ValueError("Recommendation limit must be a positive integer.")
        snapshots = {song["track_id"]: song for song in (favorite_songs or [])}
        favorites = []
        for track_id in favorite_ids:
            if track_id in self._indices:
                favorites.append(self.get_song(track_id))
            elif track_id in snapshots:
                favorites.append(snapshots[track_id])
            else:
                raise ValueError("A favorite is absent from the catalog and has no saved audio features.")
        raw_favorites = np.array([self._snapshot_features(song) for song in favorites])
        # The fitted scaler expects named columns, including for old catalog snapshots.
        favorites_scaled = self.scaler.transform(pd.DataFrame(raw_favorites, columns=FEATURES))
        distances = euclidean_distances(self.scaled, favorites_scaled).mean(axis=1)
        favorite_keys = {
            (str(song["track_name"]).strip().casefold(), str(song["artists"]).strip().casefold())
            for song in favorites
        }
        excluded_ids = set(exclude_ids or ()) | set(favorite_ids)
        excluded = np.array([
            song["track_id"] in excluded_ids or
            (song["track_name"].casefold(), song["artists"].casefold()) in favorite_keys
            for song in self._songs
        ])
        distances[excluded] = np.inf
        adjustment = np.zeros(len(self._songs))
        usable_feedback = []
        seen_feedback = set()
        # Store supplies newest-first, unique tracks. Direct callers get the same cap.
        for item in (feedback or []):
            track_id = item.get("track_id")
            if track_id in seen_feedback or not isinstance(item.get("liked"), bool):
                continue
            try:
                values = self._snapshot_features(item)
            except ValueError:
                continue
            seen_feedback.add(track_id)
            usable_feedback.append((values, item["liked"]))
            if len(usable_feedback) == 500:
                break
        if usable_feedback:
            for liked, direction in ((True, -1), (False, 1)):
                examples = [values for values, vote in usable_feedback if vote == liked]
                if not examples:
                    continue
                scaled_examples = self.scaler.transform(pd.DataFrame(examples, columns=FEATURES))
                # Chunk candidate rows to bound temporary memory with 500 examples.
                # Each class contributes at most .12, so total shift is [-.12,.12].
                for start in range(0, len(self._songs), 512):
                    stop = start + 512
                    squared = euclidean_distances(self.scaled[start:stop], scaled_examples, squared=True)
                    adjustment[start:stop] += direction * .12 * np.exp(-squared / .25).mean(axis=1)
        scores = distances + adjustment
        ranked = np.argsort(scores, kind="stable")
        target = dict(zip(FEATURES, raw_favorites.mean(axis=0)))
        feature_differences = np.abs(self.scaled - favorites_scaled.mean(axis=0))
        results = []
        for index in ranked:
            if not np.isfinite(scores[index]) or len(results) >= limit:
                break
            song = dict(self._songs[index])
            closest = np.argsort(feature_differences[index], kind="stable")[:2]
            comparisons = []
            for feature_index in closest:
                name = FEATURES[feature_index]
                label = "mood (valence)" if name == "valence" else name
                if name == "tempo":
                    comparisons.append(f"tempo {song[name]:.0f} BPM versus {target[name]:.0f} BPM")
                else:
                    comparisons.append(f"{label} {song[name]:.2f} versus {target[name]:.2f}")
            song["distance"] = float(distances[index])
            song["ranking_score"] = float(scores[index])
            song["feedback_adjustment"] = float(adjustment[index])
            song["model_version"] = MODEL_VERSION
            song["reason"] = (
                "Selected by comparing mood, tempo, energy and danceability with your favorites. "
                "Its two smallest scaled differences from your favorites' average are "
                + "; ".join(comparisons) + ". Lower audio distance means a closer feature match."
            )
            if usable_feedback:
                song["reason"] += (
                    f" Your profile's {len(usable_feedback)} recent ratings adjusted the ranking score "
                    f"by {adjustment[index]:+.3f}; similar Yes ratings lower it and similar No ratings raise it. "
                    "This is a small feature-based preference adjustment, not a guarantee of taste."
                )
            results.append(song)
        return results


class FeedbackStore:
    """Durable profile-scoped context; each operation closes its connection."""
    PROFILES = (
        {"id": "personal", "name": "Personal", "is_test": False},
        {"id": "test", "name": "Test", "is_test": True},
    )

    def __init__(self, db_path=None):
        self.path = Path(db_path or DATA_DIR / "feedback.sqlite3")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            # Explicit transaction keeps ALTER TABLE, migrated state and version atomic.
            connection.execute("BEGIN IMMEDIATE")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version > 5:
                raise ValueError("This database was created by a newer MusicMatch version.")
            statements = (
                """CREATE TABLE IF NOT EXISTS profiles (
                    profile_id TEXT PRIMARY KEY, name TEXT NOT NULL, is_test INTEGER NOT NULL
                )""",
                """CREATE TABLE IF NOT EXISTS recommendation_batches (
                    batch_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                    model_version TEXT NOT NULL, favorites_json TEXT NOT NULL,
                    profile_id TEXT NOT NULL DEFAULT 'personal' REFERENCES profiles(profile_id)
                )""",
                """CREATE TABLE IF NOT EXISTS recommendations (
                    batch_id TEXT NOT NULL REFERENCES recommendation_batches(batch_id),
                    track_id TEXT NOT NULL, song_json TEXT NOT NULL,
                    PRIMARY KEY (batch_id, track_id)
                )""",
                """CREATE TABLE IF NOT EXISTS feedback (
                    batch_id TEXT NOT NULL, track_id TEXT NOT NULL,
                    liked INTEGER NOT NULL CHECK (liked IN (0,1)),
                    reason TEXT,
                    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                    PRIMARY KEY (batch_id, track_id),
                    FOREIGN KEY (batch_id, track_id) REFERENCES recommendations(batch_id, track_id)
                )""",
                """CREATE TABLE IF NOT EXISTS profile_state (
                    profile_id TEXT PRIMARY KEY REFERENCES profiles(profile_id),
                    favorites_json TEXT NOT NULL DEFAULT '[]', latest_batch_id TEXT
                )""",
                """CREATE TABLE IF NOT EXISTS app_settings (
                    key TEXT PRIMARY KEY, value TEXT NOT NULL
                )""",
                """CREATE TABLE IF NOT EXISTS pairwise_comparisons (
                    comparison_id TEXT PRIMARY KEY,
                    profile_id TEXT NOT NULL REFERENCES profiles(profile_id),
                    batch_id TEXT NOT NULL REFERENCES recommendation_batches(batch_id),
                    pair_key TEXT NOT NULL, payload_json TEXT NOT NULL,
                    choice TEXT CHECK(choice IN ('a','b','equal','skip')),
                    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                    UNIQUE(profile_id, pair_key)
                )""",
            )
            connection.execute(statements[0])
            connection.executemany(
                "INSERT OR IGNORE INTO profiles VALUES (?,?,?)",
                [(p["id"], p["name"], int(p["is_test"])) for p in self.PROFILES],
            )
            for statement in statements[1:]:
                connection.execute(statement)
            columns = {row[1] for row in connection.execute("PRAGMA table_info(recommendation_batches)")}
            if "profile_id" not in columns:
                # SQLite cannot ALTER ADD a non-NULL REFERENCES column with a
                # non-NULL default while foreign keys are enabled. Ownership is
                # validated by the API; newly created schemas also have the FK.
                connection.execute("ALTER TABLE recommendation_batches ADD COLUMN profile_id TEXT NOT NULL DEFAULT 'personal'")
            feedback_columns = {row[1] for row in connection.execute("PRAGMA table_info(feedback)")}
            if "reason" not in feedback_columns:
                connection.execute("ALTER TABLE feedback ADD COLUMN reason TEXT")
            connection.execute("""CREATE TABLE IF NOT EXISTS feedback_events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL UNIQUE,
                profile_id TEXT NOT NULL REFERENCES profiles(profile_id),
                batch_id TEXT NOT NULL, track_id TEXT NOT NULL,
                liked INTEGER NOT NULL CHECK(liked IN (0,1)), reason TEXT,
                judged_at TEXT NOT NULL,
                FOREIGN KEY(batch_id,track_id) REFERENCES recommendations(batch_id,track_id)
            )""")
            connection.execute("""CREATE TABLE IF NOT EXISTS comparison_events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL UNIQUE,
                profile_id TEXT NOT NULL REFERENCES profiles(profile_id), comparison_id TEXT NOT NULL,
                action TEXT NOT NULL, choice TEXT,
                judged_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
            )""")
            connection.execute("""CREATE TABLE IF NOT EXISTS favorite_events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL UNIQUE,
                profile_id TEXT NOT NULL REFERENCES profiles(profile_id), favorites_json TEXT NOT NULL,
                changed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
            )""")
            if version < 5:
                # Older versions retained only the current vote. Do not invent earlier votes.
                connection.execute("""INSERT OR IGNORE INTO feedback_events
                    (event_id,profile_id,batch_id,track_id,liked,reason,judged_at)
                    SELECT 'legacy:' || f.batch_id || ':' || f.track_id,b.profile_id,
                           f.batch_id,f.track_id,f.liked,f.reason,f.updated_at
                    FROM feedback f JOIN recommendation_batches b USING(batch_id)
                    ORDER BY f.updated_at,f.rowid""")
            for profile in self.PROFILES:
                latest = connection.execute(
                    "SELECT batch_id, favorites_json FROM recommendation_batches WHERE profile_id=? ORDER BY rowid DESC LIMIT 1",
                    (profile["id"],),
                ).fetchone()
                connection.execute(
                    "INSERT OR IGNORE INTO profile_state(profile_id, favorites_json, latest_batch_id) VALUES (?,?,?)",
                    (profile["id"], latest[1] if latest else "[]", latest[0] if latest else None),
                )
            connection.execute("INSERT OR IGNORE INTO app_settings VALUES ('active_profile','personal')")
            connection.execute("CREATE INDEX IF NOT EXISTS batches_profile ON recommendation_batches(profile_id)")
            connection.execute("CREATE INDEX IF NOT EXISTS feedback_events_profile ON feedback_events(profile_id,sequence)")
            connection.execute("PRAGMA user_version = 5")

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            with connection:
                yield connection
        finally:
            connection.close()

    @classmethod
    def _validate_profile(cls, profile_id):
        if profile_id not in {profile["id"] for profile in cls.PROFILES}:
            raise ValueError("Unknown profile. Choose Personal or Test.")

    def list_profiles(self):
        return [dict(profile) for profile in self.PROFILES]

    def get_active_profile(self):
        with self._connect() as connection:
            row = connection.execute("SELECT value FROM app_settings WHERE key='active_profile'").fetchone()
        profile_id = row[0] if row else "personal"
        self._validate_profile(profile_id)
        return profile_id

    def set_active_profile(self, profile_id):
        self._validate_profile(profile_id)
        with self._connect() as connection:
            connection.execute("UPDATE app_settings SET value=? WHERE key='active_profile'", (profile_id,))

    def save_favorites(self, profile_id, favorites):
        self._validate_profile(profile_id)
        favorites_json = json.dumps(favorites, allow_nan=False)
        ids = [song["track_id"] for song in favorites]
        with self._connect() as connection:
            row = connection.execute("SELECT favorites_json FROM profile_state WHERE profile_id=?", (profile_id,)).fetchone()
            previous_ids = [song["track_id"] for song in json.loads(row[0])]
            connection.execute(
                """UPDATE profile_state SET favorites_json=?,
                latest_batch_id=CASE WHEN ? THEN latest_batch_id ELSE NULL END WHERE profile_id=?""",
                (favorites_json, ids == previous_ids, profile_id),
            )
            if json.loads(row[0]) != favorites:
                connection.execute("INSERT INTO favorite_events(event_id,profile_id,favorites_json) VALUES (?,?,?)",
                                   (str(uuid4()), profile_id, favorites_json))

    @staticmethod
    def _counts(connection, profile_id):
        row = connection.execute(
            """SELECT COALESCE(SUM(f.liked=1),0), COALESCE(SUM(f.liked=0),0)
            FROM feedback f JOIN recommendation_batches b ON f.batch_id=b.batch_id WHERE b.profile_id=?""",
            (profile_id,),
        ).fetchone()
        return tuple(row)

    def load_profile(self, profile_id):
        self._validate_profile(profile_id)
        with self._connect() as connection:
            # One read snapshot ensures a simultaneous save/reset cannot mix states.
            connection.execute("BEGIN")
            row = connection.execute("SELECT favorites_json, latest_batch_id FROM profile_state WHERE profile_id=?", (profile_id,)).fetchone()
            favorites, batch_id = json.loads(row[0]), row[1]
            recommendations = []
            if batch_id:
                rows = connection.execute(
                    """SELECT r.song_json, f.liked, f.reason FROM recommendations r
                    JOIN recommendation_batches b ON b.batch_id=r.batch_id
                    LEFT JOIN feedback f ON f.batch_id=r.batch_id AND f.track_id=r.track_id
                    WHERE r.batch_id=? AND b.profile_id=? ORDER BY r.rowid""",
                    (batch_id, profile_id),
                ).fetchall()
                for song_json, liked, reason in rows:
                    song = json.loads(song_json)
                    song["liked"] = None if liked is None else bool(liked)
                    song["feedback_reason"] = reason
                    recommendations.append(song)
            return {"favorites": favorites, "batch_id": batch_id,
                    "recommendations": recommendations, "counts": self._counts(connection, profile_id)}

    def save_batch(self, favorites, recommendations, profile_id="personal", *, active_favorites=None):
        self._validate_profile(profile_id)
        if not favorites or not recommendations:
            raise ValueError("A batch needs favorites and recommendations.")
        batch_id = str(uuid4())
        favorites_json = json.dumps(favorites, allow_nan=False)
        active_json = favorites_json if active_favorites is None else json.dumps(active_favorites, allow_nan=False)
        records = [(batch_id, song["track_id"], json.dumps(song, allow_nan=False)) for song in recommendations]
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO recommendation_batches(batch_id, model_version, favorites_json, profile_id) VALUES (?,?,?,?)",
                (batch_id, recommendations[0].get("model_version", MODEL_VERSION), favorites_json, profile_id),
            )
            connection.executemany("INSERT INTO recommendations VALUES (?,?,?)", records)
            connection.execute(
                "UPDATE profile_state SET favorites_json=?, latest_batch_id=? WHERE profile_id=?",
                (active_json, batch_id, profile_id),
            )
        return batch_id

    def save_feedback(self, batch_id, track_id, liked, profile_id="personal", reason=None):
        self._validate_profile(profile_id)
        if not isinstance(liked, bool):
            raise ValueError("Feedback must be Yes or No.")
        if reason is not None and reason not in FEEDBACK_REASONS:
            raise ValueError("Choose a supported feedback reason or leave it blank.")
        reason = None if liked else reason
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            owned = connection.execute(
                "SELECT 1 FROM recommendation_batches WHERE batch_id=? AND profile_id=?",
                (batch_id, profile_id),
            ).fetchone()
            if not owned:
                raise ValueError("This recommendation belongs to a different profile or no longer exists.")
            connection.execute("""
                INSERT INTO feedback(batch_id, track_id, liked, reason) VALUES (?,?,?,?)
                ON CONFLICT(batch_id, track_id) DO UPDATE SET
                    liked=excluded.liked, reason=excluded.reason,
                    updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
            """, (batch_id, track_id, int(liked), reason))
            connection.execute("""INSERT INTO feedback_events
                (event_id,profile_id,batch_id,track_id,liked,reason,judged_at)
                SELECT ?,?,batch_id,track_id,liked,reason,updated_at FROM feedback
                WHERE batch_id=? AND track_id=?""", (str(uuid4()), profile_id, batch_id, track_id))

    def feedback_counts(self, profile_id="personal"):
        self._validate_profile(profile_id)
        with self._connect() as connection:
            return self._counts(connection, profile_id)

    @staticmethod
    def _rating_clause(rating):
        clauses = {"all": "1=1", "yes": "f.liked=1", "no": "f.liked=0", "unrated": "f.liked IS NULL"}
        if rating not in clauses:
            raise ValueError("Rating filter must be all, yes, no, or unrated.")
        return clauses[rating]

    def list_history(self, profile_id, rating="all", limit=30, offset=0):
        """List batches having at least one recommendation matching the filter."""
        self._validate_profile(profile_id)
        clause = self._rating_clause(rating)
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 1000:
            raise ValueError("History limit must be an integer from 1 to 1000.")
        if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
            raise ValueError("History offset must be a nonnegative integer.")
        with self._connect() as connection:
            rows = connection.execute(
                f"""SELECT b.batch_id, b.created_at, b.favorites_json,
                    (SELECT COUNT(*) FROM recommendations all_r WHERE all_r.batch_id=b.batch_id)
                FROM recommendation_batches b WHERE b.profile_id=? AND EXISTS (
                    SELECT 1 FROM recommendations r LEFT JOIN feedback f
                    ON f.batch_id=r.batch_id AND f.track_id=r.track_id
                    WHERE r.batch_id=b.batch_id AND {clause}
                ) ORDER BY b.rowid DESC LIMIT ? OFFSET ?""", (profile_id, limit, offset),
            ).fetchall()
        return [{"batch_id": batch_id, "created_at": created_at,
                 "favorite_count": len(json.loads(favorites_json)), "recommendation_count": count}
                for batch_id, created_at, favorites_json, count in rows]

    def load_batch(self, profile_id, batch_id, rating="all"):
        """Read an original batch without changing favorites or current pointers."""
        self._validate_profile(profile_id)
        clause = self._rating_clause(rating)
        with self._connect() as connection:
            connection.execute("BEGIN")
            batch = connection.execute(
                "SELECT favorites_json, created_at FROM recommendation_batches WHERE profile_id=? AND batch_id=?",
                (profile_id, batch_id),
            ).fetchone()
            if batch is None:
                raise ValueError("This recommendation batch does not belong to this profile or no longer exists.")
            rows = connection.execute(
                f"""SELECT r.song_json, f.liked, f.reason FROM recommendations r LEFT JOIN feedback f
                ON f.batch_id=r.batch_id AND f.track_id=r.track_id
                WHERE r.batch_id=? AND {clause} ORDER BY r.rowid""", (batch_id,),
            ).fetchall()
            recommendations = []
            for song_json, liked, reason in rows:
                song = json.loads(song_json)
                song["liked"] = None if liked is None else bool(liked)
                song["feedback_reason"] = reason
                recommendations.append(song)
            return {"favorites": json.loads(batch[0]), "batch_id": batch_id,
                    "created_at": batch[1], "recommendations": recommendations}

    def clear_current_recommendations(self, profile_id):
        """Clear only the current pointer; historical context and votes remain."""
        self._validate_profile(profile_id)
        with self._connect() as connection:
            connection.execute("UPDATE profile_state SET latest_batch_id=NULL WHERE profile_id=?", (profile_id,))

    def recommendation_exclusions(self, profile_id, fresh=False):
        """Latest No votes are excluded; fresh mode also excludes every shown ID."""
        self._validate_profile(profile_id)
        if not isinstance(fresh, bool):
            raise ValueError("Fresh mode must be True or False.")
        with self._connect() as connection:
            if fresh:
                rows = connection.execute(
                    """SELECT DISTINCT r.track_id FROM recommendations r JOIN recommendation_batches b
                    ON b.batch_id=r.batch_id WHERE b.profile_id=?""", (profile_id,),
                ).fetchall()
            else:
                rows = connection.execute(
                    """SELECT track_id FROM (
                        SELECT f.track_id, f.liked, ROW_NUMBER() OVER (
                            PARTITION BY f.track_id ORDER BY f.updated_at DESC, f.rowid DESC
                        ) AS rank FROM feedback f JOIN recommendation_batches b ON b.batch_id=f.batch_id
                        WHERE b.profile_id=?
                    ) WHERE rank=1 AND liked=0""", (profile_id,),
                ).fetchall()
        return {row[0] for row in rows}

    def training_feedback(self, profile_id="personal"):
        """Up to 500 newest distinct-track ratings within this profile only."""
        self._validate_profile(profile_id)
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT song_json, liked, reason FROM (
                    SELECT r.song_json, f.liked, f.reason, f.updated_at, f.rowid AS vote_order,
                        ROW_NUMBER() OVER (PARTITION BY f.track_id
                            ORDER BY f.updated_at DESC, f.rowid DESC) AS rank
                    FROM feedback f
                    JOIN recommendations r ON r.batch_id=f.batch_id AND r.track_id=f.track_id
                    JOIN recommendation_batches b ON b.batch_id=f.batch_id
                    WHERE b.profile_id=?
                ) WHERE rank=1 ORDER BY updated_at DESC, vote_order DESC LIMIT 500""",
                (profile_id,),
            ).fetchall()
        feedback = []
        for song_json, liked, reason in rows:
            song = json.loads(song_json)
            song["liked"] = bool(liked)
            song["feedback_reason"] = reason
            feedback.append(song)
        return feedback

    def offer_comparison(self, profile_id, batch_id):
        """Save at most one contextual offer for a batch, without touching ratings."""
        self._validate_profile(profile_id)
        batch = self.load_batch(profile_id, batch_id)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT comparison_id FROM pairwise_comparisons WHERE profile_id=? AND batch_id=?",
                (profile_id, batch_id)).fetchone()
            if existing:
                return existing[0]
            seen = {row[0] for row in connection.execute(
                "SELECT pair_key FROM pairwise_comparisons WHERE profile_id=?", (profile_id,))}
            pair = candidate_pair(batch["recommendations"], seen)
            if pair is None:
                return None
            # Alternate left/right by offer count, not by song score or winner.
            if len(seen) % 2:
                pair["a"], pair["b"] = pair["b"], pair["a"]
            comparison_id = str(uuid4())
            connection.execute(
                "INSERT INTO pairwise_comparisons(comparison_id,profile_id,batch_id,pair_key,payload_json) VALUES (?,?,?,?,?)",
                (comparison_id, profile_id, batch_id, pair["pair_key"], json.dumps(pair, allow_nan=False)))
        return comparison_id

    def comparison_state(self, profile_id, batch_id=None):
        self._validate_profile(profile_id)
        with self._connect() as connection:
            offered = connection.execute(
                "SELECT comparison_id,payload_json,choice FROM pairwise_comparisons WHERE profile_id=? AND batch_id=?",
                (profile_id, batch_id)).fetchone() if batch_id else None
            latest = connection.execute(
                "SELECT comparison_id,choice FROM pairwise_comparisons WHERE profile_id=? AND choice IS NOT NULL ORDER BY updated_at DESC,rowid DESC LIMIT 1",
                (profile_id,)).fetchone()
            counts = connection.execute(
                "SELECT COUNT(*),COALESCE(SUM(choice IN ('a','b','equal')),0),COALESCE(SUM(choice IN ('a','b')),0) FROM pairwise_comparisons WHERE profile_id=?",
                (profile_id,)).fetchone()
        comparison = None
        if offered and offered[2] is None:
            comparison = dict(json.loads(offered[1]), id=offered[0], batch_id=batch_id, choice=None)
        return {"comparison": comparison,
                "last_comparison": {"id": latest[0], "choice": latest[1]} if latest else None,
                "comparison_stats": {"offered_count": counts[0], "count": counts[1], "active_count": counts[2]}}

    def choose_comparison(self, profile_id, comparison_id, choice):
        self._validate_profile(profile_id)
        if choice not in ("a", "b", "equal", "skip"):
            raise ValueError("Choose A, B, About equal or Skip.")
        with self._connect() as connection:
            result = connection.execute(
                "UPDATE pairwise_comparisons SET choice=?,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE profile_id=? AND comparison_id=?",
                (choice, profile_id, comparison_id))
            if result.rowcount != 1:
                raise ValueError("This comparison does not belong to this profile or no longer exists.")
            connection.execute("INSERT INTO comparison_events(event_id,profile_id,comparison_id,action,choice) VALUES (?,?,?,?,?)",
                               (str(uuid4()), profile_id, comparison_id, "choose", choice))

    def undo_comparison(self, profile_id, comparison_id):
        self._validate_profile(profile_id)
        with self._connect() as connection:
            result = connection.execute(
                "UPDATE pairwise_comparisons SET choice=NULL,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE profile_id=? AND comparison_id=?",
                (profile_id, comparison_id))
            if result.rowcount != 1:
                raise ValueError("This comparison does not belong to this profile or no longer exists.")
            connection.execute("INSERT INTO comparison_events(event_id,profile_id,comparison_id,action) VALUES (?,?,?,?)",
                               (str(uuid4()), profile_id, comparison_id, "undo"))

    def training_comparisons(self, profile_id):
        self._validate_profile(profile_id)
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT comparison_id,payload_json,choice FROM pairwise_comparisons WHERE profile_id=? AND choice IN ('a','b') ORDER BY updated_at DESC,rowid DESC LIMIT 32",
                (profile_id,)).fetchall()
        result = []
        for comparison_id, payload, choice in rows:
            pair = json.loads(payload)
            result.append(dict(id=comparison_id, choice=choice, anchor=pair["anchor"],
                winner=pair[choice], loser=pair["b" if choice == "a" else "a"],
                feature_version=pair.get("feature_version"), source_fingerprint=pair.get("source_fingerprint")))
        return result

    def reset_comparisons(self, profile_id):
        self._validate_profile(profile_id)
        with self._connect() as connection:
            connection.execute("DELETE FROM comparison_events WHERE profile_id=?", (profile_id,))
            connection.execute("DELETE FROM pairwise_comparisons WHERE profile_id=?", (profile_id,))

    def reset_profile(self, profile_id):
        self._validate_profile(profile_id)
        if profile_id != "test":
            raise ValueError("Only the Test profile can be reset. Personal data is protected.")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM feedback_events WHERE profile_id=?", (profile_id,))
            connection.execute("DELETE FROM comparison_events WHERE profile_id=?", (profile_id,))
            connection.execute("DELETE FROM favorite_events WHERE profile_id=?", (profile_id,))
            connection.execute("DELETE FROM pairwise_comparisons WHERE profile_id=?", (profile_id,))
            connection.execute("DELETE FROM feedback WHERE batch_id IN (SELECT batch_id FROM recommendation_batches WHERE profile_id=?)", (profile_id,))
            connection.execute("DELETE FROM recommendations WHERE batch_id IN (SELECT batch_id FROM recommendation_batches WHERE profile_id=?)", (profile_id,))
            connection.execute("DELETE FROM recommendation_batches WHERE profile_id=?", (profile_id,))
            connection.execute("UPDATE profile_state SET favorites_json='[]', latest_batch_id=NULL WHERE profile_id=?", (profile_id,))
