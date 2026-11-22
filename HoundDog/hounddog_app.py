"""Entry point for the Windows executable."""

import sys

import watcher
import watcher_server


def main() -> int:
    args = sys.argv[1:]
    if args and args[0] == "watch":
        return watcher.main(args[1:])
    return watcher_server.main(args, open_browser=True)


if __name__ == "__main__":
    raise SystemExit(main())
