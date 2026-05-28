# -*- coding: utf-8 -*-
"""
Launch script — run from terminal: python run.py
Falls back to run.bat if python not available.
"""
from __future__ import annotations

import os
import sys
import subprocess
from pathlib import Path

BASE = Path(__file__).parent
VENV_PY = BASE / "venv" / "Scripts" / "python.exe"
REQUIREMENTS = BASE / "requirements.txt"


def ensure_venv() -> None:
    if VENV_PY.exists():
        return
    print("[SETUP] Creating venv...")
    subprocess.run([sys.executable, "-m", "venv", "venv"], check=True, cwd=BASE)
    subprocess.run([str(VENV_PY), "-m", "pip", "install", "-r", str(REQUIREMENTS)], check=True, cwd=BASE)
    print("[OK]")


def menu() -> str:
    print("=" * 40)
    print("  Telegram DL Guard v3.9")
    print("=" * 40)
    print()
    print("  1  Start listener")
    print("  2  Interactive TUI")
    print("  3  Setup wizard")
    print("  4  Settings")
    print()
    print("  0  Exit")
    print()
    return input("> ").strip()


def main() -> None:
    ensure_venv()

    actions = {
        "1": ["guard.py", "--listen"],
        "2": ["tui.py"],
        "3": ["guard.py", "--setup"],
        "4": ["guard.py"],
    }

    while True:
        choice = menu()
        if choice == "0":
            break
        if choice not in actions:
            continue

        script = actions[choice]
        cmd = [str(VENV_PY), "-u"] + script
        try:
            subprocess.run(cmd, cwd=BASE)
        except KeyboardInterrupt:
            pass

        if choice in ("3", "4"):
            input("\nPress Enter to continue...")


if __name__ == "__main__":
    main()
