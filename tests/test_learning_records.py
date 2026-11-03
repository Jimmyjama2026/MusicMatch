import tempfile
from pathlib import Path
import unittest

from data.backend import FeedbackStore
from data.learning_records import load_examples, partition_examples, prepare_model_inputs


class LearningRecordsTests(unittest.TestCase):
    def test_saved_feature_context_reason_and_profiles_survive_read_only_export(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "feedback.sqlite3"
            store = FeedbackStore(path)
            favorite = {"track_id": "a", "track_name": "Favorite", "artists": "A"}
            song = {"track_id": "b", "track_name": "Candidate", "artists": "B",
                "model_version": "neighborhood-test", "feature_version": "vectors-test",
                "source_fingerprint": "snapshot-test", "neighborhood_context": {"anchor_id": "a"}}
            batch = store.save_batch([favorite], [song])
            store.save_feedback(batch, "b", False, reason="Already know it")
            original = path.read_bytes()
            examples = load_examples(path, "personal")
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(load_examples(path, "test"), [])
            self.assertEqual(examples[0]["feature_version"], "vectors-test")
            self.assertEqual(examples[0]["favorites"], [favorite])
            self.assertEqual(examples[0]["neighborhood_context"], {"anchor_id": "a"})
            self.assertEqual(store.training_feedback()[0]["feedback_reason"], "Already know it")
            partitions = partition_examples(examples)
            self.assertEqual(len(partitions["exclusion_only"]), 1)
            self.assertEqual(partitions["training"] + partitions["evaluation"], [])

    def test_aliases_share_partition_and_split_is_stable(self):
        songs = [{"track_id": "1", "track_name": "Song", "artists": "A; B"},
                 {"track_id": "2", "track_name": " SONG ", "artists": "B; A"}]
        examples = [{"song": s, "liked": True} for s in songs]
        result = partition_examples(examples)
        self.assertIn(2, [len(result["training"]), len(result["evaluation"])])
        self.assertEqual(result, partition_examples(examples))
        self.assertEqual(len(partition_examples(examples, 0)["training"]), 2)
        with self.assertRaises(ValueError):
            partition_examples(examples, 1)

    def test_model_inputs_remove_held_out_aliases_and_historical_outputs(self):
        held = {"track_id": "eval", "track_name": "Held out", "artists": "A"}
        alias = dict(held, track_id="alias")
        train = {"track_id": "train", "track_name": "Training", "artists": "B",
                 "neighborhood_context": {"anchor_id": "eval"}, "ranking_score": .001}
        partitions = {"training": [{"song": train, "liked": True,
                                     "favorites": [alias, train]}],
                      "evaluation": [{"song": held, "liked": True, "favorites": [train]}]}
        inputs = prepare_model_inputs(partitions)
        self.assertEqual(inputs["training"][0]["favorites"], [])
        self.assertNotIn("neighborhood_context", inputs["training"][0]["song"])
        self.assertNotIn("ranking_score", inputs["training"][0]["song"])
        self.assertEqual(inputs["evaluation"][0]["song"]["track_id"], "eval")
