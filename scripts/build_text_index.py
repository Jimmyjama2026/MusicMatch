"""Build a separate licensed MulJam experiment; no UI changes or audio requests."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from data.text_similarity import TextIndex, corpus_hash

COMMIT = "0b66527ed2f7ade13944b43364de403f8d99e638"
BASE = f"https://raw.githubusercontent.com/zhuole1025/LyricWhiz/{COMMIT}/"
FILES = {"train.meta": 12405834, "valid.meta": 294075, "test.meta": 180209}
TRANSFER_CAP = 15_000_000
DISK_CAP = 50_000_000


def parse_records(paths):
    songs = {}
    for path in paths:
        with Path(path).open(encoding="utf-8", newline="") as handle:
            # Some transcribed lines contain unquoted commas: split the first five fields only.
            header = handle.readline().strip()
            if header != "id,file,lang,start,end,wrd":
                raise ValueError(f"Unexpected metadata header in {path}")
            for line in handle:
                fields = line.rstrip("\r\n").split(",", 5)
                if len(fields) != 6:
                    raise ValueError(f"Malformed metadata row in {path}")
                ident, filename, lang, start, end, words = fields
                song_id = ident.rsplit("_", 1)[0]
                key = (song_id, lang)
                song = songs.setdefault(key, {"id": "jamendo:" + song_id, "language": lang, "segments": {}})
                segment = (float(start), float(end))
                old = song["segments"].get(segment)
                if old is not None and old != words:
                    raise ValueError("Conflicting duplicate lyric segment")
                song["segments"][segment] = words
    return [{"id": song["id"], "language": song["language"],
             "text": "\n".join(words for _, words in sorted(song["segments"].items()))}
            for song in songs.values()]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true", help="Fetch pinned text only, max 15 MB cumulative payload")
    parser.add_argument("--root", type=Path, default=Path("data/sources/muljam_text"))
    args = parser.parse_args()
    args.root.mkdir(parents=True, exist_ok=True)
    lock_path = args.root / ".build.lock"
    try:
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise RuntimeError("Experiment already running, or stale .build.lock; remove stale lock only after confirming no build is active") from exc
    try:
        os.write(lock_fd, str(os.getpid()).encode("ascii"))
        _run(args)
    finally:
        os.close(lock_fd)
        lock_path.unlink(missing_ok=True)


def _run(args):
    ledger_path = args.root / "download_ledger.json"
    ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else {"response_bytes": 0, "files": {}}
    ledger.setdefault("reserved_response_bytes", ledger["response_bytes"])

    def check_sources():
        for name, expected in FILES.items():
            target = args.root / name
            if target.exists():
                entry = ledger["files"].get(name)
                if (target.stat().st_size != expected or not entry
                        or hashlib.sha256(target.read_bytes()).hexdigest() != entry["sha256"]):
                    raise ValueError(f"Unverified or modified cached source: {name}")

    def check_disk():
        if sum(p.stat().st_size for p in args.root.rglob("*") if p.is_file()) > DISK_CAP:
            raise ValueError("Experiment exceeds its 50 MB disk allowance")

    check_disk()
    check_sources()
    if args.download:
        for name, expected in FILES.items():
            target = args.root / name
            if target.exists():
                continue
            if ledger["reserved_response_bytes"] + expected + 1 > TRANSFER_CAP:
                raise ValueError("Cumulative download budget exhausted")
            # Persist a whole-response reservation before opening the connection.
            # A killed process cannot silently reset transfer accounting.
            ledger["reserved_response_bytes"] += expected + 1
            ledger_path.write_text(json.dumps(ledger, indent=2), encoding="utf-8")
            url = BASE + "MulJam_v2.0/preconstructed-split/" + name
            temporary = target.with_suffix(".partial")
            received = 0
            try:
                request = urllib.request.Request(url, headers={"User-Agent": "MusicMatch-personal-research/1.0"})
                with urllib.request.urlopen(request, timeout=45) as response, temporary.open("wb") as output:
                    while True:
                        chunk = response.read(min(65536, expected - received + 1))
                        if not chunk:
                            break
                        received += len(chunk)
                        ledger["response_bytes"] += len(chunk)
                        ledger_path.write_text(json.dumps(ledger, indent=2), encoding="utf-8")
                        if received > expected or ledger["response_bytes"] > TRANSFER_CAP:
                            raise ValueError("Source or cumulative transfer exceeds budget")
                        output.write(chunk)
                if received != expected:
                    raise ValueError("Incomplete source download")
                temporary.replace(target)
                ledger["files"][name] = {"bytes": received, "sha256": hashlib.sha256(target.read_bytes()).hexdigest(), "url": url}
            finally:
                temporary.unlink(missing_ok=True)
                ledger_path.write_text(json.dumps(ledger, indent=2), encoding="utf-8")
    check_sources()
    records = parse_records([args.root / name for name in FILES])
    digest = corpus_hash(records)
    index_path = args.root / ("index-" + digest[:16])
    if index_path.exists():
        index = TextIndex.load(index_path, digest)
    else:
        index = TextIndex.build(records)
        index.save(index_path)
    check_disk()
    timings = []
    for group in index.groups.values():
        for song_id in group[2][:10]:
            start = time.perf_counter()
            index.neighbors(song_id, 10)
            timings.append((time.perf_counter() - start) * 1000)
    counts = {lang: len(group[2]) for lang, group in index.groups.items()}
    report = {"commit": COMMIT, "source": BASE, "license": "CC BY-NC-SA (numeric version not specified in paper)",
              "license_evidence": "https://arxiv.org/html/2306.17103v2", "corpus_sha256": digest,
              "song_count": len(records), "language_counts": counts,
              "response_bytes": ledger["response_bytes"],
              "reserved_response_bytes": ledger["reserved_response_bytes"],
              "query_timings_ms": {"queries": len(timings), "mean": sum(timings) / len(timings), "max": max(timings)},
              "retained_bytes": sum(p.stat().st_size for p in args.root.rglob("*") if p.is_file()),
              "sample_neighbors": {lang: {"query": group[2][0], "neighbors": index.neighbors(group[2][0], 3)}
                                   for lang, group in index.groups.items()},
              "limitations": "Lexical sanity check only; not validated theme accuracy or personal recommendation improvement. No mainstream artist overlap established."}
    (args.root / "experiment_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    report["retained_bytes"] = sum(p.stat().st_size for p in args.root.rglob("*") if p.is_file())
    (args.root / "experiment_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    check_disk()
    print(json.dumps({key: value for key, value in report.items() if key != "sample_neighbors"}, indent=2))


if __name__ == "__main__":
    main()
