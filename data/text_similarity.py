"""Offline, language-separated lexical similarity experiment; never imported by the UI."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile

import numpy as np
from scipy import sparse
from sklearn.feature_extraction.text import TfidfVectorizer

MODEL_VERSION = "muljam-tfidf-word12-v1"


def corpus_hash(records):
    payload = json.dumps(sorted(records, key=lambda r: r["id"]), ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class TextIndex:
    """Persist vectors once; compute only one query against one language's rows."""

    def __init__(self, metadata, groups):
        self.metadata = metadata
        self.groups = groups

    @classmethod
    def build(cls, records):
        if len({r["id"] for r in records}) != len(records):
            raise ValueError("Duplicate song IDs")
        groups = {}
        for lang in sorted({r["language"] for r in records}):
            rows = sorted((r for r in records if r["language"] == lang and r["text"].strip()), key=lambda r: r["id"])
            if not rows:
                continue
            vectorizer = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True,
                                         max_features=20000, dtype=np.float32)
            try:
                matrix = vectorizer.fit_transform([r["text"] for r in rows]).tocsr()
            except ValueError as exc:
                if "empty vocabulary" in str(exc):
                    continue
                raise
            groups[lang] = (vectorizer, matrix, [r["id"] for r in rows])
        return cls({"model_version": MODEL_VERSION, "corpus_sha256": corpus_hash(records)}, groups)

    def save(self, directory):
        directory = Path(directory)
        directory.parent.mkdir(parents=True, exist_ok=True)
        if directory.exists():
            raise FileExistsError(directory)
        with tempfile.TemporaryDirectory(prefix="text-index-", dir=directory.parent) as temporary:
            self._save_files(Path(temporary))
            Path(temporary).rename(directory)

    def _save_files(self, directory):
        manifest = dict(self.metadata, languages={})
        for number, (lang, (vectorizer, matrix, ids)) in enumerate(sorted(self.groups.items())):
            filename = f"language-{number}.npz"
            sparse.save_npz(directory / filename, matrix)
            manifest["languages"][lang] = {"file": filename, "ids": ids,
                "vocabulary": {word: int(index) for word, index in vectorizer.vocabulary_.items()},
                "idf": vectorizer.idf_.tolist()}
        # Write manifest last: incomplete builds have no valid entry point.
        (directory / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls, directory, expected_corpus_hash=None):
        directory = Path(directory)
        metadata = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        if metadata["model_version"] != MODEL_VERSION:
            raise ValueError("Text model version changed; rebuild index")
        if expected_corpus_hash and metadata["corpus_sha256"] != expected_corpus_hash:
            raise ValueError("Text corpus changed; rebuild index")
        groups = {}
        for lang, item in metadata["languages"].items():
            filename = item["file"]
            if Path(filename).name != filename or not filename.endswith(".npz"):
                raise ValueError("Invalid index filename")
            vectorizer = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True,
                                         vocabulary=item["vocabulary"], dtype=np.float32)
            vectorizer.idf_ = np.asarray(item["idf"], dtype=np.float32)
            matrix = sparse.load_npz(directory / filename).tocsr()
            if matrix.shape != (len(item["ids"]), len(item["vocabulary"])):
                raise ValueError("Index dimensions do not match manifest")
            groups[lang] = (vectorizer, matrix, item["ids"])
        return cls(metadata, groups)

    def neighbors(self, song_id, limit=10):
        if limit < 1:
            return []
        for lang, (_, matrix, ids) in self.groups.items():
            if song_id in ids:
                row = ids.index(song_id)
                # TF-IDF rows are normalized, so dot product equals cosine.
                scores = (matrix @ matrix[row].T).tocoo()
                ranked = sorted(((ids[i], float(score)) for i, score in zip(scores.row, scores.data)
                                 if i != row and score > 0), key=lambda pair: (-pair[1], pair[0]))
                return [{"id": ident, "score": score, "language": lang,
                         "signal": "lexical_similarity"} for ident, score in ranked[:limit]]
        return []
