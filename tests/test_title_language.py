import json
import math
import sqlite3
from pathlib import Path
import tempfile
import unittest

from data.title_language import DETECTOR_VERSION, TitleLanguageScreen, normalize_title


class TitleLanguageTests(unittest.TestCase):
    def song(self, title="A sufficiently long song title", track_id="one"):
        return {"track_id": track_id, "track_name": title}

    def test_all_language_classification_then_allowlist(self):
        for language, expected in [("en", True), ("es", False), ("fr", False), ("pt", False), ("zh", False)]:
            screen = TitleLanguageScreen(detector=lambda title: (language, .99))
            result = screen.screen(self.song())
            self.assertEqual(result["allowed"], expected)
            self.assertEqual(result["language"], language)
            self.assertEqual(result["source"], "title")

    def test_threshold_and_invalid_confidences_are_conservative(self):
        for confidence in [.8999, -1, 2, math.nan, math.inf]:
            result = TitleLanguageScreen(detector=lambda text: ("fr", confidence)).screen(self.song())
            self.assertFalse(result["allowed"])
            self.assertEqual(result["status"], "unknown")
            self.assertTrue(result["confidence"] is None or math.isfinite(result["confidence"]))
        self.assertFalse(TitleLanguageScreen(detector=lambda text: ("fr", .90)).allows(self.song()))
        self.assertTrue(TitleLanguageScreen(detector=lambda text: ("en", .90)).allows(self.song()))

    def test_names_short_numeric_and_empty_are_unknown_without_detector(self):
        def forbidden(title):
            self.fail("Ambiguous title should not be classified")
        for title in ["Hello", "Paris", "BTS", "123", "", "Despacito"]:
            result = TitleLanguageScreen(detector=forbidden).screen(self.song(title))
            self.assertEqual(result["status"], "unknown")
            self.assertFalse(result["allowed"], title)

    def test_clear_foreign_written_scripts_even_when_short_or_mixed(self):
        def forbidden(title):
            self.fail("Clear written script should not need model classification")
        screen = TitleLanguageScreen(detector=forbidden)
        for title in ["無人之境", "無人之境 in Bb major", "東京の夜", "사랑해요", "Привет", "مرحبا"]:
            result = screen.screen(self.song(title))
            self.assertFalse(result["allowed"], title)
            self.assertEqual(result["language"], "other")
            self.assertEqual(result["reason"], "clear_non_latin_title_script")
            self.assertIsNone(result["confidence"])
        screen.set_override("one", "es")
        self.assertFalse(screen.allows(self.song("無人之境")))
        screen.set_override("one", "en")
        self.assertTrue(screen.allows(self.song("無人之境")))

    def test_latin_diacritics_math_and_emoji_do_not_trigger_script_block(self):
        screen = TitleLanguageScreen(detector=lambda title: ("en", .99))
        for title in ["Canción de corazón", "An English title α", "Love 💙 Forever", "A song about 𝛼 and 𝛽", "An English title 中"]:
            self.assertTrue(screen.allows(self.song(title)), title)

    def test_marker_normalization_preserves_meaningful_words(self):
        self.assertEqual(normalize_title("I Love You - 2011 Remaster"), "i love you")
        self.assertEqual(normalize_title("I Love You (Live)"), "i love you")
        self.assertEqual(normalize_title("Live Forever"), "live forever")
        self.assertEqual(normalize_title("A Different Remix"), "a different remix")

    def test_cache_and_manual_corrections_persist_without_profile_coupling(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cache.sqlite3"
            calls = []
            screen = TitleLanguageScreen(path, lambda text: (calls.append(text) or "fr", .99))
            self.assertFalse(screen.allows(self.song()))
            self.assertFalse(screen.allows(self.song(track_id="two")))
            self.assertEqual(len(calls), 1)
            screen.set_override("one", "es")
            self.assertFalse(screen.allows(self.song()))
            self.assertFalse(screen.allows(self.song(track_id="two")))
            restarted = TitleLanguageScreen(path, lambda text: self.fail("Cached"))
            self.assertEqual(restarted.screen(self.song())["language"], "es")
            restarted.set_override("one", "auto")
            self.assertFalse(restarted.allows(self.song()))
            restarted.set_override("one", "unknown")
            self.assertEqual(restarted.screen(self.song())["status"], "unknown")
            self.assertFalse(restarted.allows(self.song()))
            restarted.set_override("one", "en")
            self.assertTrue(restarted.allows(self.song()))
            with self.assertRaises(ValueError):
                restarted.set_override("one", "de")

    def test_dependency_failure_is_visible_and_safe(self):
        screen = TitleLanguageScreen()
        screen._load_error = "ImportError"
        result = screen.screen(self.song())
        self.assertFalse(result["allowed"])
        self.assertEqual(result["reason"], "detector_unavailable")

    def test_detector_exception_cannot_allow_unknown(self):
        def broken(title):
            raise RuntimeError("Model unavailable")
        result = TitleLanguageScreen(detector=broken).screen(self.song())
        self.assertFalse(result["allowed"])
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(result["reason"], "detector_unavailable")

    def test_current_english_cache_is_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cache.sqlite3"
            self.assertTrue(TitleLanguageScreen(path, lambda text: ("en", .99)).allows(self.song()))
            restarted = TitleLanguageScreen(path, lambda text: self.fail("Use cached English"))
            self.assertTrue(restarted.allows(self.song()))

    def test_old_policy_cache_cannot_admit_spanish_or_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cache.sqlite3"
            screen = TitleLanguageScreen(path, lambda text: ("es", .99))
            with screen._connect() as connection:
                for title, language in [("La vida es una canción", "es"), ("Hello", None)]:
                    result = {"allowed": True, "language": language, "status": "unknown"}
                    connection.execute("INSERT INTO title_cache VALUES (?,?,?)", (
                        "py3langid-0.4.0-title-policy-v2", normalize_title(title), json.dumps(result)))
            for title in ["La vida es una canción", "Hello"]:
                result = screen.screen(self.song(title))
                self.assertFalse(result["allowed"])
                self.assertEqual(result["detector_version"], DETECTOR_VERSION)

    def test_cache_failure_still_classifies_in_memory(self):
        with tempfile.TemporaryDirectory() as directory:
            # A file cannot serve as a parent directory for the SQLite cache.
            blocked_parent = Path(directory) / "file"
            blocked_parent.write_text("occupied")
            calls = []
            screen = TitleLanguageScreen(blocked_parent / "cache.sqlite3",
                                         lambda text: (calls.append(text) or "en", .99))
            with screen.session():
                self.assertTrue(screen.allows(self.song()))
                self.assertTrue(screen.allows(self.song(track_id="two")))
            self.assertEqual(len(calls), 1)

    def test_nonlinguistic_detector_labels_remain_unknown(self):
        for label in ["und", "zxx", "unknown", ""]:
            result = TitleLanguageScreen(detector=lambda text: (label, .99)).screen(self.song())
            self.assertEqual(result["status"], "unknown")
            self.assertFalse(result["allowed"])

    def test_batch_session_persists_and_closes_its_connection(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cache.sqlite3"
            screen = TitleLanguageScreen(path, lambda text: ("fr", .99))
            with screen.session():
                self.assertFalse(screen.allows(self.song()))
                with screen.session():
                    screen.set_override("one", "es")
                    self.assertFalse(screen.allows(self.song()))
            self.assertIsNone(screen._session_connection)
            restarted = TitleLanguageScreen(path, lambda text: self.fail("Cached"))
            self.assertFalse(restarted.allows(self.song()))
            self.assertFalse(restarted.allows(self.song(track_id="two")))

    def test_actual_detector_small_phrase_smoke_check(self):
        try:
            import py3langid  # noqa: F401
        except ImportError:
            self.skipTest("Optional local detector is not installed")
        screen = TitleLanguageScreen()
        for title in ["Never going to give you up", "You Are Always On My Mind"]:
            self.assertTrue(screen.allows(self.song(title)), title)
        for title, language in [("La vida es una canción", "es"),
                                ("Te quiero con todo mi corazón", "es"),
                                ("Je ne veux pas travailler", "fr"),
                                ("Você não sabe o que é amar", "pt"),
                                ("我真的很想念你", "other")]:
            result = screen.screen(self.song(title))
            self.assertFalse(result["allowed"], title)
            self.assertIn(result["language"], (language, None))
        self.assertEqual(screen.screen(self.song("Paris"))["status"], "unknown")
        result = screen.screen(self.song("I Will Always Love You"))
        self.assertEqual(result["status"], "unknown")
        self.assertFalse(result["allowed"])


if __name__ == "__main__":
    unittest.main()
