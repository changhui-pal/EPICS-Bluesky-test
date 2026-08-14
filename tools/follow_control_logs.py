#!/usr/bin/env python3
"""Merge growing control logs into a timestamped live session stream."""

from __future__ import annotations

import argparse
import datetime
import pathlib
import signal
import sys
import time


def timestamp() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="milliseconds")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", required=True, type=pathlib.Path)
    parser.add_argument(
        "--source", action="append", required=True, metavar="NAME=FILE"
    )
    arguments = parser.parse_args()
    sources: list[tuple[str, pathlib.Path, int]] = []
    for specification in arguments.source:
        name, separator, filename = specification.partition("=")
        if not separator or not name or not filename:
            parser.error("--source must use NAME=FILE")
        sources.append((name, pathlib.Path(filename), 0))

    stopping = False

    def request_stop(_signum, _frame) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, request_stop)
    # Ctrl-C belongs to the launcher, which first shuts down GUI and IOC and
    # then sends this follower SIGTERM after their final log lines are written.
    signal.signal(signal.SIGINT, signal.SIG_IGN)

    with arguments.session.open("a", encoding="utf-8", buffering=1) as session:
        while True:
            emitted = False
            updated = []
            for name, path, offset in sources:
                try:
                    size = path.stat().st_size
                    if size < offset:
                        offset = 0
                    with path.open("r", encoding="utf-8", errors="replace") as stream:
                        stream.seek(offset)
                        for raw_line in stream:
                            line = raw_line.rstrip("\r\n")
                            rendered = f"{timestamp()} [{name}] {line}\n"
                            sys.stdout.write(rendered)
                            sys.stdout.flush()
                            session.write(rendered)
                            emitted = True
                        offset = stream.tell()
                except FileNotFoundError:
                    pass
                updated.append((name, path, offset))
            sources = updated
            if stopping and not emitted:
                break
            if not emitted:
                time.sleep(0.1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
