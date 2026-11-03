"""Build a local vector index from the existing CSV; no network or model download."""
import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from data.backend import MusicRecommender
from data.song_vectors import SongVectors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=Path("data/dataset.csv"))
    parser.add_argument("--output", type=Path, default=Path("data/vectors"))
    args = parser.parse_args()
    started = time.perf_counter()
    table = MusicRecommender(args.dataset).table
    vectors = SongVectors.build(table)
    vectors.save(args.output)
    SongVectors.load(args.output, table=table)
    report = dict(vectors.metadata)
    report.update(matrix_bytes=vectors.matrix.nbytes, validity_bytes=vectors.validity.nbytes,
                  retained_bytes=sum(path.stat().st_size for path in args.output.rglob("*") if path.is_file()),
                  elapsed_seconds=round(time.perf_counter() - started, 3),
                  csv_modified=False, downloaded_bytes=0)
    (args.output / "build_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
