"""Debounced, isolated shadow training while the desktop application is running."""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time

from .identity import credited_artists
from .song_vectors import SongVectors
from .training_data import load_training_records, resolve_favorite_features


class NeuralTrainingManager:
    def __init__(self, output_root, *, idle_seconds=30, timeout_seconds=10, new_judgments=10,
                 launcher=None):
        self.root = Path(output_root)
        self.idle_seconds = idle_seconds
        self.timeout_seconds = timeout_seconds
        self.new_judgments = new_judgments
        self._launcher = launcher or subprocess.Popen
        self._lock = threading.RLock()
        self._timer = None
        self._process = None
        self._process_profile = None
        self._deadline = None
        self._input = None
        self._log = None
        self._profiles = {}
        self._closed = False

    def _directory(self, profile):
        if profile not in ("personal", "test"):
            raise ValueError("Unknown training profile.")
        return self.root / profile

    @staticmethod
    def _read(path):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    @staticmethod
    def _write(path, payload):
        temporary = path.with_suffix(path.suffix + ".new")
        temporary.write_text(json.dumps(payload, allow_nan=False), encoding="utf-8")
        os.replace(temporary, path)

    def observe(self, db_path, profile, manifest):
        """Called on the serialized service worker, never from the Qt thread."""
        if manifest is None:
            return {"state": "unavailable", "enabled": False, "mode": "shadow"}
        records = resolve_favorite_features(load_training_records(db_path, profile), manifest)
        from .neural_learning import record_features_compatible, MODEL_VERSION
        matching = [r for r in records if record_features_compatible(r, manifest)]
        if matching:
            transformer = SongVectors()
            transformer.metadata = manifest
            _, valid_song = transformer.transform([r["song"] for r in matching])
            _, valid_anchor = transformer.transform([r.get("anchor") or {} for r in matching])
            context_ok = valid_anchor.all(axis=1) | [r.get("judgment_source") == "favorite" and r.get("anchor") is None for r in matching]
            matching = [r for r, ok in zip(matching, valid_song.all(axis=1) & context_ok) if ok]
        labels = Counter(bool(r["liked"]) for r in matching)
        families = {credited_artists(r.get("anchor") or r["song"]) for r in matching if credited_artists(r.get("anchor") or r["song"])}
        fingerprint = hashlib.sha256(json.dumps({"model_version": MODEL_VERSION, "records": matching}, sort_keys=True).encode()).hexdigest()
        counts = dict(eligible=len(matching), yes=labels[True], no=labels[False],
                      anchor_families=len(families))
        from .genres import effective_labels
        counts["genre_known_pairs"] = sum(bool(effective_labels(r["song"]) and effective_labels(r.get("anchor") or {})) for r in matching)
        counts["favorite_positives"] = sum(r.get("judgment_source") == "favorite" for r in matching)
        ready = len(matching) >= 100 and min(labels[True], labels[False]) >= 20 and len(families) >= 3
        with self._lock:
            if self._closed:
                return {"state": "closed", "enabled": False, "mode": "shadow"}
            previous = self._profiles.get(profile, {})
            changes = previous.get("changes", 0) + int(previous.get("fingerprint") != fingerprint)
            current = dict(records=matching, manifest=dict(manifest), fingerprint=fingerprint,
                           counts=counts, ready=ready, changes=changes)
            self._profiles[profile] = current
            attempt = self._read(self._directory(profile) / "attempt.json")
            changes_since_attempt = changes - previous.get("attempt_changes", 0)
            current["attempt_changes"] = previous.get("attempt_changes", 0)
            last_count = attempt.get("count", -100)
            due = (ready and attempt.get("fingerprint") != fingerprint and
                   (not attempt or attempt.get("model_version") != MODEL_VERSION or len(matching) - last_count >= self.new_judgments or
                    changes_since_attempt >= self.new_judgments))
            if self._timer:
                self._timer.cancel()
                self._timer = None
            if due and self._process is None:
                self._timer = threading.Timer(self.idle_seconds, self._start, args=(profile,))
                self._timer.daemon = True
                self._timer.start()
            return self._status(profile)

    def _status(self, profile):
        current = self._profiles.get(profile, {})
        status = self._read(self._directory(profile) / "status.json") if current.get("ready") else {}
        from .neural_learning import MODEL_VERSION
        if status.get("version") != MODEL_VERSION:
            status = {}
        status.update(mode="shadow", enabled=False, counts=current.get("counts", {}),
                      requirements={"unique_judgments": 100, "per_class": 20, "anchor_artist_families": 3})
        if self._process_profile == profile:
            status["state"] = "training"
        elif not current.get("ready"):
            status["state"] = "needs_data"
        else:
            status.setdefault("state", "scheduled")
        return status

    def _start(self, profile):
        with self._lock:
            self._timer = None
            if self._closed or self._process is not None:
                return
            current = self._profiles.get(profile)
            if not current or not current["ready"]:
                return
            directory = self._directory(profile)
            try:
                directory.mkdir(parents=True, exist_ok=True)
                self._cleanup_staging(directory)
                self._input = directory / "job-input.json"
                self._write(self._input, {"records": current["records"], "feature_manifest": current["manifest"]})
                from .neural_learning import MODEL_VERSION
                self._write(directory / "attempt.json", dict(fingerprint=current["fingerprint"],
                    count=current["counts"]["eligible"], model_version=MODEL_VERSION))
                current["attempt_changes"] = current["changes"]
                env = dict(os.environ, OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
                flags = (getattr(subprocess, "CREATE_NO_WINDOW", 0) |
                         getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)) if os.name == "nt" else 0
                self._log = (directory / "worker.log").open("w", encoding="utf-8")
                self._process = self._launcher([sys.executable, "-m", "data.neural_worker",
                    "--input", str(self._input.resolve()), "--output", str(directory.resolve())],
                    cwd=str(Path(__file__).resolve().parents[1]), env=env,
                    stdin=subprocess.DEVNULL, stdout=self._log, stderr=self._log, creationflags=flags)
                self._process_profile = profile
                self._deadline = time.monotonic() + self.timeout_seconds
                watcher = threading.Thread(target=self._watch, daemon=True)
                watcher.start()
            except (OSError, ValueError) as error:
                self._close_files()
                if directory.exists():
                    self._write(directory / "status.json", dict(state="worker_failed", mode="shadow",
                        enabled=False, detail=type(error).__name__))

    def _watch(self):
        while True:
            with self._lock:
                process = self._process
                if process is None:
                    return
                code = process.poll()
                if code is not None or time.monotonic() >= self._deadline:
                    directory = self._directory(self._process_profile)
                    if code is None:
                        process.kill()
                        process.wait()
                        self._write(directory / "status.json", dict(state="budget_exceeded", mode="shadow", enabled=False))
                    elif code:
                        self._write(directory / "status.json", dict(state="worker_failed", mode="shadow", enabled=False))
                    self._process = self._process_profile = None
                    self._close_files()
                    return
            time.sleep(.05)

    def _close_files(self):
        if self._log:
            self._log.close()
            self._log = None
        if self._input:
            directory = self._input.parent
            self._input.unlink(missing_ok=True)
            self._input = None
            self._cleanup_staging(directory)

    def _cleanup_staging(self, directory):
        """Reclaim incomplete artifacts only after this manager's worker stops."""
        directory = directory.resolve()
        if directory.parent != self.root.resolve() or directory.name not in ("personal", "test"):
            raise ValueError("Unsafe training staging directory.")
        for candidate in directory.glob(".training-*"):
            # Never follow a link or junction outside the verified profile directory.
            resolved = candidate.resolve()
            if resolved.parent == directory and not candidate.is_symlink() and candidate.is_dir():
                shutil.rmtree(resolved)

    def reset(self, profile):
        """Clear this profile's experimental artifacts after a confirmed profile reset."""
        with self._lock:
            if self._timer:
                self._timer.cancel()
                self._timer = None
            if self._process_profile == profile:
                self._process.kill()
                self._process.wait()
                self._process = self._process_profile = None
                self._close_files()
            self._profiles.pop(profile, None)
            directory, root = self._directory(profile).resolve(), self.root.resolve()
            if directory.parent != root or directory == root:
                raise ValueError("Unsafe training artifact directory.")
            if directory.exists():
                shutil.rmtree(directory)

    def close(self):
        with self._lock:
            self._closed = True
            if self._timer:
                self._timer.cancel()
                self._timer = None
            if self._process is not None:
                self._process.kill()
                self._process.wait()
                self._process = self._process_profile = None
            self._close_files()
