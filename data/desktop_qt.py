"""Qt presentation adapter. All service and SQLite work stays on one worker."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys

from PySide6.QtCore import QObject, Property, Signal, Slot, Qt, QUrl, QAbstractListModel, QModelIndex
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickWindow
from PySide6.QtQuickControls2 import QQuickStyle

QQuickStyle.setStyle("Fusion")


class SongListModel(QAbstractListModel):
    """Keep delegates and scroll position alive when only a rating changes."""
    SongRole = int(Qt.ItemDataRole.UserRole) + 1

    def __init__(self, parent=None):
        super().__init__(parent)
        self._songs = []
        self._batch_key = None

    def roleNames(self):
        return {self.SongRole: b"modelData"}

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._songs)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if index.isValid() and 0 <= index.row() < len(self._songs) and role == self.SongRole:
            return self._songs[index.row()]
        return None

    def sync(self, songs, batch_key):
        songs = [dict(song) for song in songs]
        ids = [song["track_id"] for song in songs]
        if self._batch_key == batch_key:
            # A history rating filter can remove the rated row. Remove only
            # those rows, preserving the other delegates and viewport anchor.
            wanted = set(ids)
            for row in range(len(self._songs) - 1, -1, -1):
                if self._songs[row]["track_id"] not in wanted:
                    self.beginRemoveRows(QModelIndex(), row, row)
                    self._songs.pop(row)
                    self.endRemoveRows()
            if [song["track_id"] for song in self._songs] == ids:
                for row, song in enumerate(songs):
                    if song != self._songs[row]:
                        self._songs[row] = song
                        self.dataChanged.emit(self.index(row), self.index(row), [self.SongRole])
                return
        self.beginResetModel()
        self._songs = songs
        self._batch_key = batch_key
        self.endResetModel()


class DesktopBridge(QObject):
    changed = Signal()
    profileChanged = Signal()
    _completed = Signal(str, object, str)

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="musicmatch")
        self._state = {"profiles": [], "profile_id": "personal", "profile_name": "Personal",
                       "favorites": [], "recommendations": [], "batch_id": "",
                       "counts": {}, "model_status": "Loading your local library", "message": ""}
        self._results = []
        self._history = []
        self._history_batch = {}
        self._busy = False
        self._error = ""
        self._closed = False
        self._initialized = False
        self._history_offset = 0
        self._history_rating = "all"
        self._history_has_older = False
        self._recommendation_model = SongListModel(self)
        self._history_recommendation_model = SongListModel(self)
        self._completed.connect(self._receive, Qt.ConnectionType.QueuedConnection)

    state = Property("QVariantMap", lambda self: self._state, notify=changed)
    searchResults = Property("QVariantList", lambda self: self._results, notify=changed)
    historyRows = Property("QVariantList", lambda self: self._history, notify=changed)
    historyBatch = Property("QVariantMap", lambda self: self._history_batch, notify=changed)
    busy = Property(bool, lambda self: self._busy, notify=changed)
    error = Property(str, lambda self: self._error, notify=changed)
    initialized = Property(bool, lambda self: self._initialized, notify=changed)
    recommendationModel = Property(QObject, lambda self: self._recommendation_model, constant=True)
    historyRecommendationModel = Property(QObject, lambda self: self._history_recommendation_model, constant=True)
    historyOffset = Property(int, lambda self: self._history_offset, notify=changed)
    historyHasOlder = Property(bool, lambda self: self._history_has_older, notify=changed)

    def _submit(self, kind, operation):
        if self._closed or self._busy:
            return
        self._busy, self._error = True, ""
        self.changed.emit()
        future = self.executor.submit(operation)

        def complete(done):
            try:
                result, error = done.result(), ""
            except Exception as exc:
                result, error = None, str(exc)
            if not self._closed:
                self._completed.emit(kind, result, error)

        future.add_done_callback(complete)

    @Slot(str, object, str)
    def _receive(self, kind, result, error):
        if self._closed:
            return
        self._busy, self._error = False, error
        if not error:
            if kind == "search":
                self._results = result
            elif kind == "history":
                self._history = result["rows"]
                self._history_offset = result["offset"]
                self._history_rating = result["rating"]
                self._history_has_older = result["has_older"]
                self._history_batch = {}
            elif kind == "history_batch":
                self._history_batch = result
            else:
                self._state = dict(result)
                self._history_batch = self._state.pop("_history_batch", self._history_batch)
                self._history = self._state.pop("_history_rows", self._history)
                self._history_has_older = self._state.pop("_history_has_older", self._history_has_older)
                if kind == "profile":
                    self._initialized = True
                    self._results, self._history, self._history_batch = [], [], {}
                    self._history_offset = 0
                    self._history_has_older = False
                    self._history_rating = "all"
                    self.profileChanged.emit()
        self._recommendation_model.sync(self._state.get("recommendations", []),
            (self._state.get("profile_id"), self._state.get("batch_id")))
        self._history_recommendation_model.sync(self._history_batch.get("recommendations", []),
            (self._state.get("profile_id"), self._history_batch.get("batch_id")))
        self.changed.emit()

    @Slot()
    def initialize(self):
        self._submit("profile", self.service.initialize)

    @Slot(str, str)
    def search(self, title, artist):
        self._submit("search", lambda: self.service.search(title, artist, True))

    @Slot(str)
    def addFavorite(self, track_id):
        self._submit("state", lambda: self.service.add_favorite(track_id))

    @Slot(str)
    def removeFavorite(self, track_id):
        self._submit("state", lambda: self.service.remove_favorite(track_id))

    @Slot(bool)
    def recommend(self, fresh):
        self._submit("state", lambda: self.service.recommend(fresh))

    @Slot(str, bool)
    def moreLikeThis(self, track_id, fresh=False):
        self._submit("state", lambda: self.service.more_like_this(track_id, fresh))

    @Slot(str, bool, str)
    def steerMoreLikeThis(self, track_id, fresh, steering):
        self._submit("state", lambda: self.service.more_like_this(track_id, fresh, steering=steering))

    @Slot(str, str)
    def chooseComparison(self, comparison_id, choice):
        self._submit("state", lambda: self.service.choose_comparison(comparison_id, choice))

    @Slot(str)
    def undoComparison(self, comparison_id):
        self._submit("state", lambda: self.service.undo_comparison(comparison_id))

    @Slot()
    def resetComparisons(self):
        self._submit("state", self.service.reset_comparisons)

    @Slot(str, str, bool, str)
    def rate(self, batch_id, track_id, liked, reason=""):
        history_id = self._history_batch.get("batch_id")
        history_rating = self._history_rating
        history_offset = self._history_offset

        def work():
            result = dict(self.service.rate(batch_id, track_id, liked, reason or None))
            if history_id:
                result["_history_batch"] = self.service.load_history(history_id, history_rating)
                page = self._history_page(history_rating, history_offset)
                result["_history_rows"] = page["rows"]
                result["_history_has_older"] = page["has_older"]
            return result

        self._submit("rating", work)

    @Slot(str)
    def switchProfile(self, profile_id):
        self._submit("profile", lambda: self.service.switch_profile(profile_id))

    @Slot()
    def resetTest(self):
        self._submit("profile", self.service.reset_test)

    @Slot(str, int)
    def loadHistory(self, rating="all", offset=0):
        if self._busy or self._closed:
            return
        offset = max(0, offset)
        self._submit("history", lambda: self._history_page(rating, offset))

    def _history_page(self, rating, offset):
        rows = self.service.list_history(rating, 31, offset)
        return {"rows": rows[:30], "has_older": len(rows) > 30, "rating": rating, "offset": offset}

    @Slot(str)
    def openHistory(self, batch_id):
        self._submit("history_batch", lambda: self.service.load_history(batch_id, self._history_rating))

    @Slot()
    def clearError(self):
        self._error = ""
        self.changed.emit()

    @Slot()
    def close(self):
        if self._closed:
            return
        self._closed = True
        close = getattr(self.service, "close", None)
        if close:
            self.executor.submit(close)
        self.executor.shutdown(wait=False)


def run(service=None):
    if service is None:
        from .application import ApplicationService
        service = ApplicationService()
    app = QGuiApplication.instance() or QGuiApplication(sys.argv)
    app.setApplicationName("MusicMatch")
    app.setOrganizationName("MusicMatch")
    app.styleHints().setColorScheme(Qt.ColorScheme.Dark)
    app.setWindowIcon(QIcon(str(Path(__file__).parent / "ui" / "musicmatch.svg")))
    engine = QQmlApplicationEngine()
    bridge = DesktopBridge(service)
    engine.rootContext().setContextProperty("music", bridge)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).parent / "ui" / "Main.qml")))
    if not engine.rootObjects():
        bridge.close()
        return 1
    app.aboutToQuit.connect(bridge.close)
    bridge.initialize()
    return app.exec()
