import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from data.text_similarity import MODEL_VERSION, TextIndex, corpus_hash
from scripts.build_text_index import parse_records
from scripts import build_text_index


class TextSimilarityTests(unittest.TestCase):
    def setUp(self):
        self.records = [
            {"id": "a", "language": "en", "text": "lonely heart broken love goodbye"},
            {"id": "b", "language": "en", "text": "broken heart lonely goodbye"},
            {"id": "c", "language": "en", "text": "sunshine dancing party celebration"},
            {"id": "d", "language": "fr", "text": "lonely heart broken love goodbye"},
        ]

    def test_roundtrip_language_and_self_exclusion(self):
        index = TextIndex.build(self.records)
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "index"
            index.save(target)
            loaded = TextIndex.load(target, corpus_hash(self.records))
            neighbors = loaded.neighbors("a")
            self.assertEqual([r["id"] for r in neighbors], ["b"])
            self.assertAlmostEqual(neighbors[0]["score"], index.neighbors("a")[0]["score"], places=6)
            self.assertEqual(loaded.neighbors("missing"), [])
            self.assertEqual(loaded.neighbors("a", 0), [])
            with self.assertRaises(ValueError):
                TextIndex.load(target, "changed-corpus")
            manifest = json.loads((target / "manifest.json").read_text())
            manifest["model_version"] = "old-version"
            (target / "manifest.json").write_text(json.dumps(manifest))
            with self.assertRaises(ValueError):
                TextIndex.load(target)

    def test_duplicate_ids_and_corpus_change(self):
        with self.assertRaises(ValueError):
            TextIndex.build(self.records + self.records[:1])
        changed = [dict(row) for row in self.records]
        changed[0]["text"] += " changed"
        self.assertNotEqual(corpus_hash(changed), corpus_hash(self.records))

    def test_failed_build_is_atomic_and_rerunnable(self):
        index = TextIndex.build(self.records)
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "index"
            with patch.object(index, "_save_files", side_effect=RuntimeError("interrupted")):
                with self.assertRaises(RuntimeError):
                    index.save(target)
            self.assertFalse(target.exists())
            self.assertEqual(list(Path(tmp).iterdir()), [])
            index.save(target)
            self.assertEqual(TextIndex.load(target).neighbors("a")[0]["id"], "b")

    def test_parser_joins_segments_without_losing_commas(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "sample.meta"
            source.write_text("id,file,lang,start,end,wrd\n123_1,x,en,10,20,love, goodbye\n123_0,x,en,0,10,hello\n", encoding="utf-8")
            self.assertEqual(parse_records([source]), [{"id": "jamendo:123", "language": "en", "text": "hello\nlove, goodbye"}])

    def test_exclusive_build_lock_and_exception_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lock = root / ".build.lock"
            lock.write_text("123")
            with patch("sys.argv", ["build_text_index.py", "--root", str(root)]), patch.object(build_text_index, "_run") as run:
                with self.assertRaises(RuntimeError):
                    build_text_index.main()
                run.assert_not_called()
            lock.unlink()
            with patch("sys.argv", ["build_text_index.py", "--root", str(root)]), patch.object(build_text_index, "_run", side_effect=RuntimeError("failed")):
                with self.assertRaises(RuntimeError):
                    build_text_index.main()
            self.assertFalse(lock.exists())


if __name__ == "__main__":
    unittest.main()
