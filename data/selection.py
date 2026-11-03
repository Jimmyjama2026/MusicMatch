"""One deterministic diversity policy, shared by all rich ranking paths."""
import math
if __package__:
    from .identity import credited_artists, normalized, artist_ids
    from .ranking_config import DEFAULT_RANKING
else:
    from identity import credited_artists, normalized, artist_ids
    from ranking_config import DEFAULT_RANKING


def select_candidates(songs, limit, config=DEFAULT_RANKING, known_artist_names=None):
    remaining, seen = [], set()
    credits_by_object = {}
    tokens_by_object = {}
    families_by_object = {}
    for song in sorted(songs, key=lambda item: float(item["ranking_score"])):
        credits = credited_artists(song)
        key = normalized(song.get("track_name", "")), tuple(sorted(credits))
        if key not in seen:
            seen.add(key)
            remaining.append(song)
            credits_by_object[id(song)] = credits
            tokens_by_object[id(song)] = set(artist_ids(song)) | {"name:" + name for name in credits}
            anchor = song.get("matched_anchor") or {}
            families_by_object[id(song)] = set(artist_ids(anchor)) | {"name:" + name for name in credited_artists(anchor)}
    known = {normalized(name) for name in (known_artist_names or ())}
    requested = min(config.discovery_minimum, limit) if known_artist_names is not None and limit >= config.discovery_minimum_batch else 0
    def discoverable(song):
        distance = song.get("distance")
        return (bool(credits_by_object[id(song)]) and not song.get("known_artist_overlap", False)
                and not known.intersection(credits_by_object[id(song)])
                and isinstance(distance, (int, float)) and math.isfinite(distance)
                and distance <= config.discovery_max_distance)
    discoveries = [song for song in remaining if discoverable(song)]
    def close_family(song):
        distance = song.get("distance")
        return (bool(families_by_object[id(song)]) and isinstance(distance, (int, float))
                and math.isfinite(distance) and distance <= config.discovery_max_distance)
    multiple_families = len({tuple(sorted(families_by_object[id(song)])) for song in remaining if close_family(song)}) > 1
    reserved = []
    if requested:
        # At most two slots: find the best-ranked pair whose complete credits
        # are disjoint. A popular collaboration must not hide two eligible solos.
        if requested >= 2:
            for different_families in ((True, False) if config.anchor_family_diversity else (False,)):
                for first in discoveries:
                    credits = tokens_by_object[id(first)]
                    family = families_by_object[id(first)]
                    second = next((song for song in discoveries if song is not first
                        and credits.isdisjoint(tokens_by_object[id(song)])
                        and (not different_families or (family and families_by_object[id(song)]
                             and family.isdisjoint(families_by_object[id(song)])))), None)
                    if second is not None:
                        reserved = [first, second]
                        break
                if reserved:
                    break
        if not reserved and discoveries:
            reserved = discoveries[:1]
    reserved_ids = {id(song) for song in reserved}
    selected, groups, artists = [], {}, {}
    used_families = set()
    while remaining and len(selected) < limit:
        pending = [song for song in remaining if id(song) in reserved_ids]
        pending_artists = {artist for song in pending for artist in credits_by_object[id(song)]}
        slots_left = limit - len(selected)
        forced = bool(pending) and slots_left <= len(pending)
        source_pool = pending if forced else remaining
        eligible = [song for song in source_pool if all(
            artists.get(artist, 0) + (1 if artist in pending_artists and id(song) not in reserved_ids else 0) < config.artist_cap
            for artist in credits_by_object[id(song)])]
        cap_relaxed = not eligible
        if not eligible:
            eligible = source_pool
        # Favorite-song counts and complete-link group counts are not votes.
        # Reserve coverage by the actual nearest anchor's artist family, only
        # while another sufficiently close family has an eligible candidate.
        pending_families = set().union(*(families_by_object[id(item)] for item in pending)) if pending else set()
        family_eligible = [item for item in eligible if close_family(item)
            and used_families.isdisjoint(families_by_object[id(item)])
            and (id(item) in reserved_ids or pending_families.isdisjoint(families_by_object[id(item)]))]
        if not family_eligible:
            family_eligible = [item for item in eligible if close_family(item)
                and used_families.isdisjoint(families_by_object[id(item)])]
        family_relaxed = bool(used_families) and not family_eligible
        if config.anchor_family_diversity and multiple_families and family_eligible and (used_families or pending):
            eligible = family_eligible
        def priority(song):
            group = song.get("neighborhood_context", {}).get("group", -1)
            return float(song["ranking_score"]) + config.group_diversity_penalty * groups.get(group, 0)
        song = min(eligible, key=priority)
        group = song.get("neighborhood_context", {}).get("group", -1)
        selected.append(dict(song, selection_context={
            "group_use_before": groups.get(group, 0),
            "artist_counts_before": {artist: artists.get(artist, 0) for artist in credits_by_object[id(song)]},
            "artist_cap_relaxed": cap_relaxed,
            "anchor_artist_family": sorted(families_by_object[id(song)]),
            "anchor_family_overlap_before": bool(used_families.intersection(families_by_object[id(song)])),
            "anchor_family_cap_relaxed": family_relaxed,
            "anchor_family_diversity_enabled": config.anchor_family_diversity,
            "anchor_family_max_distance": config.discovery_max_distance,
            "anchor_family_policy": "one close candidate per anchor artist family while eligible alternatives remain",
            "discovery": id(song) in reserved_ids,
            "diversity_adjustment": config.group_diversity_penalty * groups.get(group, 0),
            "selection_score": priority(song)}))
        remaining.remove(song)
        groups[group] = groups.get(group, 0) + 1
        used_families.update(families_by_object[id(song)])
        for artist in credits_by_object[id(song)]:
            artists[artist] = artists.get(artist, 0) + 1
    fulfilled = sum(song["selection_context"]["discovery"] for song in selected)
    for song in selected:
        song["selection_context"].update(discovery_requested=requested, discovery_fulfilled=fulfilled,
            discovery_shortfall=max(0, requested - fulfilled), discovery_max_distance=config.discovery_max_distance,
            discovery_shortage_reason="Not enough suitably close, mutually distinct unfamiliar credited artists in the eligible pool." if fulfilled < requested else None)
    return selected


def discovery_unavailable(songs, limit, config=DEFAULT_RANKING):
    """Keep unsupported ranking intact while reporting unavailable quota evidence."""
    requested = min(config.discovery_minimum, limit) if limit >= config.discovery_minimum_batch else 0
    return [dict(song, selection_context=dict(song.get("selection_context", {}), discovery=False,
        discovery_requested=requested, discovery_fulfilled=0, discovery_shortfall=requested,
        discovery_max_distance=config.discovery_max_distance,
        discovery_shortage_reason="The unfamiliar-artist quota needs reliable rich-audio distances; this route does not supply them." if requested else None)) for song in songs]
