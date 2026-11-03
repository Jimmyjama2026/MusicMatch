"""Launch the modern desktop; --legacy keeps the earlier Tk interface available."""
import argparse


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--legacy", action="store_true", help="Open the classic Tk interface")
    args = parser.parse_args()
    if args.legacy:
        from data.main import main as classic
        return classic()
    try:
        from data.desktop_qt import run
    except ImportError:
        print("Qt desktop dependency is unavailable; opening the classic interface. Install requirements.txt to enable the new desktop.")
        from data.main import main as classic
        return classic()
    return run()

if __name__ == "__main__":
    raise SystemExit(main())
