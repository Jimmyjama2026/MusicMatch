import unittest

from data.selection import select_candidates, discovery_unavailable


def candidate(ident, artist, score, distance=.03, **extra):
    return dict(track_id=ident, track_name=ident, artists=artist, ranking_score=score,
                distance=distance, **extra)


class DiscoverySelectionTests(unittest.TestCase):
    def test_two_reserved_discoveries_preserve_top_ranked_known_matches(self):
        rows = [candidate("known1", "Known A", -.18), candidate("known2", "Known A", -.17),
                candidate("known3", "Known B", -.16), candidate("new1", "New A", .02),
                candidate("new2", "New B", .03), candidate("known4", "Known B", -.15)]
        result = select_candidates(rows, 5, known_artist_names={"known a", "known b"})
        self.assertEqual([s["track_id"] for s in result], ["known1", "known2", "known3", "new1", "new2"])
        self.assertEqual(sum(s["selection_context"]["discovery"] for s in result), 2)
        self.assertEqual(result[0]["selection_context"]["discovery_fulfilled"], 2)

    def test_collaboration_known_credit_disqualifies_and_pair_uses_all_credits(self):
        rows = [candidate("mixed", "Known; New A", -.1), candidate("duet", "New A;New B", .01),
                candidate("solo1", "New A", .02), candidate("solo2", "New B", .03), candidate("known", "Known", -.2)]
        result = select_candidates(rows, 5, known_artist_names={"known"})
        discoveries = [s["track_id"] for s in result if s["selection_context"]["discovery"]]
        self.assertEqual(discoveries, ["solo1", "solo2"])

    def test_provider_aliases_are_not_two_distinct_discovery_artists(self):
        ids = str(["A" * 22])
        rows = [candidate("a", "New Name", .01, id_artists=ids),
                candidate("alias", "Other Name", .02, id_artists=ids),
                candidate("distinct", "Distinct", .03), candidate("known", "Known", -.2)]
        result = select_candidates(rows, 5, known_artist_names={"known"})
        discoveries = [s["track_id"] for s in result if s["selection_context"]["discovery"]]
        self.assertEqual(discoveries, ["a", "distinct"])

    def test_shortage_does_not_claim_distant_or_unknown_audio_is_suitable(self):
        rows = [candidate("known", "Known", -.2), candidate("close", "New A", .02),
                candidate("far", "New B", .03, distance=.5),
                candidate("unknown", "New C", .01, distance=None)]
        result = select_candidates(rows, 5, known_artist_names={"known"})
        self.assertEqual(sum(s["selection_context"]["discovery"] for s in result), 1)
        self.assertEqual(result[0]["selection_context"]["discovery_shortfall"], 1)
        self.assertTrue(result[0]["selection_context"]["discovery_shortage_reason"])
        small = select_candidates(rows, 3, known_artist_names={"known"})
        self.assertEqual(small[0]["selection_context"]["discovery_requested"], 0)

    def test_known_stable_id_overlap_and_unsupported_route_are_explicit(self):
        rows = [candidate("alias", "Unknown Alias", -.1, known_artist_overlap=True),
                candidate("new", "New", .02)]
        result = select_candidates(rows, 5, known_artist_names={"known"})
        self.assertFalse(next(s for s in result if s["track_id"] == "alias")["selection_context"]["discovery"])
        unsupported = discovery_unavailable(rows, 5)
        self.assertEqual(unsupported[0]["selection_context"]["discovery_fulfilled"], 0)
        self.assertEqual(unsupported[0]["selection_context"]["discovery_shortfall"], 2)
