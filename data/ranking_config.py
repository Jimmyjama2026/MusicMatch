"""Frozen ranking policy. Distances are smaller-is-better; bonuses subtract."""
from dataclasses import asdict, dataclass
import hashlib
import json


@dataclass(frozen=True)
class RankingConfig:
    artist_bonus: float = .18
    group_radius: float = .10
    yes_anchor_penalty: float = .08
    dislike_max: float = .04
    dislike_width: float = .01
    group_diversity_penalty: float = .06
    artist_cap: int = 2
    rich_listening_bonus: float = .02
    rich_artist_vote_bound: float = .005
    legacy_listening_bonus: float = .12
    legacy_artist_vote_bound: float = .04
    max_explicit_candidates: int = 1000
    discovery_minimum: int = 2
    discovery_minimum_batch: int = 5
    discovery_max_distance: float = .10
    anchor_family_diversity: bool = True

    def provenance(self):
        values = asdict(self)
        return {"version": "ranking-policy-v3-anchor-families-directional-no", "values": values,
                "sha256": hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()}


DEFAULT_RANKING = RankingConfig()
