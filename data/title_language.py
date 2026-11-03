"""Conservative, offline title-language screening, not sung-language detection.

Only confidently English titles or explicit English corrections are eligible.
Uncertain titles remain Unknown and are excluded. No titles leave the computer.
This screens written titles; it cannot verify the language of the sung audio.
"""
from __future__ import annotations

from collections import OrderedDict
from contextlib import contextmanager, ExitStack
import json
import math
from pathlib import Path
import re
import sqlite3
import unicodedata

DETECTOR_VERSION = "py3langid-0.4.0-title-policy-v3-english-only"
CONFIDENCE_THRESHOLD = .90
MAX_CACHE_BYTES = 40 * 1024 * 1024
_VERSION_MARKER = re.compile(
    r"\s*(?:[-–—]\s*|\()(?:(?:\d{4}\s+)?remaster(?:ed)?(?:\s+\d{4})?|live(?:\s+version)?|radio\s+edit|album\s+version)\)?\s*$",
    re.IGNORECASE,
)


def normalize_title(title):
    title = unicodedata.normalize("NFKC", str(title or ""))[:512]
    return " ".join(_VERSION_MARKER.sub("", title).casefold().split())


class TitleLanguageScreen:
    def __init__(self, cache_path=None, detector=None):
        self.cache_path = Path(cache_path) if cache_path is not None else None
        self._detector = detector
        self._load_error = None
        self._cache = OrderedDict()
        self._overrides = {}
        self._ready = False
        self._session_connection = None

    @contextmanager
    def session(self):
        """Batch worker-side screening into one bounded cache transaction."""
        if self.cache_path is None or self._session_connection is not None:
            yield self
            return
        with ExitStack() as stack:
            try:
                connection = stack.enter_context(self._connect())
            except (sqlite3.Error, OSError):
                yield self
                return
            self._session_connection = connection
            try:
                yield self
            finally:
                self._session_connection = None

    @contextmanager
    def _connect(self):
        if self._session_connection is not None:
            yield self._session_connection
            return
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.cache_path, timeout=3)
        try:
            page_size = connection.execute("PRAGMA page_size").fetchone()[0]
            # Leave room for a rollback journal plus the installed detector
            # within this round's 100 MB additional disk budget.
            connection.execute(f"PRAGMA max_page_count = {MAX_CACHE_BYTES // page_size}")
            if not self._ready:
                connection.execute("CREATE TABLE IF NOT EXISTS title_cache (version TEXT, title TEXT, result TEXT, PRIMARY KEY(version,title))")
                connection.execute("CREATE TABLE IF NOT EXISTS language_overrides (track_id TEXT PRIMARY KEY, language TEXT NOT NULL)")
                connection.commit()
                self._ready = True
            with connection:
                yield connection
        finally:
            connection.close()

    @staticmethod
    def _result(language=None, confidence=None, status="unknown", reason=None, source="title"):
        result = dict(language=language, confidence=confidence, status=status,
                      allowed=status == "allowed" and language == "en", source=source,
                      detector_version=DETECTOR_VERSION)
        if reason:
            result["reason"] = reason
        return result

    def _override(self, track_id):
        if not track_id:
            return None
        if track_id in self._overrides:
            return self._overrides[track_id]
        if self.cache_path is not None:
            try:
                with self._connect() as connection:
                    row = connection.execute("SELECT language FROM language_overrides WHERE track_id=?", (track_id,)).fetchone()
                    if row:
                        self._overrides[track_id] = row[0]
                        return row[0]
            except (sqlite3.Error, OSError):
                pass
        self._overrides[track_id] = None
        if len(self._overrides) > 25000:
            self._overrides.clear()
        return None

    def set_override(self, track_id, language):
        track_id = str(track_id or "").strip()
        if not track_id or language not in {"auto", "en", "es", "other", "unknown"}:
            raise ValueError("Choose a song and auto, en, es, other, or unknown.")
        if self.cache_path is not None:
            with self._connect() as connection:
                if language == "auto":
                    connection.execute("DELETE FROM language_overrides WHERE track_id=?", (track_id,))
                else:
                    connection.execute("INSERT OR REPLACE INTO language_overrides VALUES (?,?)", (track_id, language))
        if language == "auto":
            self._overrides.pop(track_id, None)
        else:
            self._overrides[track_id] = language
        return {"track_id": track_id, "language": language}

    def _remember_memory(self, title, result):
        self._cache[title] = dict(result)
        self._cache.move_to_end(title)
        if len(self._cache) > 25000:
            self._cache.popitem(last=False)

    def _remember(self, title, result):
        self._remember_memory(title, result)
        if self.cache_path is not None and result.get("reason") != "detector_unavailable":
            try:
                with self._connect() as connection:
                    connection.execute("INSERT OR REPLACE INTO title_cache VALUES (?,?,?)", (DETECTOR_VERSION, title, json.dumps(result)))
            except (sqlite3.Error, OSError):
                pass  # A full/unwritable cache must not interrupt suggestions.

    def screen(self, song):
        override = self._override(str(song.get("track_id", "")))
        if override:
            return self._result(None if override == "unknown" else override, None,
                                "unknown" if override == "unknown" else "allowed" if override == "en" else "blocked",
                                "manual_correction", "override")
        title = normalize_title(song.get("track_name", song.get("title", song.get("name", ""))))
        if title in self._cache:
            return dict(self._cache[title])
        if self.cache_path is not None:
            try:
                with self._connect() as connection:
                    row = connection.execute("SELECT result FROM title_cache WHERE version=? AND title=?", (DETECTOR_VERSION, title)).fetchone()
                if row:
                    result = json.loads(row[0])
                    self._remember_memory(title, result)
                    return dict(result)
            except (sqlite3.Error, OSError, ValueError):
                pass
        letters = [letter for letter in title if letter.isalpha()]
        # A script check is evidence about the written title only. Short CJK
        # names often have weak model probabilities despite an obvious script.
        # Ignore mathematical alphabets and require two letters plus a meaningful
        # fraction, so an isolated Greek variable does not block an English title.
        foreign_letters = [letter for letter in letters
                           if "LATIN" not in unicodedata.name(letter, "")
                           and not any(marker in unicodedata.name(letter, "")
                                       for marker in ("MATHEMATICAL", "DOUBLE-STRUCK", "BLACK-LETTER", "SCRIPT CAPITAL", "SCRIPT SMALL"))]
        latin = all("LATIN" in unicodedata.name(letter, "") for letter in letters)
        if len(foreign_letters) >= 2 and len(foreign_letters) / len(letters) >= .25:
            result = self._result("other", None, "blocked", "clear_non_latin_title_script")
        elif len(letters) < (8 if latin else 5) or (latin and len(title.split()) < 2):
            result = self._result(reason="short_or_ambiguous_title")
        else:
            result = self._classify(title)
        self._remember(title, result)
        return dict(result)

    def _classify(self, title):
        if self._detector is None and self._load_error is None:
            try:
                from py3langid.langid import LanguageIdentifier, MODEL_FILE
                self._detector = LanguageIdentifier.from_model_file(MODEL_FILE, norm_probs=True)
                # Deliberately keep every supported language enabled.
            except Exception as error:
                self._load_error = type(error).__name__
        if self._detector is None:
            return self._result(reason="detector_unavailable")
        try:
            classify = getattr(self._detector, "classify", self._detector)
            language, confidence = classify(title)
            confidence = float(confidence)
            if not math.isfinite(confidence) or not 0 <= confidence <= 1:
                return self._result(reason="invalid_detector_confidence")
            if confidence < CONFIDENCE_THRESHOLD:
                return self._result(confidence=confidence, reason="uncertain_title")
            if language in {"und", "zxx", "unknown", ""}:
                return self._result(confidence=confidence, reason="nonlinguistic_or_unknown_title")
            return self._result(str(language), confidence, "allowed" if language == "en" else "blocked")
        except Exception:
            return self._result(reason="detector_unavailable")

    def allows(self, song):
        return self.screen(song)["allowed"]
