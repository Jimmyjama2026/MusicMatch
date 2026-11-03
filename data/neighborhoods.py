"""Offline rich-feature neighborhoods; no global taste centroid or training job."""
from pathlib import Path
from collections import defaultdict
import numpy as np
from scipy.spatial.distance import cdist

if __package__:
    from .backend import MusicRecommender as BaselineRecommender, DATA_DIR
    from .song_vectors import SongVectors, RAW_FEATURES
    from .identity import song_identity as song_key, credited_artists, artist_ids, normalized
    from .ranking_config import DEFAULT_RANKING
    from .selection import select_candidates, discovery_unavailable
    from .genres import load_evidence, effective_labels as genre_labels, effective_evidence, attach_artist_evidence, compatible as genre_compatible, ARTIST_VERSION as GENRE_VERSION
    from .preference_policy import validate_steering, steering_target, steering_adjustment, prepare_pairs, pairwise_adjustment, POLICY_VERSION
else:
    from backend import MusicRecommender as BaselineRecommender, DATA_DIR
    from song_vectors import SongVectors, RAW_FEATURES
    from identity import song_identity as song_key, credited_artists, artist_ids, normalized
    from ranking_config import DEFAULT_RANKING
    from selection import select_candidates, discovery_unavailable
    from genres import load_evidence, effective_labels as genre_labels, effective_evidence, attach_artist_evidence, compatible as genre_compatible, ARTIST_VERSION as GENRE_VERSION
    from preference_policy import validate_steering, steering_target, steering_adjustment, prepare_pairs, pairwise_adjustment, POLICY_VERSION

MODEL_VERSION = "rich-neighborhoods-artist-genre-fallback-v6"
GROUP_RADIUS = DEFAULT_RANKING.group_radius
ARTIST_MATCH_BONUS = DEFAULT_RANKING.artist_bonus


def _directional_negatives(negatives, vectors):
    """Use measured tempo only; unavailable evidence keeps the generic No path."""
    generic, directional, centers = [], [], []
    for item in negatives:
        reason = item.get("feedback_reason", item.get("reason"))
        try:
            tempo = float(item.get("tempo"))
        except (TypeError, ValueError):
            tempo = float("nan")
        if reason not in ("Too slow", "Too fast") or not np.isfinite(tempo) or tempo <= 0:
            generic.append(item)
            continue
        anchor = item.get("matched_anchor")
        candidates = [anchor, item] if isinstance(anchor, dict) else [item]
        center = None
        for candidate in candidates:
            _, validity = vectors.transform([candidate])
            if validity.mean() >= .70 and validity[0, :10].sum() >= 7:
                center = candidate
                break
        if center is None:
            generic.append(item)
            continue
        centers.append(center)
        directional.append({"track_id": item.get("track_id"), "reason": reason, "rejected_tempo": tempo,
            "scope_anchor_id": center.get("track_id"), "scope_source": "matched_anchor" if center is anchor else "rejected_song"})
    return generic, directional, centers


