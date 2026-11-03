"""Render the real Qt desktop using a disposable copy of the saved profile DB."""
import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, QTimer, QUrl, QMetaObject, Q_ARG
from PySide6.QtGui import QFontDatabase, QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from data.application import ApplicationService
from data.backend import FeedbackStore
from data.desktop_qt import DesktopBridge


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "data/sources/desktop_preview")
    parser.add_argument("--focus-first", action="store_true", help="Verify More like this on the first saved favorite")
    parser.add_argument("--steering", choices=("same", "slower", "faster", "energetic", "less_artist"), default="same")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    app = QGuiApplication([])
    for name in ("segoeui.ttf", "segoeuib.ttf"):
        path = Path("C:/Windows/Fonts") / name
        if path.exists():
            QFontDatabase.addApplicationFont(str(path))
    report = {"screenshots": [], "warnings": [], "database_writes": "temporary copy only"}
    with tempfile.TemporaryDirectory(dir=args.output) as temporary:
        target = Path(temporary) / "preview.sqlite3"
        source = ROOT / "data/feedback.sqlite3"
        if source.exists():
            with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as origin:
                with closing(sqlite3.connect(target)) as destination:
                    origin.backup(destination)
        service = ApplicationService(store=FeedbackStore(target))
        bridge = DesktopBridge(service)
        engine = QQmlApplicationEngine()
        engine.warnings.connect(lambda warnings: report["warnings"].extend(str(w) for w in warnings))
        engine.rootContext().setContextProperty("music", bridge)
        engine.load(QUrl.fromLocalFile(str(ROOT / "data/ui/Main.qml")))
        if not engine.rootObjects():
            bridge.close()
            bridge.executor.shutdown(wait=True)
            raise RuntimeError(report["warnings"])
        window = engine.rootObjects()[0]
        phase = "initialize"
        started = time.perf_counter()
        beats = []
        timer = QTimer()
        timer.setInterval(16)
        timer.timeout.connect(lambda: beats.append((phase, time.perf_counter())))
        timer.start()

        def capture(name, width, height, next_step):
            window.resize(width, height)
            def save():
                path = args.output / name
                if not window.grabWindow().save(str(path)):
                    report["warnings"].append("Screenshot failed: " + name)
                else:
                    report["screenshots"].append(str(path))
                next_step()
            QTimer.singleShot(250, save)

        def capture_details():
            window.setProperty("section", 0)
            if bridge.state["recommendations"]:
                QMetaObject.invokeMethod(window, "showDetails",
                    Q_ARG("QVariant", bridge.state["recommendations"][0]))
            capture("match_detail.png", 1200, 840, finish)

        def capture_map():
            window.setProperty("section", 3)
            capture("neighborhoods.png", 1200, 840,
                lambda: capture("neighborhoods_narrow.png", 560, 760, capture_details))

        def capture_comparison():
            window.setProperty("section", 0)
            panel = window.findChild(QObject, "comparisonPanel")
            if panel:
                panel.setProperty("expanded", True)
            capture("comparison.png", 1200, 840, capture_map)

        def finish():
            timer.stop()
            gaps = sorted((b[1]-a[1])*1000 for a,b in zip(beats, beats[1:]))
            report["event_loop_timer_ms"] = {"samples": len(gaps), "max": max(gaps, default=0),
                "p95": gaps[int(.95*(len(gaps)-1))] if gaps else 0}
            report["event_loop_by_phase_ms"] = {}
            for label in ("initialize", "recommend", "capture"):
                values = sorted((b[1]-a[1])*1000 for a,b in zip(beats, beats[1:]) if a[0] == b[0] == label)
                report["event_loop_by_phase_ms"][label] = {
                    "samples": len(values), "max": max(values, default=0),
                    "p95": values[int(.95*(len(values)-1))] if values else 0}
            window.close()
            bridge.close()
            app.quit()

        def changed():
            nonlocal phase
            if bridge.error:
                report["warnings"].append(bridge.error)
                phase = "failed"
                finish()
            elif phase == "initialize" and bridge.initialized and not bridge.busy:
                report["initialize_seconds"] = time.perf_counter()-started
                phase = "recommend"
                report["recommend_started"] = time.perf_counter()
                if bridge.state["favorites"]:
                    if args.focus_first:
                        bridge.steerMoreLikeThis(bridge.state["favorites"][0]["track_id"], False, args.steering)
                    else:
                        bridge.recommend(False)
                else:
                    phase = "capture"
                    capture("wide.png", 1200, 840, lambda: capture("narrow.png", 560, 760, capture_comparison))
            elif phase == "recommend" and not bridge.busy:
                report["recommend_ms"] = (time.perf_counter()-report.pop("recommend_started"))*1000
                report["recommendation_count"] = len(bridge.state["recommendations"])
                recommendations = bridge.state["recommendations"]
                report["favorite_count"] = len(bridge.state["favorites"])
                report["saved_recommendation_payload_bytes"] = len(json.dumps(recommendations).encode("utf-8"))
                report["discovery"] = recommendations[0].get("selection_context", {}) if recommendations else {}
                report["map_points"] = len(bridge.state.get("neighborhood_view", {}).get("points", []))
                report["comparison_offered"] = bool(bridge.state.get("comparison"))
                report["steering"] = recommendations[0].get("steering_context") if recommendations else None
                report["title_languages"] = [s.get("title_language") for s in recommendations]
                phase = "capture"
                capture("wide.png", 1200, 840, lambda: capture("narrow.png", 560, 760, capture_comparison))

        bridge.changed.connect(changed)
        QTimer.singleShot(30000, finish)
        bridge.initialize()
        app.exec()
        bridge.executor.shutdown(wait=True)
        engine.deleteLater()
        app.processEvents()
    report["limitations"] = "Offscreen render/event-loop smoke check; not physical-monitor FPS certification."
    (args.output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
