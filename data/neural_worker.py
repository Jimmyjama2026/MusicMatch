"""Isolated CPU training entry point; no catalog load and no personal DB access."""
import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    from .neural_learning import train_candidate
    train_candidate(payload["records"], args.output, payload["feature_manifest"],
                    time_budget_seconds=9)


if __name__ == "__main__":
    main()
