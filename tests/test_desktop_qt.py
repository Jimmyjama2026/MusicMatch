"""Real offscreen Qt/QML checks, with a thread-recording local service double."""
import copy
import os
import threading
import time
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PySide6.QtCore import QObject, QPoint, Qt, QUrl, QMetaObject, Q_ARG
    from PySide6.QtGui import QGuiApplication, QFontDatabase
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtQuick import QQuickItem
    from PySide6.QtTest import QTest
    from data.desktop_qt import DesktopBridge
    QT_AVAILABLE = True
except ImportError:
    QT_AVAILABLE = False


class ServiceDouble:
    def __init__(self):
        self.calls = []
        self.fail_initialize = False
        self.fail_search = False
        self.slow_search = False
        self.song = {"track_id": "song-a", "track_name": "A very long title " * 5,
                     "artists": "James Arthur and collaborators", "reason": "Nearby acoustic and vocal features.",
                     "reason_preview": "Near one of your liked-song neighborhoods", "liked": None}
        self.value = {"profiles": [{"id": "personal", "name": "Personal", "is_test": False},
                                   {"id": "test", "name": "Test", "is_test": True}],
                      "profile_id": "personal", "profile_name": "Personal", "favorites": [],
                      "recommendations": [], "batch_id": "", "counts": {"yes": 0, "no": 0},
                      "model_status": "Local feature neighborhoods", "message": ""}
        self.saved = {}
        self.closed = False

    def note(self, action):
        self.calls.append((action, threading.get_ident()))

    def current_state(self):
        return copy.deepcopy(self.value)

    def initialize(self):
        self.note("initialize")
        if self.fail_initialize:
            self.fail_initialize = False
            raise ValueError("Temporary loading failure")
        return self.current_state()

    def search(self, title, artist="", title_only=True):
        self.note("search")
        if self.slow_search:
            time.sleep(0.08)
        if self.fail_search:
            raise ValueError("Search failure")
        return [copy.deepcopy(self.song)]

    def add_favorite(self, track_id):
        self.note("add")
        self.value["favorites"] = [copy.deepcopy(self.song)]
        return self.current_state()

    def remove_favorite(self, track_id):
        self.note("remove")
        self.value["favorites"] = []
        return self.current_state()

    def recommend(self, fresh=False):
        self.note("recommend")
        self.value["recommendations"] = [] if fresh else [copy.deepcopy(self.song)]
        self.value["batch_id"] = "" if fresh else "batch-a"
        if not fresh:
            self.saved["batch-a"] = {"batch_id": "batch-a", "recommendations": [copy.deepcopy(self.song)]}
        return self.current_state()

    def rate(self, batch_id, track_id, liked, reason=None):
        self.note("rate")
        for song in self.saved[batch_id]["recommendations"]:
            song.update(liked=liked, feedback_reason=reason)
        if self.value["batch_id"] == batch_id:
            self.value["recommendations"] = copy.deepcopy(self.saved[batch_id]["recommendations"])
        return self.current_state()

    def more_like_this(self, track_id, fresh=False, steering="same"):
        self.note(("steer", track_id, fresh, steering))
        return self.current_state()

    def choose_comparison(self, comparison_id, choice):
        self.note(("compare", comparison_id, choice))
        self.offered = copy.deepcopy(self.value["comparison"])
        self.value.update(comparison=None, last_comparison={"id": comparison_id, "choice": choice}, comparison_stats={"count": 1})
        return self.current_state()

    def undo_comparison(self, comparison_id):
        self.note(("undo_comparison", comparison_id))
        self.value.update(comparison=self.offered, last_comparison=None, comparison_stats={"count": 0})
        return self.current_state()

    def reset_comparisons(self):
        self.note("reset_comparisons")
        self.value.update(comparison=None, last_comparison=None, comparison_stats={"count": 0})
        return self.current_state()

    def set_title_language(self, track_id, language):
        self.note(("title_language", track_id, language))
        return self.current_state()

    def list_history(self, rating="all", limit=30, offset=0):
        self.note("history")
        return [{"batch_id": key, "created_at": "2026-10-31", "count": len(value["recommendations"])}
                for key, value in self.saved.items()][offset:offset + limit]

    def load_history(self, batch_id, rating="all"):
        self.note("history_batch")
        return copy.deepcopy(self.saved[batch_id])

    def switch_profile(self, profile_id):
        self.note("switch")
        self.value.update(profile_id=profile_id, profile_name=profile_id.title(), favorites=[], recommendations=[], batch_id="", comparison=None, last_comparison=None, comparison_stats={})
        return self.current_state()

    def reset_test(self):
        self.note("reset")
        if self.value["profile_id"] != "test":
            raise ValueError("Reset is limited to Test")
        self.value.update(favorites=[], recommendations=[], batch_id="")
        return self.current_state()

    def close(self):
        self.note("close")
        self.closed = True


