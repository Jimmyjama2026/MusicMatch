"""Offline catalog enrichment; provider associations are not acoustic similarity.

The audio engine remains the fallback. Text experiments are deliberately separate.
"""
from collections import defaultdict
import json
import math
from pathlib import Path
from uuid import UUID

if __package__:
    from .backend import DATA_DIR
    from .neighborhoods import MusicRecommender as AudioRecommender
    from .identity import normalized, song_identity as identity, credited_artists, artist_ids
    from .ranking_config import DEFAULT_RANKING
    from .selection import discovery_unavailable
    from .preference_policy import validate_steering, POLICY_VERSION
else:
    from backend import DATA_DIR
    from neighborhoods import MusicRecommender as AudioRecommender
    from identity import normalized, song_identity as identity, credited_artists, artist_ids
    from ranking_config import DEFAULT_RANKING
    from selection import discovery_unavailable
    from preference_policy import validate_steering, POLICY_VERSION

VERSION = "audio-listening-heuristic-v1"
RICH_VERSION = "rich-neighborhoods-discovery-listening-v4"


def valid_mbid(value):
    try:
        return isinstance(value, str) and str(UUID(value)) == value
    except (ValueError, TypeError, AttributeError):
        return False


class MusicRecommender:
    """Network-free facade with conservative identity mapping and bounded ranking."""

    def __init__(self, dataset_path=None, enrichment_path=None, config=DEFAULT_RANKING):
        self.config = config
        self.audio = AudioRecommender(dataset_path, config=config)
        self.catalog = {}
        self.edges = defaultdict(dict)
        self.audio_to_mbid = {}
        self.mbid_to_audio = {}
        self.artist_names = {}
        self.identity_ids = defaultdict(set)
        self.enrichment_warning = None
        if dataset_path is not None and enrichment_path is None:
            return  # Synthetic/custom catalogs never pick up unrelated production enrichment.
        path = Path(enrichment_path) if enrichment_path else DATA_DIR / "enrichment" / "catalog.json"
        if not path.exists():
            return
        try:
            if path.stat().st_size > 25_000_000:
                raise ValueError("Enrichment catalog exceeds 25 MB loading limit.")
            document = json.loads(path.read_text(encoding="utf-8"))
            self._load(document)
        except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
            # Optional enrichment must never prevent the original app from loading.
            self.catalog.clear()
            self.edges.clear()
            self.audio_to_mbid.clear()
            self.mbid_to_audio.clear()
            self.artist_names.clear()
            self.identity_ids.clear()
            self.enrichment_warning = str(error)

    def _load(self, document):
        if document.get("schema_version") != 1:
            raise ValueError("Unsupported enrichment schema.")
        reviewed = defaultdict(set)
        known_names = defaultdict(set)
        for artist in document.get("artists", []):
            if valid_mbid(artist.get("mbid")):
                for name in (artist.get("name"), artist.get("requested_name")):
                    if isinstance(name, str) and name.strip():
                        known_names[normalized(name)].add(artist["mbid"])
                        if artist.get("match_confidence") == "manually_verified":
                            reviewed[normalized(name)].add(artist["mbid"])
        tracks = document.get("tracks", [])
        edges = document.get("related_edges", [])
        if not isinstance(tracks, list) or len(tracks) > 10000 or not isinstance(edges, list) or len(edges) > 100000:
            raise ValueError("Invalid enrichment bounds.")
        for track in tracks:
            mbid, title = track["mbid"], track["title"]
            names, artist_ids = track["artist_names"], track["artist_mbids"]
            if (not valid_mbid(mbid) or not isinstance(title, str) or not title.strip()
                    or not isinstance(names, list) or not names or not all(isinstance(n, str) and n.strip() for n in names)
                    or not isinstance(artist_ids, list) or not artist_ids or not all(valid_mbid(a) for a in artist_ids)
                    or track.get("source") not in ("musicbrainz", "listenbrainz_musicbrainz_metadata")
                    or track.get("license") != "CC0-1.0"):
                raise ValueError("Invalid or unlicensed catalog identity.")
            self.catalog[mbid] = {"track_id": "mb:" + mbid, "track_name": title.strip(),
                "artists": "; ".join(n.strip() for n in names), "recording_mbid": mbid,
                "artist_mbids": artist_ids, "duration_ms": track.get("duration_ms"),
                "credit_complete": track.get("credit_complete", True),
                "source": track["source"], "license": "CC0-1.0", "audio_features_available": False}
            note = track.get("disambiguation")
            if isinstance(note, str) and note.strip():
                self.catalog[mbid]["version_note"] = note.strip()
                self.catalog[mbid]["display_title"] = f"{title.strip()} ({note.strip()})"
            if len(names) == len(artist_ids):
                for name, artist_id in zip(names, artist_ids):
                    known_names[normalized(name)].add(artist_id)
        self.artist_names = {name: next(iter(ids)) for name, ids in reviewed.items()
                             if len(ids) == 1 and len(known_names[name]) == 1}
        if not self.catalog:
            return
        by_identity = defaultdict(list)
        for song in self.catalog.values():
            # Presentation/exclusion aliases only; this does not establish a
            # recording mapping or transfer audio measurements between IDs.
            self.identity_ids[identity(song)].add(song["track_id"])
            if song["credit_complete"]:
                by_identity[identity(song)].append(song)
        audio_matches = defaultdict(list)
        titles = {s["track_name"].casefold() for s in self.catalog.values()}
        # Vectorized prefilter avoids normalizing all 200k audio credits at startup.
        for song in self.audio.songs_with_titles(titles):
            self.identity_ids[identity(song)].add(song["track_id"])
            candidates = by_identity.get(identity(song), [])
            # Title+full credit AND duration agreement; ambiguous versions stay unmapped.
            duration = song.get("duration_ms")
            if not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration <= 0:
                continue
            candidates = [s for s in candidates if isinstance(s.get("duration_ms"), (int, float))
                          and math.isfinite(s["duration_ms"]) and abs(s["duration_ms"] - duration) <= 2000]
            if len(candidates) == 1:
                audio_matches[candidates[0]["recording_mbid"]].append(song["track_id"])
        for mbid, ids in audio_matches.items():
            if len(ids) == 1:
                self.audio_to_mbid[ids[0]] = mbid
                self.mbid_to_audio[mbid] = ids[0]
        for edge in edges:
            seed, recording = edge["seed_artist_mbid"], edge["recording_mbid"]
            if (not valid_mbid(seed) or not valid_mbid(recording)
                    or edge.get("source") != "listenbrainz" or edge.get("license") != "CC0-1.0"):
                raise ValueError("Invalid or unlicensed recommendation edge.")
            if recording not in self.catalog:
                continue  # Partially capped acquisition may lack neighbor metadata.
            self.edges[seed][recording] = True

    def get_song(self, track_id):
        if isinstance(track_id, str) and track_id.startswith("mb:") and track_id[3:] in self.catalog:
            return dict(self.catalog[track_id[3:]])
        return self.audio.get_song(track_id)

    def search(self, query, artist_query="", title_only=False):
        original = self.audio.search(query, artist_query, title_only)
        if not self.catalog or not (query.strip() or artist_query.strip()):
            return original
        title, artist = normalized(query), normalized(artist_query)
        keys = {(identity(s), normalized(s.get("version_note", ""))) for s in original}
        extra = []
        for mbid, song in self.catalog.items():
            key = identity(song), normalized(song.get("version_note", ""))
            if mbid in self.mbid_to_audio or key in keys:
                continue
            if artist not in normalized(song["artists"]):
                continue
            if title and title not in normalized(song["track_name"]) and (title_only or artist or title not in normalized(song["artists"])):
                continue
            keys.add(key)
            extra.append(dict(song))
        combined = original + extra
        combined.sort(key=lambda s: normalized(s["track_name"]) != title if title else False)
        return combined[:10]

    def recommend(self, favorite_ids, limit=5, favorite_songs=None, feedback=None, exclude_ids=None, known_artist_names=None, known_artist_ids=None, *, steering="same", pairwise_feedback=None, candidate_filter=None):
        validate_steering(steering)
        options = {"steering": steering, "pairwise_feedback": pairwise_feedback, "candidate_filter": candidate_filter}
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
            raise ValueError("Recommendation limit must be a positive integer.")
        ids = list(dict.fromkeys(favorite_ids))
        if not ids:
            raise ValueError("Add at least one favorite before asking for recommendations.")
        snapshots = {s["track_id"]: s for s in (favorite_songs or [])}
        favorites, audio_favorites, seed_ids = [], [], set()
        for track_id in ids:
            try:
                song = self.get_song(track_id)
            except ValueError:
                if track_id not in snapshots:
                    raise ValueError("A favorite is absent and has no saved context.") from None
                song = snapshots[track_id]
            favorites.append(song)
            try:
                audio_id = self.mbid_to_audio.get(track_id[3:]) if track_id.startswith("mb:") else None
                audio_song = self.audio.get_song(audio_id) if audio_id else song
                if self.audio.has_audio_features(audio_song):
                    audio_favorites.append(audio_song)
            except ValueError:
                pass
            mbid = self.audio_to_mbid.get(track_id) or (track_id[3:] if track_id.startswith("mb:") else None)
            if mbid in self.catalog:
                seed_ids.update(self.catalog[mbid]["artist_mbids"])
            # Provider relationships are artist-based, so a reviewed exact credited
            # artist name can seed them without claiming a matched recording ID.
            for name in credited_artists(song):
                seed = self.artist_names.get(normalized(name))
                if seed:
                    seed_ids.add(seed)
        excluded = set(exclude_ids or ()) | set(ids)
        favorite_keys = {identity(s) for s in favorites}
        rated = {}
        for item in (feedback or []):
            if isinstance(item.get("liked"), bool) and item.get("track_id") not in rated:
                rated[item.get("track_id")] = item
                if len(rated) >= 500:
                    break
        known_names = {normalized(name) for name in (known_artist_names or ())}
        known_names.update(name for song in favorites for name in credited_artists(song))
        known_names.update(name for song in rated.values() if song["liked"] for name in credited_artists(song))
        known_ids = set(known_artist_ids or ())
        known_ids.update(token for song in favorites for token in artist_ids(song))
        known_ids.update(token for song in rated.values() if song["liked"] for token in artist_ids(song))
        excluded.update(item["track_id"] for item in rated.values() if not item["liked"])
        # Apply the same title/full-credit deduplication policy to No/Fresh
        # exclusions, even when incomplete credits prevent a recording mapping.
        excluded_keys = set(favorite_keys)
        for track_id in tuple(excluded):
            try:
                song = self.get_song(track_id)
            except ValueError:
                song = snapshots.get(track_id) or rated.get(track_id)
            if song and "track_name" in song and "artists" in song:
                key = identity(song)
                excluded_keys.add(key)
                excluded.update(self.identity_ids.get(key, ()))
        support = defaultdict(set)
        for seed in seed_ids:
            for mbid in self.edges.get(seed, {}):
                support[mbid].add(seed)
        if not support and len(audio_favorites) == len(favorites):
            results = self.audio.recommend([s["track_id"] for s in audio_favorites], limit,
                favorite_songs=audio_favorites, feedback=feedback, exclude_ids=excluded,
                known_artist_names=known_names if self.audio.vectors_active or known_artist_names is not None else None,
                known_artist_ids=known_ids, **options)
            if ids != [s["track_id"] for s in audio_favorites]:
                for song in results:
                    song["favorite_resolution"] = {"selected_ids": ids,
                        "audio_input_ids": [s["track_id"] for s in audio_favorites]}
            return results
        base = []
        candidate_union_context = None
        if audio_favorites:
            if self.audio.vectors_active:
                # Only conservative recording joins enter this union. Every joined
                # track is measured with the same anchor metric before graph bonus.
                available_graph_ids = {self.mbid_to_audio[mbid] for mbid in support if mbid in self.mbid_to_audio}
                graph_ids = sorted(available_graph_ids,
                    key=lambda track_id: (-len(support[self.audio_to_mbid[track_id]]), track_id))[:self.config.max_explicit_candidates]
                base = self.audio.recommend([s["track_id"] for s in audio_favorites], max(50, limit),
                    favorite_songs=audio_favorites, feedback=feedback, exclude_ids=excluded,
                    diversify=False, extra_candidate_ids=graph_ids, known_artist_names=known_names, known_artist_ids=known_ids, **options)
                eligible_graph_ids = {song["track_id"] for song in base} & set(graph_ids)
                candidate_union_context = {"joined_graph_candidates_available": len(available_graph_ids),
                    "joined_graph_candidates_requested": len(graph_ids), "joined_graph_candidates_eligible": len(eligible_graph_ids),
                    "graph_candidates_capped": len(available_graph_ids) > len(graph_ids),
                    "union_size": len(base)}
            else:
                base = self.audio.recommend([s["track_id"] for s in audio_favorites], max(50, limit),
                    favorite_songs=audio_favorites, feedback=feedback, exclude_ids=excluded, **options)
        artist_votes = defaultdict(list)
        for item in rated.values():
            if not item["liked"] and item.get("feedback_reason") == "Already know it":
                continue  # Exclude familiarity without learning an artist dislike.
            for artist in credited_artists(item):
                artist_votes[normalized(artist)].append(1 if item["liked"] else -1)
        def vote_adjustment(song):
            votes = [v for a in credited_artists(song) for v in artist_votes.get(normalized(a), [])]
            bound = self.config.rich_artist_vote_bound if self.audio.vectors_active else self.config.legacy_artist_vote_bound
            return bound * sum(votes) / (len(votes) + 4)
        for song in base:
            mbid = self.audio_to_mbid.get(song["track_id"])
            fraction = len(support.get(mbid, ())) / max(1, len(seed_ids))
            if fraction:
                bonus = (self.config.rich_listening_bonus if self.audio.vectors_active else self.config.legacy_listening_bonus) * fraction + vote_adjustment(song)
                song["audio_model_version"] = song["model_version"]
                song["audio_ranking_score"] = song["ranking_score"]
                song["listening_support"] = fraction
                song["ranking_score"] -= bonus
                song["listening_adjustment"] = -bonus
                song.setdefault("score_components", {})["listening_adjustment"] = -bonus
                song["model_version"] = RICH_VERSION if self.audio.vectors_active else VERSION
                song["reason_preview"] = song.get("reason_preview", "Audio-feature match.") + " Additional ListenBrainz artist-based evidence."
                song["reason"] += f" ListenBrainz artist-based recommendation support: {fraction:.0%} of matched favorite artist IDs; bounded heuristic adjustment {-bonus:+.3f}. Artist seeds can use exact names matched to reviewed artist IDs; this does not establish a matched recording. This is listening association, not evidence of similar sound."
        base = [s for s in base if s["track_id"] not in excluded and identity(s) not in excluded_keys]
        base.sort(key=lambda s: s["ranking_score"])
        def unique_songs(songs):
            seen = set()
            for song in songs:
                key = identity(song)
                if key not in seen:
                    seen.add(key)
                    yield song
        base = list(unique_songs(base))
        discoveries = []
        baseline_ids = {s["track_id"] for s in base}
        baseline_keys = {identity(s) for s in base}
        for mbid, seeds in support.items():
            audio_id = self.mbid_to_audio.get(mbid)
            if audio_id in baseline_ids:
                continue
            song = self.audio.get_song(audio_id) if audio_id else dict(self.catalog[mbid])
            if song["track_id"] in excluded or identity(song) in excluded_keys or identity(song) in baseline_keys:
                continue
            strength = len(seeds) / max(1, len(seed_ids))
            song.update(model_version=VERSION, listening_support=strength,
                ranking_config=self.config.provenance(),
                ranking_score=-(strength + vote_adjustment(song)),
                reason_preview="ListenBrainz artist-based discovery; audio and lyric similarity are unknown.",
                reason=f"ListenBrainz recommended this recording from {len(seeds)} of your {len(seed_ids)} matched favorite artist IDs. Artist seeds can use exact credited names matched to reviewed IDs, without a recording match. No audio features or lyrical comparison were used for this discovery. Ranking uses artist support and a small adjustment from this profile's artist ratings; it is an experimental heuristic.")
            if candidate_filter is None or candidate_filter(song):
                discoveries.append(song)
        discoveries.sort(key=lambda s: (s["ranking_score"], s["track_id"]))
        discoveries = list(unique_songs(discoveries))
        if base:
            # At most one separately labelled discovery; incomparable score scales are not mixed.
            results = self.audio.select_candidates(base, limit, self.config, known_names) if self.audio.vectors_active else base[:limit]
            if discoveries and limit > 1 and not self.audio.vectors_active:
                results = base[:limit - 1] + discoveries[:1]
        else:
            # Exhausting the scored rich channel must not silently switch a
            # sound-based request to metadata-only recommendations.
            results = [] if self.audio.vectors_active and audio_favorites else discoveries[:limit]
        for song in results:
            if steering != "same" and "steering_context" not in song:
                song["steering_context"] = {"version": POLICY_VERSION, "option": steering,
                    "applied": False, "score_adjustment": 0., "target": None,
                    "method": "Request steering requires measured rich audio features."}
            if candidate_union_context is not None:
                song["candidate_union_context"] = dict(candidate_union_context)
            if "distance" in song:
                song.setdefault("audio_model_version", song.get("model_version"))
            song["model_version"] = RICH_VERSION if song.get("neighborhood_context") else VERSION
            song["favorite_resolution"] = {"selected_ids": ids,
                "audio_input_ids": [s["track_id"] for s in audio_favorites]}
            song["audio_favorite_count"] = len(audio_favorites)
            song["mapped_favorite_artist_count"] = len(seed_ids)
            if len(audio_favorites) < len(favorites) and "distance" in song:
                song["reason_preview"] = "Audio match using favorites with known audio features; other favorites have limited data."
                song["reason"] += f" Audio comparison used {len(audio_favorites)} of {len(favorites)} favorites; missing features were not estimated."
        if not results and not audio_favorites and not support:
            raise ValueError("These catalog favorites have no cached listening recommendations yet. Add an existing audio-feature favorite or refresh enrichment outside the app.")
        if known_artist_names is not None and results and not results[0].get("neighborhood_context"):
            results = discovery_unavailable(results, limit, self.config)
        return results
