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
if sys.platform == "win32":
    VENV_PY = BASE / "venv" / "Scripts" / "python.exe"
else:
    VENV_PY = BASE / "venv" / "bin" / "python"
REQUIREMENTS = BASE / "requirements.txt"


def ensure_venv() -> None:
    if VENV_PY.exists():
        return
    print("[SETUP] Creating virtual environment (venv)...")
    try:
        subprocess.run([sys.executable, "-m", "venv", "venv"], check=True, cwd=BASE)
        print("[SETUP] Installing dependencies from requirements.txt...")
        subprocess.run([str(VENV_PY), "-m", "pip", "install", "--upgrade", "pip"], check=True, cwd=BASE)
        subprocess.run([str(VENV_PY), "-m", "pip", "install", "-r", str(REQUIREMENTS)], check=True, cwd=BASE)
        print("[OK] Environment setup complete.")
    except Exception as e:
        print(f"\n[ERROR] Failed to set up virtual environment: {e}")
        print("Please ensure Python is installed and you have internet access.")
        sys.exit(1)


def update_dependencies() -> None:
    print("[SETUP] Updating/Verifying dependencies...")
    try:
        subprocess.run([str(VENV_PY), "-m", "pip", "install", "--upgrade", "pip"], check=True, cwd=BASE)
        subprocess.run([str(VENV_PY), "-m", "pip", "install", "-U", "-r", str(REQUIREMENTS)], check=True, cwd=BASE)
        print("[OK] Dependencies are up to date.")
    except Exception as e:
        print(f"\n[ERROR] Failed to update dependencies: {e}")


def menu() -> str:
    print("=" * 40)
    print("  Telegram DL Guard v3.9")
    print("=" * 40)
    print()
    print("  1  Run DL Guard (Interactive TUI)")
    print("  2  Setup Wizard (Initial Login)")
    print("  3  Start Headless Daemon")
    print("  4  Update/Verify Dependencies")
    print()
    print("  0  Exit")
    print()
    return input("> ").strip()


def run_action(choice: str) -> bool:
    """Runs the selected action. Returns True if we should pause after execution."""
    actions = {
        "1": ["tui.py"],
        "2": ["guard.py", "--setup"],
        "3": ["guard.py", "--listen"],
    }
    
    if choice == "4":
        update_dependencies()
        return True

    if choice not in actions:
        return False

    script = actions[choice]
    cmd = [str(VENV_PY), "-u"] + script
    
    # Ensure stdout/stderr are unbuffered
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    
    try:
        subprocess.run(cmd, cwd=BASE, env=env)
    except KeyboardInterrupt:
        pass
        
    return choice in ("2", "3")


def main() -> None:
    ensure_venv()

    # Handle command-line arguments to bypass menu
    if len(sys.argv) > 1:
        arg = sys.argv[1].strip().lower()
        alias = {
            "1": "1", "tui": "1", "--tui": "1",
            "2": "2", "setup": "2", "--setup": "2",
            "3": "3", "listen": "3", "--listen": "3",
            "4": "4", "update": "4", "--update": "4",
        }
        choice = alias.get(arg)
        if choice:
            should_pause = run_action(choice)
            if should_pause:
                input("\nPress Enter to continue...")
            return
        else:
            print(f"Unknown argument: {sys.argv[1]}")
            print("Usage: python run.py [1|2|3|4|tui|setup|listen|update]")
            sys.exit(1)

    while True:
        choice = menu()
        if choice == "0":
            break
        
        should_pause = run_action(choice)
        if should_pause:
            input("\nPress Enter to continue...")


if __name__ == "__main__":
    main()