@unittest.skipUnless(QT_AVAILABLE, "Optional PySide6 desktop dependency is absent")
class QtDesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QGuiApplication.instance() or QGuiApplication([])
        if not QFontDatabase.families():
            # The Windows offscreen platform does not enumerate system fonts.
            for filename in ("segoeui.ttf", "segoeuib.ttf"):
                font = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / filename
                if font.exists():
                    QFontDatabase.addApplicationFont(str(font))

    def setUp(self):
        self.service = ServiceDouble()
        self.bridge = DesktopBridge(self.service)
        self.engine = QQmlApplicationEngine()
        self.warnings = []
        self.engine.warnings.connect(lambda errors: self.warnings.extend(str(e) for e in errors))
        self.engine.rootContext().setContextProperty("music", self.bridge)
        self.engine.load(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1] / "data/ui/Main.qml")))
        self.assertEqual(len(self.engine.rootObjects()), 1, self.warnings)
        self.window = self.engine.rootObjects()[0]

    def tearDown(self):
        self.window.close()
        self.bridge.close()
        self.bridge.executor.shutdown(wait=True)
        self.engine.deleteLater()
        self.app.processEvents()

    def wait(self):
        deadline = time.monotonic() + 5
        while self.bridge.busy and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.003)
        self.app.processEvents()
        self.assertFalse(self.bridge.busy)

    def initialize(self):
        self.bridge.initialize()
        self.wait()
        self.assertTrue(self.bridge.initialized)

    def visual_item(self, name, parent=None):
        parent = parent if parent is not None else self.window.contentItem()
        if parent.objectName() == name:
            return parent
        for child in parent.childItems():
            found = self.visual_item(name, child)
            if found is not None:
                return found
        return None

    def test_qml_workflow_and_worker_thread_ownership(self):
        notifications = []
        self.bridge.changed.connect(lambda: notifications.append(threading.get_ident()))
        self.initialize()
        title = self.window.findChild(QObject, "titleInput")
        self.assertEqual(title.property("implicitHeight"), 42)
        self.assertEqual(title.property("placeholderTextColor").name(), "#aab7ca")
        self.assertEqual(title.property("background").property("radius"), 9)
        title.setProperty("text", "Quite Miss Home")
        button = self.window.findChild(QObject, "searchButton")
        center = button.mapToScene(button.boundingRect().center())
        QTest.mouseClick(self.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                         QPoint(round(center.x()), round(center.y())))
        self.wait()
        self.assertEqual(len(self.bridge.searchResults), 1)
        self.bridge.addFavorite("song-a")
        self.wait()
        self.bridge.recommend(False)
        self.wait()
        self.assertEqual(self.bridge.state["batch_id"], "batch-a")
        self.assertEqual(len(self.bridge.state["recommendations"]), 1)
        self.bridge.rate("batch-a", "song-a", False, "Already know it")
        self.wait()
        self.assertEqual(self.bridge.state["recommendations"][0]["feedback_reason"], "Already know it")
        self.bridge.loadHistory("all", 0)
        self.wait()
        self.bridge.openHistory("batch-a")
        self.wait()
        self.bridge.rate("batch-a", "song-a", True, "")
        self.wait()
        self.assertTrue(self.bridge.historyBatch["recommendations"][0]["liked"])
        self.bridge.recommend(True)
        self.wait()
        self.assertEqual(self.bridge.state["recommendations"], [])
        self.assertEqual(self.bridge.state["batch_id"], "")
        self.bridge.switchProfile("test")
        self.wait()
        self.assertEqual(self.bridge.historyRows, [])
        self.assertEqual(self.bridge.historyBatch, {})
        self.assertEqual(title.property("text"), "")
        self.bridge.resetTest()
        self.wait()
        main_thread = threading.get_ident()
        self.assertTrue(all(tid != main_thread for _, tid in self.service.calls))
        self.assertEqual(len({tid for _, tid in self.service.calls}), 1)
        self.assertTrue(all(tid == main_thread for tid in notifications))
        self.assertEqual(self.warnings, [])

    def test_real_application_service_sqlite_history_and_focused_workflow(self):
        from data.application import ApplicationService
        from data.backend import FeedbackStore
        from tests.test_application import Engine, english_screen
        with tempfile.TemporaryDirectory() as folder:
            engine = Engine()
            self.bridge.service = ApplicationService(engine, FeedbackStore(Path(folder) / "qt.sqlite3"), english_screen(engine))
            self.initialize()
            self.bridge.search("a", "")
            self.wait()
            self.bridge.addFavorite("a")
            self.wait()
            self.bridge.recommend(False)
            self.wait()
            first_id = self.bridge.state["batch_id"]
            track = self.bridge.state["recommendations"][0]["track_id"]
            self.bridge.moreLikeThis(track, True)
            self.wait()
            self.assertEqual([s["track_id"] for s in self.bridge.state["favorites"]], ["a"])
            current_id = self.bridge.state["batch_id"]
            self.bridge.loadHistory("all", 0)
            self.wait()
            self.bridge.openHistory(first_id)
            self.wait()
            self.bridge.rate(first_id, track, False, "Already know it")
            self.wait()
            self.assertEqual(self.bridge.state["batch_id"], current_id)
            self.assertEqual(self.bridge.historyBatch["batch_id"], first_id)
            self.assertEqual(self.bridge.historyBatch["recommendations"][0]["feedback_reason"], "Already know it")
            self.bridge.switchProfile("test")
            self.wait()
            self.assertEqual(self.bridge.state["favorites"], [])
            self.assertEqual(self.warnings, [])

    def test_failed_initialize_can_retry_and_search_error_preserves_state(self):
        self.service.fail_initialize = True
        self.bridge.initialize()
        self.wait()
        self.assertFalse(self.bridge.initialized)
        self.assertIn("loading failure", self.bridge.error)
        self.initialize()
        self.service.fail_search = True
        before = copy.deepcopy(self.bridge.state)
        self.bridge.search("title", "")
        self.wait()
        self.assertIn("Search failure", self.bridge.error)
        self.assertEqual(self.bridge.state, before)
        self.assertEqual(self.warnings, [])

    def test_busy_guard_keeps_ui_responsive_and_prevents_profile_race(self):
        self.initialize()
        self.service.slow_search = True
        self.bridge.search("title", "")
        self.bridge.switchProfile("test")
        self.assertTrue(self.bridge.busy)
        self.window.setProperty("section", 1)
        self.app.processEvents()
        self.assertEqual(self.window.property("section"), 1)
        self.wait()
        self.assertEqual(self.bridge.state["profile_id"], "personal")
        self.assertFalse(any(action == "switch" for action, _ in self.service.calls))
        self.assertEqual(self.warnings, [])

    def test_rating_updates_preserve_scrolled_list_and_existing_delegates(self):
        songs = [dict(self.service.song, track_id="scroll-" + str(i),
                      track_name="Scroll song " + str(i), reason_preview="A nearby match " * 8)
                 for i in range(8)]
        self.service.value.update(recommendations=copy.deepcopy(songs), batch_id="scroll-batch")
        self.service.saved["scroll-batch"] = dict(batch_id="scroll-batch", recommendations=copy.deepcopy(songs))
        self.initialize()
        self.window.setWidth(800)
        self.window.setHeight(700)
        view = self.window.findChild(QObject, "discoveries")
        QTest.qWait(80)
        QMetaObject.invokeMethod(view, "positionViewAtIndex", Q_ARG(int, 4), Q_ARG(int, 0))
        QTest.qWait(80)
        before = float(view.property("contentY"))
        self.assertGreater(before, 100)
        resets = []
        self.bridge._recommendation_model.modelReset.connect(lambda: resets.append(True))
        for liked in (True, False, True):
            button = self.visual_item(("yesVote_" if liked else "noVote_") + "scroll-4")
            self.assertIsNotNone(button)
            QMetaObject.invokeMethod(button, "clicked")
            self.wait()
            QTest.qWait(40)
            self.assertAlmostEqual(float(view.property("contentY")), before, delta=2)
            self.assertEqual(self.bridge.state["recommendations"][4]["liked"], liked)
        self.assertEqual(resets, [])
        self.assertEqual(self.warnings, [])

    def test_narrow_window_actions_and_history_render_without_qml_errors(self):
        self.initialize()
        self.bridge.addFavorite("song-a")
        self.wait()
        self.bridge.recommend(False)
        self.wait()
        self.window.setWidth(560)
        self.window.setHeight(540)
        for section in (0, 1, 2, 3):
            self.window.setProperty("section", section)
            self.app.processEvents()
        self.bridge.loadHistory("all", 0)
        self.wait()
        self.bridge.openHistory("batch-a")
        self.wait()
        self.assertEqual(self.warnings, [])
        self.window.setProperty("section", 0)
        self.app.processEvents()
        for name in ("searchButton", "suggestButton"):
            item = self.window.findChild(QObject, name)
            right = item.mapToScene(item.boundingRect().topRight()).x()
            self.assertLessEqual(right, self.window.width() + 1, name)

    def test_keyboard_search_and_explicit_test_reset_confirmation(self):
        self.initialize()
        self.window.requestActivate()
        self.window.setProperty("section", 1)
        QTest.keyClick(self.window, Qt.Key.Key_K, Qt.KeyboardModifier.ControlModifier)
        self.app.processEvents()
        title = self.window.findChild(QObject, "titleInput")
        self.assertEqual(self.window.property("section"), 0)
        self.assertTrue(title.property("activeFocus"))
        QTest.keyClick(self.window, Qt.Key.Key_A)
        QTest.keyClick(self.window, Qt.Key.Key_Return)
        self.wait()
        self.assertEqual(len(self.bridge.searchResults), 1)
        self.bridge.switchProfile("test")
        self.wait()
        reset = self.window.findChild(QObject, "resetTestButton")
        dialog = self.window.findChild(QObject, "resetDialog")
        QMetaObject.invokeMethod(reset, "clicked")
        self.app.processEvents()
        self.assertTrue(dialog.property("visible"))
        self.assertFalse(any(action == "reset" for action, _ in self.service.calls))
        QMetaObject.invokeMethod(dialog, "reject")
        self.app.processEvents()
        self.assertFalse(any(action == "reset" for action, _ in self.service.calls))
        QMetaObject.invokeMethod(reset, "clicked")
        QMetaObject.invokeMethod(dialog, "accept")
        self.wait()
        self.assertEqual(sum(action == "reset" for action, _ in self.service.calls), 1)
        self.assertEqual(self.warnings, [])

    def test_neighborhood_tab_keyboard_selection_and_saved_match_comparison(self):
        visual = {
            "available": True,
            "projection_note": "Approximate 2D projection; ranking uses all 21 dimensions.",
            "points": [
                {"track_id": "anchor", "track_name": "Liked acoustic song", "artists": "Anchor artist",
                 "x": .2, "y": .3, "group": "0", "kind": "liked", "discovery": False},
                {"track_id": "positive", "track_name": "A positive rating", "artists": "Other artist",
                 "x": .4, "y": .35, "group": "0", "kind": "positive", "discovery": False},
                {"track_id": "song-a", "track_name": "Quite Miss Home", "artists": "James Arthur",
                 "x": .7, "y": .6, "group": "0", "kind": "suggestion", "discovery": True}],
            "groups": [{"id": "0", "label": "Acoustic neighborhood", "anchor_count": 2}]}
        self.service.value["neighborhood_view"] = visual
        self.service.song.update(
            neighborhood_visual=visual,
            matched_anchor={"track_id": "anchor", "track_name": "Liked acoustic song", "artists": "Anchor artist"},
            selection_context={"discovery": True},
            match_table=[{"feature": "Tempo", "liked": "80 BPM", "suggested": "84 BPM", "note": "Raw measured values"},
                         {"feature": "Acousticness", "liked": "0.75", "suggested": "0.71", "note": "Scale 0–1"},
                         {"feature": "Missing feature", "liked": "Unavailable", "suggested": "Unavailable", "note": "Missing information is not a zero."}])
        self.initialize()
        navigation = self.visual_item("navigation_3")
        self.assertIsNotNone(navigation)
        QMetaObject.invokeMethod(navigation, "clicked")
        self.app.processEvents()
        self.assertEqual(self.window.property("section"), 3)
        overview = self.window.findChild(QObject, "overviewNeighborhoodMap")
        self.assertTrue(overview.property("hasPoints"))
        point = self.visual_item("neighborhoodPoint_0", overview)
        self.assertIsNotNone(point)
        self.window.requestActivate()
        point.forceActiveFocus()
        QTest.keyClick(self.window, Qt.Key.Key_Return)
        self.app.processEvents()
        selected = overview.property("selectedPoint")
        selected = selected.toVariant() if hasattr(selected, "toVariant") else selected
        self.assertEqual(selected["track_id"], "anchor")
        selection_label = overview.findChild(QObject, "mapSelectionLabel")
        self.assertIn("Acoustic neighborhood", selection_label.property("text"))
        self.service.value["neighborhood_view"] = dict(visual, points=[dict(visual["points"][0], track_id="new-context")])
        self.bridge.addFavorite("song-a")
        self.wait()
        QMetaObject.invokeMethod(self.window, "showDetails", Q_ARG("QVariant", self.service.song))
        QTest.qWait(160)
        detail = self.window.findChild(QObject, "detailNeighborhoodMap")
        self.assertEqual(detail.property("focusedTrackId"), "song-a")
        self.assertTrue(detail.property("hasPoints"))
        detail_points = detail.property("points")
        detail_points = detail_points.toVariant() if hasattr(detail_points, "toVariant") else detail_points
        self.assertEqual(detail_points[0]["track_id"], "anchor")
        note = detail.findChild(QObject, "projectionNote")
        self.assertIn("Approximate 2D", note.property("text"))
        self.assertTrue(note.property("visible"))
        table = self.window.findChild(QObject, "matchComparisonTable")
        rows = table.property("rows")
        rows = rows.toVariant() if hasattr(rows, "toVariant") else rows
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[-1]["suggested"], "Unavailable")
        self.window.setWidth(560)
        self.app.processEvents()
        self.assertLessEqual(table.mapToScene(table.boundingRect().topRight()).x(), 561)
        QTest.keyClick(self.window, Qt.Key.Key_Escape)
        QTest.qWait(120)
        self.assertEqual(self.warnings, [])

    def test_steering_language_and_optional_comparison_controls(self):
        self.service.value.update(comparison={"id": "pair-a", "anchor": {"track_name": "Favorite anchor"},
                                             "a": self.service.song, "b": dict(self.service.song, track_id="song-b", track_name="Second choice")},
                                  comparison_stats={"count": 0})
        self.service.song["title_language"] = {"status": "unknown", "language": "unknown", "source": "title"}
        self.initialize()
        self.window.setWidth(560)
        self.window.setHeight(540)
        panel = self.window.findChild(QObject, "comparisonPanel")
        self.assertFalse(panel.property("expanded"))
        QMetaObject.invokeMethod(self.visual_item("comparisonToggle"), "clicked")
        self.app.processEvents()
        self.assertTrue(panel.property("expanded"))
        choice = self.visual_item("comparisonA")
        self.assertLessEqual(choice.mapToScene(choice.boundingRect().topRight()).x(), 561)
        QMetaObject.invokeMethod(choice, "clicked")
        self.wait()
        self.assertIn(("compare", "pair-a", "a"), [action for action, _ in self.service.calls])
        QMetaObject.invokeMethod(self.visual_item("comparisonUndo"), "clicked")
        self.wait()
        self.assertIn(("undo_comparison", "pair-a"), [action for action, _ in self.service.calls])
        QMetaObject.invokeMethod(self.window, "showDetails", Q_ARG("QVariant", self.service.song))
        QTest.qWait(160)
        picker = self.window.findChild(QObject, "steeringPicker")
        picker.setProperty("currentIndex", 2)
        QMetaObject.invokeMethod(self.window.findChild(QObject, "steeredMoreButton"), "clicked")
        self.wait()
        self.assertIn(("steer", "song-a", False, "faster"), [action for action, _ in self.service.calls])
        QMetaObject.invokeMethod(self.window, "showDetails", Q_ARG("QVariant", self.service.song))
        QTest.qWait(160)
        self.assertEqual(picker.property("currentIndex"), 0)
        self.assertIsNone(self.window.findChild(QObject, "titleLanguagePicker"))
        self.assertIsNone(self.window.findChild(QObject, "detailTitleLanguage"))
        self.bridge.chooseComparison("pair-a", "equal")
        self.wait()
        dialog = self.window.findChild(QObject, "resetComparisonsDialog")
        QMetaObject.invokeMethod(self.visual_item("comparisonReset"), "clicked")
        self.app.processEvents()
        self.assertTrue(dialog.property("visible"))
        QMetaObject.invokeMethod(dialog, "reject")
        self.assertNotIn("reset_comparisons", [action for action, _ in self.service.calls])
        QMetaObject.invokeMethod(self.visual_item("comparisonReset"), "clicked")
        QMetaObject.invokeMethod(dialog, "accept")
        self.wait()
        self.assertIn("reset_comparisons", [action for action, _ in self.service.calls])
        picker.setProperty("currentIndex", 4)
        self.bridge.switchProfile("test")
        self.wait()
        self.assertEqual(picker.property("currentIndex"), 0)
        self.assertFalse(panel.property("expanded"))
        self.assertEqual(self.warnings, [])


if __name__ == "__main__":
    unittest.main()
