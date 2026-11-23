"""Entry point for the windowless Windows build used by Task Scheduler."""

import watcher


if __name__ == "__main__":
    raise SystemExit(watcher.main(["--scheduled"]))