class MusicRecommender(BaselineRecommender):
    """Nearest liked anchors with complete-link groups and bounded diversification."""

    def __init__(self, dataset_path=None, vector_path=None, config=DEFAULT_RANKING, genre_path=None, artist_genre_path=None):
        self.config = config
        super().__init__(dataset_path)
        self.genre_warning = None
        try:
            evidence = load_evidence(genre_path or DATA_DIR / "sources/song_genres/index.json") if genre_path or dataset_path is None else {}
        except (OSError, ValueError, TypeError, AttributeError) as error:
            evidence = {}
            self.genre_warning = str(error)
        for song in self._songs:
            item = evidence.get(song["track_id"])
            # Index evidence must still describe the same title and full credits.
            if item and song_key(song) == song_key(item):
                song["genre_evidence"] = item
        try:
            if artist_genre_path or dataset_path is None:
                attach_artist_evidence(self._songs, artist_genre_path or DATA_DIR / "sources/artist_genres/index.json")
        except (OSError, ValueError, TypeError, AttributeError, KeyError) as error:
            self.genre_warning = str(error)
        self._genre_sets = [genre_labels(song) for song in self._songs]
        self.genres_active = any(self._genre_sets)
        self._credits = [credited_artists(song) for song in self._songs]
        self._identity_keys = [(normalized(song["track_name"]), tuple(sorted(credits)))
                               for song, credits in zip(self._songs, self._credits)]
        self._identity_code_by_key = {key: code for code, key in enumerate(dict.fromkeys(self._identity_keys))}
        self._identity_codes = np.asarray([self._identity_code_by_key[key] for key in self._identity_keys], dtype=np.int32)
        self.vectors = None
        self.vector_warning = None
        self._artist_rows = None
        self._solo_artist_ids = defaultdict(set)
        # A tiny legacy fixture cannot accidentally trigger production data loading.
        if not {"acousticness", "instrumentalness", "speechiness", "loudness",
                "liveness", "duration_ms", "key", "mode", "time_signature"}.issubset(self.table.columns):
            return
        try:
            if dataset_path is not None and vector_path is None:
                self.vectors = SongVectors.build(self.table)
            else:
                self.vectors = SongVectors.load(
                    Path(vector_path) if vector_path else DATA_DIR / "vectors",
                    table=self.table)
        except (OSError, ValueError, KeyError, TypeError) as error:
            # Offline rebuilding is deliberate: never start a build in the GUI.
            self.vector_warning = str(error)
        if self.vectors is not None:
            self._artist_matches([])  # Initialize once on the existing loading worker.

    @property
    def vectors_active(self):
        return self.vectors is not None

    def _artist_matches(self, anchors):
        """Exact artist-ID matches; names only when IDs are unavailable.

        Build postings once, then reuse small row lists rather than scanning
        artist strings for every candidate/anchor comparison.
        """
        if self._artist_rows is None:
            rows = defaultdict(list)
            for index, song in enumerate(self._songs):
                ids = artist_ids(song)
                if len(self._credits[index]) == 1 and len(ids) == 1:
                    self._solo_artist_ids[self._credits[index][0]].update(ids)
                for artist_id in set(ids):
                    rows[("id", artist_id)].append(index)
                for name in self._credits[index]:
                    rows[("name", name)].append(index)
                    if not ids:
                        rows[("missing_id_name", name)].append(index)
            self._artist_rows = {key: np.asarray(value, dtype=np.int32) for key, value in rows.items()}
        matches = []
        for anchor in anchors:
            ids = artist_ids(anchor)
            keys = [("id", value) for value in ids]
            keys += [("missing_id_name" if ids else "name", name) for name in credited_artists(anchor)]
            parts = [self._artist_rows[key] for key in keys if key in self._artist_rows]
            matches.append(np.unique(np.concatenate(parts)) if parts else np.empty(0, dtype=np.int32))
        return matches

    @staticmethod
    def _distance(matrix, masks, seeds, seed_masks):
        """Shared-dimension distance; missing values never masquerade as evidence."""
        size = matrix.shape[1]
        if masks.all() and seed_masks.all():
            return (cdist(matrix, seeds) / np.sqrt(size)).astype(np.float32)
        result = np.empty((len(matrix), len(seeds)), dtype=np.float32)
        # Bounded at 2048 × dimensions; never materialize catalog × likes × dims.
        for j, (seed, seed_mask) in enumerate(zip(seeds, seed_masks)):
            for start in range(0, len(matrix), 2048):
                stop = start + 2048
                shared = masks[start:stop] & seed_mask
                count = shared.sum(axis=1)
                difference = matrix[start:stop] - seed
                squared = np.sum(difference * difference * shared, axis=1)
                # Count raw measurements, not duplicated one-hot dimensions.
                raw_shared = shared[:, :10].sum(axis=1) + shared[:, 10] + shared[:, 12] + shared[:, 14]
                coverage = raw_shared / 13
                distance = np.sqrt(squared / np.maximum(count, 1)) + .15 * (1 - coverage)
                distance[(coverage < .70) | (shared[:, :10].sum(axis=1) < 7)] = np.inf
                result[start:stop, j] = distance
        return result

    @staticmethod
    def _groups(distances, radius=GROUP_RADIUS):
        """Deterministic complete link: every pair must meet the same radius."""
        groups = []
        labels = []
        for index in range(len(distances)):
            destination = next((i for i, group in enumerate(groups)
                                if all(distances[index, other] <= radius for other in group)), None)
            if destination is None:
                destination = len(groups)
                groups.append([])
            groups[destination].append(index)
            labels.append(destination)
        return np.asarray(labels), groups

    def recommend(self, favorite_ids, limit=5, favorite_songs=None, feedback=None, exclude_ids=None, *, candidate_ids=None, diversify=True, extra_candidate_ids=None, known_artist_names=None, known_artist_ids=None, steering="same", pairwise_feedback=None, candidate_filter=None):
        validate_steering(steering)
        favorite_ids = list(dict.fromkeys(favorite_ids))
        if self.vectors is None:
            if candidate_ids is not None or extra_candidate_ids:
                raise ValueError("Explicit candidate scoring requires rich vectors.")
            results = super().recommend(favorite_ids, max(limit, 100) if candidate_filter else limit, favorite_songs, feedback, exclude_ids)
            if candidate_filter:
                results = [song for song in results if candidate_filter(song)][:limit]
            if steering != "same":
                for song in results:
                    song["steering_context"] = {"version": POLICY_VERSION, "option": steering,
                        "applied": False, "score_adjustment": 0., "target": None,
                        "method": "Request steering requires the rich audio-feature index."}
            return discovery_unavailable(results, limit, self.config) if known_artist_names is not None else results
        if not favorite_ids:
            raise ValueError("Add at least one favorite before asking for recommendations.")
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
            raise ValueError("Recommendation limit must be a positive integer.")
        extra_candidate_ids = self._validated_candidate_ids(extra_candidate_ids) if extra_candidate_ids is not None else []
        snapshots = {song["track_id"]: song for song in (favorite_songs or [])}
        favorites = []
        for track_id in favorite_ids:
            song = self.get_song(track_id) if track_id in self._indices else snapshots.get(track_id)
            if song is None:
                raise ValueError("A favorite is absent from the catalog and has no saved audio features.")
            favorites.append(song)
        excluded = set(exclude_ids or ()) | set(favorite_ids)
        excluded_keys = {song_key(song) for song in favorites}
        excluded_keys.update(song_key(self._songs[self._indices[track_id]])
                             for track_id in excluded if track_id in self._indices)
        # Latest rating wins before feature validation. Familiarity is exclusion,
        # not a negative training example.
        ratings, seen = [], set()
        for item in feedback or ():
            track_id = item.get("track_id")
            if not track_id or track_id in seen or not isinstance(item.get("liked"), bool):
                continue
            seen.add(track_id)
            ratings.append(item)
            excluded.add(track_id)
            excluded_keys.add(song_key(item))
            if len(ratings) >= 500:
                break
        positives = [item for item in ratings if item["liked"] and item["track_id"] not in favorite_ids]
        known_names = {normalized(name) for name in (known_artist_names or ())}
        known_names.update(name for song in favorites + positives for name in credited_artists(song))
        known_artist_rows = np.zeros(len(self._songs), dtype=bool)
        for artist_id in known_artist_ids or ():
            known_artist_rows[self._artist_rows.get(("id", artist_id), np.empty(0, dtype=np.int32))] = True
        for rows in self._artist_matches(favorites + positives):
            known_artist_rows[rows] = True
        for name in known_names:
            known_artist_rows[self._artist_rows.get(("name", name), np.empty(0, dtype=np.int32))] = True
            for artist_id in self._solo_artist_ids.get(name, ()):
                known_artist_rows[self._artist_rows.get(("id", artist_id), np.empty(0, dtype=np.int32))] = True
        # More seeds do not multiply a neighborhood's score. Bound representatives
        # and preserve far-apart favorites rather than taking a temporal prefix.
        all_seeds = favorites + positives[:32]
        seed_vectors, seed_validity = self.vectors.transform(all_seeds)
        seed_masks = self.vectors.expand_validity(seed_validity)
        seed_eligible = (seed_validity.mean(axis=1) >= .70) & (seed_validity[:, :10].sum(axis=1) >= 7)
        usable = np.flatnonzero(seed_eligible)
        if not seed_eligible[:len(favorites)].any():
            raise ValueError("Saved favorites lack sufficient rich features; reselect songs from the current catalog.")
        # Farthest-first representative selection preserves separated taste modes.
        if len(usable) > 96:
            chosen = [int(usable[0])]
            remaining = list(map(int, usable[1:]))
            while remaining and len(chosen) < 96:
                distances = self._distance(seed_vectors[remaining], seed_masks[remaining],
                                           seed_vectors[chosen[-1:]], seed_masks[chosen[-1:]])[:, 0]
                if len(chosen) == 1:
                    nearest = distances
                else:
                    nearest = np.minimum(nearest, distances)
                position = int(np.argmax(nearest))
                chosen.append(remaining.pop(position))
                nearest = np.delete(nearest, position)
            usable = np.asarray(chosen)
        anchors = [all_seeds[i] for i in usable]
        # Old feedback snapshots may predate acquisition. Resolve current evidence
        # only through the same catalog ID and exact title/full-credit identity.
        anchors = [dict(anchor, **{key: self._songs[self._indices[anchor["track_id"]]][key]
                                  for key in ("genre_evidence", "artist_genre_evidence")
                                  if key in self._songs[self._indices[anchor["track_id"]]]})
                   if anchor.get("track_id") in self._indices
                   and song_key(anchor) == song_key(self._songs[self._indices[anchor["track_id"]]]) else anchor
                   for anchor in anchors]
        anchor_genres = [genre_labels(anchor) for anchor in anchors]
        artist_rows = self._artist_matches(anchors)
        vectors, masks = seed_vectors[usable], seed_masks[usable]
        seed_distances = self._distance(vectors, masks, vectors, masks)
        if self.genres_active:
            for i, left in enumerate(anchors):
                for j, right in enumerate(anchors):
                    if i != j and not genre_compatible(left, right):
                        seed_distances[i, j] = np.inf
        labels, groups = self._groups(seed_distances, self.config.group_radius)
        group_genre_sets = [[anchor_genres[k] for k in groups[int(labels[j])]] for j in range(len(anchors))]
        # Explicit favorites retain priority over added Yes examples.
        penalties = np.asarray([0.0 if i < len(favorites) else self.config.yes_anchor_penalty for i in usable], dtype=np.float32)
        closest = np.zeros(len(self._songs), dtype=np.int32)
        scores = np.full(len(self._songs), np.inf, dtype=np.float32)
        raw_distance = np.empty(len(self._songs), dtype=np.float32)
        adjustment = np.empty(len(self._songs), dtype=np.float32)
        artist_adjustment = np.empty(len(self._songs), dtype=np.float32)
        negatives = [item for item in ratings if not item["liked"]
                     and item.get("feedback_reason", item.get("reason")) != "Already know it"][:32]
        negatives, directional, tempo_centers = _directional_negatives(negatives, self.vectors)
        directional_adjustment = np.zeros(len(self._songs), dtype=np.float32)
        if directional:
            tempo_vectors, tempo_validity = self.vectors.transform(tempo_centers)
            tempo_masks = self.vectors.expand_validity(tempo_validity)
            rejected_tempos = np.asarray([item["rejected_tempo"] for item in directional])
            tempo_signs = np.asarray([1 if item["reason"] == "Too slow" else -1 for item in directional])
            candidate_tempos = self.table["tempo"].to_numpy(dtype=float)
        negative_vectors, negative_validity = self.vectors.transform(negatives) if negatives else (None, None)
        if negatives:
            negative_masks = self.vectors.expand_validity(negative_validity)
            valid_negative = (negative_validity[:, :10].sum(axis=1) >= 7) & (negative_validity.mean(axis=1) >= .70)
            negative_vectors, negative_masks = negative_vectors[valid_negative], negative_masks[valid_negative]
        pairs = prepare_pairs(pairwise_feedback, self.vectors)
        pair_adjustments = np.zeros(len(self._songs), dtype=np.float32)
        pair_counts = np.zeros(len(self._songs), dtype=np.int32)
        steer_adjustments = np.zeros(len(self._songs), dtype=np.float32)
        targets = [steering_target(anchor, steering) for anchor in anchors]
        steering_values = None
        if any(targets):
            feature = next(target["feature"] for target in targets if target)
            steering_values = self.table[feature].to_numpy(dtype=float)
        artist_bonus = self.config.artist_bonus * (.5 if steering == "less_artist" else 1.)
        catalog_masks = self.vectors.dimension_validity
        if candidate_ids is not None:
            candidate_ids = self._validated_candidate_ids(candidate_ids)
            candidate_rows = np.asarray(sorted(self._indices[item] for item in candidate_ids), dtype=np.int32)
        else:
            candidate_rows = np.arange(len(self._songs), dtype=np.int32)
        for start in range(0, len(candidate_rows), 2048):
            indices = candidate_rows[start:start + 2048]
            indexer = slice(start, start + len(indices)) if candidate_ids is None else indices
            distances = self._distance(self.vectors.matrix[indexer], catalog_masks[indexer], vectors, masks)
            artist_match = np.zeros(distances.shape, dtype=bool)
            for j, rows in enumerate(artist_rows):
                if candidate_ids is None:
                    local = rows[np.searchsorted(rows, start):np.searchsorted(rows, start + len(indices))] - start
                    artist_match[local, j] = True
                else:
                    artist_match[:, j] = np.isin(indices, rows, assume_unique=True)
            weighted = distances + penalties - artist_bonus * artist_match
            if self.genres_active:
                for j, genres in enumerate(anchor_genres):
                    # Known genres require overlap; unknown anchors only have an
                    # explicitly unverified audio fallback among unknown tracks.
                    allowed = np.fromiter((all(bool(self._genre_sets[i] & required) for required in group_genre_sets[j]) if genres
                                           else not self._genre_sets[i] for i in indices), bool, len(indices))
                    weighted[~allowed, j] = np.inf
            steering_by_anchor = None
            if steering_values is not None:
                steering_by_anchor = np.column_stack([steering_adjustment(steering_values[indices], target) for target in targets])
                weighted += steering_by_anchor
            local = weighted.argmin(axis=1)
            closest[indices] = local
            scores[indices] = weighted[np.arange(len(indices)), local]
            raw_distance[indices] = distances[np.arange(len(indices)), local]
            adjustment[indices] = penalties[local]
            artist_adjustment[indices] = -artist_bonus * artist_match[np.arange(len(indices)), local]
            if steering_by_anchor is not None:
                steer_adjustments[indices] = steering_by_anchor[np.arange(len(indices)), local]
            if pairs:
                pair_adjustments[indices], pair_counts[indices] = pairwise_adjustment(
                    self.vectors.matrix[indexer], catalog_masks[indexer], pairs, self._distance, self.config.group_radius)
                scores[indices] += pair_adjustments[indices]
            dislike_penalty = np.zeros(len(indices), dtype=np.float32)
            if negatives and len(negative_vectors):
                negative_distance = self._distance(self.vectors.matrix[indexer], catalog_masks[indexer],
                                                   negative_vectors, negative_masks).min(axis=1)
                dislike_penalty = self.config.dislike_max * np.exp(-negative_distance ** 2 / self.config.dislike_width)
            if directional:
                scope_distances = self._distance(self.vectors.matrix[indexer], catalog_masks[indexer], tempo_vectors, tempo_masks)
                offset = tempo_signs * (rejected_tempos - candidate_tempos[indices, None]) / np.maximum(10., rejected_tempos * .1)
                side = 1. / (1. + np.exp(-np.clip(offset, -30, 30)))
                scoped = self.config.dislike_max * side * np.exp(-scope_distances ** 2 / self.config.dislike_width)
                scoped[(scope_distances > self.config.group_radius) | ~np.isfinite(offset)] = 0
                scoped[candidate_tempos[indices] <= 0, :] = 0
                tempo_penalty = scoped.max(axis=1)
                combined = np.maximum(dislike_penalty, tempo_penalty)
                directional_adjustment[indices] = combined - dislike_penalty
                dislike_penalty = combined
            scores[indices] += dislike_penalty
            adjustment[indices] += dislike_penalty
        excluded_codes = [self._identity_code_by_key[key] for key in excluded_keys if key in self._identity_code_by_key]
        invalid = self.table["track_id"].isin(excluded).to_numpy() | np.isin(self._identity_codes, excluded_codes)
        invalid |= self.vectors.validity[:, :10].sum(axis=1) < 7
        scores[invalid] = np.inf
        finite_rows = candidate_rows[np.isfinite(scores[candidate_rows])]
        ordered = finite_rows[np.argsort(scores[finite_rows], kind="stable")]
        # Deduplicate globally before grouping so an alias in another neighborhood
        # cannot consume an artist slot or alter its group's representative pool.
        if len(ordered):
            _, first = np.unique(self._identity_codes[ordered], return_index=True)
            ordered = ordered[np.sort(first)]
        if candidate_ids is not None:
            # A small explicit subset never constructs or scans catalog queues.
            selected = ordered[:limit].tolist()
        else:
            queues, primary_queues = {}, {}
            queue_cap = max(50, limit * 4)
            ordered_groups = labels[closest[ordered]]
            for group in sorted(set(map(int, ordered_groups))):
                queue, backup, counts = [], [], {}
                for index in ordered[ordered_groups == group]:
                    artists = self._credits[index]
                    if len(queue) < queue_cap and all(counts.get(artist, 0) < self.config.artist_cap for artist in artists):
                        queue.append(int(index))
                        for artist in artists:
                            counts[artist] = counts.get(artist, 0) + 1
                    elif len(backup) < queue_cap:
                        backup.append(int(index))
                    if len(queue) >= queue_cap and len(backup) >= queue_cap:
                        break
                primary_queues[group] = queue
                queues[group] = sorted(queue + backup, key=lambda i: (scores[i], i))
            selected = sorted({index for queue in queues.values() for index in queue}, key=lambda i: (scores[i], i))
            if not diversify:
                # Retrieval retains raw top scores plus per-group artist-limited
                # representatives. No diversity score is applied at this stage.
                pool = dict.fromkeys(selected[:limit])
                for offset in range(queue_cap):
                    for group in sorted(primary_queues):
                        queue = primary_queues[group]
                        if offset < len(queue) and len(pool) < self.config.max_explicit_candidates:
                            pool.setdefault(queue[offset], None)
                selected = sorted(pool, key=lambda i: (scores[i], i))
        # Full-catalog distances already include graph rows. Retain their exact
        # scores in this pass instead of fitting anchors and scanning masks twice.
        if extra_candidate_ids:
            extras = [self._indices[item] for item in extra_candidate_ids if np.isfinite(scores[self._indices[item]])]
            selected = sorted(set(selected) | set(extras), key=lambda i: (scores[i], i))
        if candidate_ids is None:
            # A positive artist bonus can bury every unfamiliar artist below the
            # ordinary retrieval queues. Retain a separate close-audio pool.
            unfamiliar = ordered[(~known_artist_rows[ordered]) &
                                 (raw_distance[ordered] <= self.config.discovery_max_distance)]
            discovery_rows, discovery_counts = [], {}
            for index in unfamiliar:
                credits = self._credits[index]
                if credits and all(discovery_counts.get(name, 0) < self.config.artist_cap for name in credits):
                    discovery_rows.append(int(index))
                    for name in credits:
                        discovery_counts[name] = discovery_counts.get(name, 0) + 1
                if len(discovery_rows) >= 50:
                    break
            selected = sorted(set(selected) | set(discovery_rows), key=lambda i: (scores[i], i))
        if candidate_filter is not None:
            # A rejected shortlist is not catalog exhaustion. Keep exact scores
            # and continue through eligible ranked rows until the batch can fill.
            checked = {}
            def allowed(index):
                index = int(index)
                if index not in checked:
                    checked[index] = bool(candidate_filter(self._songs[index]))
                return checked[index]
            selected = [index for index in selected if allowed(index)]
            if len(selected) < limit:
                retained = set(selected)
                target = max(limit, 10)
                for index in ordered:
                    index = int(index)
                    if index not in retained and allowed(index):
                        selected.append(index)
                        retained.add(index)
                    if len(selected) >= target:
                        break
                selected.sort(key=lambda i: (scores[i], i))
        selection_contexts = {}
        if diversify:
            minimal = [dict(self._songs[i], ranking_score=float(scores[i]),
                       distance=float(raw_distance[i]), known_artist_overlap=bool(known_artist_rows[i]),
                       matched_anchor=anchors[int(closest[i])],
                       neighborhood_context={"group": int(labels[closest[i]])}) for i in selected]
            picked = select_candidates(minimal, limit, self.config, known_names)
            selection_contexts = {song["track_id"]: song["selection_context"] for song in picked}
            selected = [self._indices[song["track_id"]] for song in picked]
        elif candidate_ids is not None:
            selected = selected[:limit]
        results = []
        ranking_provenance = self.config.provenance()
        snapshot_fields = set(RAW_FEATURES) | {"track_id", "track_name", "artists", "id_artists", "artist_mbids", "recording_mbid", "source", "license", "version_note", "feature_version", "source_fingerprint", "genre_evidence", "artist_genre_evidence"}
        anchor_snapshots = [{key: value for key, value in anchor.items() if key in snapshot_fields} for anchor in anchors]
        neighborhood_anchors = [{"song": snapshot, "group": int(labels[i]),
                                 "kind": "liked" if usable[i] < len(favorites) else "positive"}
                                for i, snapshot in enumerate(anchor_snapshots)]
        for index in selected:
            anchor_index = int(closest[index])
            group = int(labels[anchor_index])
            anchor = anchors[anchor_index]
            members = groups[group]
            spread = float(np.max(seed_distances[np.ix_(members, members)])) if len(members) > 1 else 0.0
            song = dict(self._songs[index])
            if song["track_id"] in selection_contexts:
                song["selection_context"] = selection_contexts[song["track_id"]]
            song.update(distance=float(raw_distance[index]), ranking_score=float(scores[index]),
                        known_artist_overlap=bool(known_artist_rows[index]),
                        matched_anchor=dict(anchor_snapshots[anchor_index]), neighborhood_anchors=neighborhood_anchors,
                        feedback_adjustment=float(adjustment[index]), model_version=MODEL_VERSION,
                        artist_adjustment=float(artist_adjustment[index]),
                        feature_version=self.vectors.metadata.get("feature_version", self.vectors.metadata.get("version")),
                        source_fingerprint=self.vectors.metadata.get("source_fingerprint"),
                        ranking_config=dict(ranking_provenance, values=dict(ranking_provenance["values"])),
                        neighborhood_context={"group": group, "anchor_id": anchor["track_id"],
                            "member_ids": [anchors[i]["track_id"] for i in members],
                            "spread": spread, "groups": len(groups), "seed_count": len(anchors),
                            "available_seed_count": len(all_seeds), "representative_limit": 96,
                            "omitted_incomplete_seeds": int((~seed_eligible).sum())})
            if steering != "same":
                target = targets[anchor_index]
                song["steering_context"] = {"version": POLICY_VERSION, "option": steering,
                    "applied": bool(target) or steering == "less_artist",
                    "score_adjustment": float(steer_adjustments[index]), "original_distance": float(raw_distance[index]),
                    "target": {key: value for key, value in target.items() if key != "scale"} if target else None,
                    "candidate_value": float(steering_values[index]) if steering_values is not None and np.isfinite(steering_values[index]) else None,
                    "artist_bonus": artist_bonus,
                    "method": "bounded feature-target closeness; original measured vectors and groups retained"}
            if directional:
                song["directional_feedback_context"] = {"version": "local-tempo-no-v1",
                    "records": directional, "score_adjustment": float(directional_adjustment[index]),
                    "scope_radius": self.config.group_radius, "maximum_total_no_penalty": self.config.dislike_max,
                    "method": "local tempo-side penalty; maximum with generic No, not a trained model"}
            if pairs:
                song["pairwise_context"] = {"version": POLICY_VERSION, "record_count": len(pairs),
                    "active_count": int(pair_counts[index]), "score_adjustment": float(pair_adjustments[index]),
                    "maximum_adjustment": .02, "scope_radius": self.config.group_radius,
                    "evidence": [snapshot for _, _, snapshot in pairs],
                    "method": "mean bounded local preference kernel; not a trained neural network"}
            song["reason_preview"] = f"Close to {anchor['track_name']} by {anchor['artists']}."
            shared_genres = sorted(genre_labels(song) & anchor_genres[anchor_index])
            levels = [effective_evidence(item).get("level", "unknown") for item in (song, anchor)]
            recording_match = levels == ["recording", "recording"]
            song["genre_context"] = {"version": GENRE_VERSION, "status": ("shared_recording_genres" if recording_match else "shared_artist_genre_fallback") if shared_genres else "unknown_genre_audio_fallback",
                                     "candidate_level": levels[0], "anchor_level": levels[1],
                                     "shared_genres": shared_genres, "policy": "recording labels first, artist fallback second; known genres require overlap; unknown anchors remain separate"}
            if artist_adjustment[index] < 0:
                song["reason_preview"] = f"Shares an artist with {anchor['track_name']} by {anchor['artists']}; also compared audio features."
            song["reason"] = (song["reason_preview"] + " Compared scaled audio measurements with individual liked-song anchors; "
                              "this song matches at least one preference neighborhood rather than an average of all favorites. "
                              f"Shared-feature distance {raw_distance[index]:.3f}; group has {len(members)} anchors "
                              f"and spread {spread:.3f}. Artist overlap adjusted the score by {artist_adjustment[index]:+.3f}; "
                              "artist IDs are used where available, otherwise exact normalized credits. "
                              "Genre or instrumentation is not inferred from these measurements.")
            if shared_genres:
                prefix = "Shared song genres: " if recording_match else "Shared genres (artist fallback): "
                song["reason_preview"] = prefix + ", ".join(shared_genres) + ". " + song["reason_preview"]
                song["reason"] += " " + prefix + ", ".join(shared_genres) + "."
                if not recording_match:
                    song["reason"] += " Artist genres describe the credited artists and may differ from this particular song."
            else:
                song["reason"] += " Song genre is unknown; this is an unverified audio fallback, not a confirmed genre match."
            results.append(song)
        for song in results:
            song["score_components"] = {"audio_distance": song["distance"],
                "artist_adjustment": song["artist_adjustment"], "feedback_adjustment": song["feedback_adjustment"] - song.get("directional_feedback_context", {}).get("score_adjustment", 0.),
                "listening_adjustment": 0.0}
            if directional:
                song["score_components"]["directional_tempo_adjustment"] = song["directional_feedback_context"]["score_adjustment"]
            if steering != "same":
                song["score_components"]["steering_adjustment"] = song["steering_context"]["score_adjustment"]
            if pairs:
                song["score_components"]["pairwise_adjustment"] = song["pairwise_context"]["score_adjustment"]
        return results

    @staticmethod
    def select_candidates(songs, limit, config=DEFAULT_RANKING, known_artist_names=None):
        return select_candidates(songs, limit, config, known_artist_names)

    def has_song(self, track_id):
        return track_id in self._indices

    def has_audio_features(self, song):
        try:
            self._snapshot_features(song)
            return True
        except ValueError:
            return False

    def songs_with_titles(self, titles):
        """Vectorized prefilter for conservative cross-source identity joins."""
        for index in self.table.index[self._titles.isin(titles)]:
            yield dict(self._songs[index])

    def _validated_candidate_ids(self, candidate_ids):
        if isinstance(candidate_ids, (str, bytes)):
            raise ValueError("Candidate IDs must be a sequence, not a string.")
        result = []
        seen = set()
        for position, item in enumerate(candidate_ids):
            if position >= self.config.max_explicit_candidates:
                raise ValueError("Explicit candidate list exceeds ranking bound.")
            if not isinstance(item, str) or not item.strip() or not self.has_song(item):
                raise ValueError("Explicit candidate ID is missing from the audio catalog.")
            if item not in seen:
                seen.add(item)
                result.append(item)
        return result

    def score_candidates(self, favorite_ids, candidate_ids, favorite_songs=None, feedback=None, exclude_ids=None):
        """Score a bounded verified catalog subset with the same rich anchor metric.

        No diversity is applied here; the caller selects once after candidate union.
        Unknown IDs and metadata-only records are rejected, never imputed.
        """
        candidate_ids = self._validated_candidate_ids(candidate_ids)
        if not candidate_ids:
            return []
        return self.recommend(favorite_ids, len(candidate_ids), favorite_songs, feedback, exclude_ids,
                              candidate_ids=candidate_ids, diversify=False)
