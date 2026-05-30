# -*- coding: utf-8 -*-
from __future__ import annotations

import subprocess
import sys


COMMANDS = [
    [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
    [
        sys.executable,
        "-m",
        "pyflakes",
        "listener.py",
        "uploader.py",
        "web_server.py",
        "config.py",
        "core",
        "services",
        "tui",
        "tests",
    ],
    [
        sys.executable,
        "-m",
        "compileall",
        "-q",
        "-x",
        r"\\.git|venv|downloads|logs|scratch|__pycache__",
        ".",
    ],
]


def main() -> int:
    for cmd in COMMANDS:
        print(">", " ".join(cmd))
        result = subprocess.run(cmd)
        if result.returncode != 0:
            return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
