import unittest
from data.identity import artist_ids, credited_artists, song_identity
from data.learning_records import identity_key
from data.ranking_config import DEFAULT_RANKING, RankingConfig
from data.selection import select_candidates


class IdentityTests(unittest.TestCase):
    def test_full_credit_order_spacing_unicode_and_aliases(self):
        first = {"track_name": " What’s  Next ", "artists": "Ａ;B ; C; A"}
        second = {"track_name": "what's next", "artists": "c ; b;a"}
        self.assertEqual(song_identity(first), song_identity(second))
        self.assertEqual(identity_key(first), song_identity(second))
        self.assertEqual(credited_artists(first), ("a", "b", "c"))

    def test_ids_are_namespaced_validated_and_preferred(self):
        song = {"id_artists": str(["A" * 22]), "artist_mbids": ["00000000-0000-4000-8000-000000000001"]}
        self.assertEqual(artist_ids(song), ("spotify:" + "A" * 22,))
        self.assertEqual(artist_ids({"id_artists": "malformed"}), ())

    def test_selection_deduplicates_before_artist_cap(self):
        rows = [dict(track_id=str(i), track_name=title, artists=artist, ranking_score=score)
                for i, (title, artist, score) in enumerate([
                    ("Same", "A; B", 0), (" same ", "B;A", .001),
                    ("Other", "A", .002), ("Third", "A", .003), ("Novel", "C", .004)])]
        result = select_candidates(rows, 3)
        self.assertEqual([s["track_name"] for s in result], ["Same", "Other", "Novel"])

    def test_config_is_frozen_and_provenance_distinguishes_ablation(self):
        with self.assertRaises(AttributeError):
            DEFAULT_RANKING.artist_bonus = .20
        self.assertNotEqual(DEFAULT_RANKING.provenance()["sha256"], RankingConfig(artist_bonus=.20).provenance()["sha256"])
