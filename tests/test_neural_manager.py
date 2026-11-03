import copy
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from data.neural_manager import NeuralTrainingManager
from tests.test_neural_learning import fixture


class NeuralManagerTests(unittest.TestCase):
    def wait_for(self, predicate, timeout=12):
        deadline = time.monotonic() + timeout
        while not predicate() and time.monotonic() < deadline:
            time.sleep(.02)
        self.assertTrue(predicate())

    def test_low_data_never_launches_and_duration_version_is_respected(self):
        manifest, records = fixture(30)
        with tempfile.TemporaryDirectory() as temporary:
            manager = NeuralTrainingManager(temporary, launcher=lambda *a, **k: self.fail("No worker expected"))
            try:
                with patch("data.neural_manager.load_training_records", return_value=records):
                    result = manager.observe("unused", "test", manifest)
                    self.assertEqual(result["counts"]["eligible"], 30)
                    self.assertEqual(result["state"], "needs_data")
                    self.assertFalse(result["enabled"])
                    records[0]["feature_version"] = "rich-audio-vectors-v1"
                    self.assertEqual(manager.observe("unused", "test", manifest)["counts"]["eligible"], 30)
                    records[0]["feature_version"] = "old-duration-features"
                    self.assertEqual(manager.observe("unused", "test", manifest)["counts"]["eligible"], 29)
                    for record in records:
                        record["anchor"]["artists"] = ""
                    self.assertEqual(manager.observe("unused", "test", manifest)["counts"]["anchor_families"], 0)
                self.assertFalse((Path(temporary) / "test").exists())
            finally:
                manager.close()

    def test_real_isolated_worker_produces_only_shadow_artifact(self):
        manifest, records = fixture()
        with tempfile.TemporaryDirectory() as temporary:
            manager = NeuralTrainingManager(temporary, idle_seconds=.01)
            try:
                with patch("data.neural_manager.load_training_records", return_value=records):
                    manager.observe("unused", "test", manifest)
                    status = Path(temporary) / "test/status.json"
                    self.wait_for(lambda: status.exists())
                    self.wait_for(lambda: manager._process is None)
                    result = json.loads(status.read_text())
                    self.assertEqual(result["state"], "shadow_ready", result)
                    self.assertFalse(result["enabled"])
                    self.assertLess(result["artifact_bytes"], 1024 * 1024)
                    self.assertFalse((Path(temporary) / "test/job-input.json").exists())
                    # Same data cannot restart training or move its checkpoint.
                    manifest_path = Path(temporary) / "test/manifest.json"
                    saved = manifest_path.read_bytes()
                    manager.observe("unused", "test", manifest)
                    time.sleep(.08)
                    self.assertEqual(manifest_path.read_bytes(), saved)
                    self.assertIsNone(manager._timer)
            finally:
                manager.close()

    def test_worker_deadline_kills_and_does_not_enable_model(self):
        class Process:
            def __init__(self): self.killed = False
            def poll(self): return None
            def kill(self): self.killed = True
            def wait(self): return 0
        manifest, records = fixture()
        process = Process()
        with tempfile.TemporaryDirectory() as temporary:
            staging = Path(temporary) / "test/.training-interrupted"
            staging.mkdir(parents=True)
            (staging / "partial.npz").write_bytes(b"partial")
            manager = NeuralTrainingManager(temporary, idle_seconds=.01, timeout_seconds=.05,
                                            launcher=lambda *args, **kwargs: process)
            try:
                with patch("data.neural_manager.load_training_records", return_value=records):
                    manager.observe("unused", "test", manifest)
                    self.wait_for(lambda: process.killed)
                    self.wait_for(lambda: manager._process is None)
                self.assertFalse(staging.exists())
                result = json.loads((Path(temporary) / "test/status.json").read_text())
                self.assertEqual(result["state"], "budget_exceeded")
                self.assertFalse(result["enabled"])
            finally:
                manager.close()

    def test_close_and_test_reset_cancel_pending_jobs_without_clearing_personal(self):
        manifest, records = fixture()
        with tempfile.TemporaryDirectory() as temporary:
            manager = NeuralTrainingManager(temporary, idle_seconds=5,
                                            launcher=lambda *a, **k: self.fail("Cancelled job launched"))
            personal = Path(temporary) / "personal"
            personal.mkdir()
            (personal / "retained.json").write_text("{}")
            with patch("data.neural_manager.load_training_records", return_value=records):
                manager.observe("unused", "test", manifest)
                self.assertIsNotNone(manager._timer)
                manager.reset("test")
                self.assertTrue((personal / "retained.json").exists())
                self.assertIsNone(manager._timer)
                manager.observe("unused", "test", manifest)
                manager.close()
                self.assertIsNone(manager._timer)
                self.assertFalse((Path(temporary) / "test/job-input.json").exists())
