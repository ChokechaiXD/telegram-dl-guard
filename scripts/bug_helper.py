# -*- coding: utf-8 -*-
"""
Developer Bug Diagnostic Assistant for Telegram DL Guard.
Implements the 10 software testing prompts directly against the project log files and database state.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent
LOGS_DIR = BASE_DIR / "logs"
GUARD_LOG = LOGS_DIR / "guard.log"
TUI_LOG = LOGS_DIR / "tui_debug.log"

# Dictionary mapping common errors in this project to root causes, explanations, and investigation steps.
PROJECT_ERROR_MAP: dict[str, dict[str, str]] = {
    "FloodWaitError": {
        "severity": "high",
        "explanation": "Telegram is rate-limiting the account because too many requests (such as forwards or downloads) were sent in a short timeframe.",
        "root_cause": "The account exceeded Telegram's API spam limits. This commonly happens during direct forwarding mode or history scans.",
        "steps": (
            "1. Check if the newly implemented FORWARD_LOCK cooldown is enabled.\n"
            "2. Increase the delay between API calls or reduce the number of concurrent worker threads in config.yaml.\n"
            "3. Wait for the required duration specified in the error message before restarting."
        )
    },
    "AuthKeyDuplicatedError": {
        "severity": "critical",
        "explanation": "The active Telegram session has been terminated or logged in elsewhere, invalidating the current session file.",
        "root_cause": "The same session string or file is being used concurrently by another client instance, or was deleted from Telegram's active sessions.",
        "steps": (
            "1. Stop all running instances of the guard immediately.\n"
            "2. Run the Setup Wizard ('python run.py 2') to generate a fresh authorization session.\n"
            "3. Update the SESSION_STRING environment variable in your .env file."
        )
    },
    "database is locked": {
        "severity": "critical",
        "explanation": "SQLite database is experiencing write collisions because multiple processes or threads are attempting to write concurrently.",
        "root_cause": "Background uploader threads, history scanner, web server, and TUI are competing for SQLite write locks without proper locking.",
        "steps": (
            "1. Ensure the global '_db_lock' in core/state.py is acquired before any write operation.\n"
            "2. Verify that long-running operations inside the lock are offloaded to worker threads via asyncio.to_thread.\n"
            "3. Increase the SQLite connection timeout to allow queueing of write operations."
        )
    },
    "ConnectionError": {
        "severity": "high",
        "explanation": "The script cannot establish or maintain a connection to Telegram's gateway servers.",
        "root_cause": "Local network outage, proxy misconfiguration, firewall block, or temporary Telegram server issues.",
        "steps": (
            "1. Test connection to api.telegram.org from the local terminal.\n"
            "2. Verify proxy settings in config.yaml if you are behind a corporate firewall.\n"
            "3. Check logs to see if auto-reconnect logic triggered connect_retry."
        )
    },
    "FileNotFoundError": {
        "severity": "medium",
        "explanation": "A required database file or media download file is missing.",
        "root_cause": "The cleanup sweeper deleted a local file, or a manual file target path is invalid/unwritable.",
        "steps": (
            "1. Check if the file path exists and has appropriate read/write permissions.\n"
            "2. Review core/cleanup.py logs to verify if the file was caught in the expiration sweep.\n"
            "3. Ensure target directories are verified or created using _ensure_dir()."
        )
    }
}


def read_last_errors(filepath: Path, count: int = 3) -> list[dict[str, Any]]:
    """Scans log file and extracts the last few traceback blocks or ERROR entries."""
    if not filepath.exists():
        return []

    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()

    errors = []
    current_block = []
    in_traceback = False

    # Traverse backwards to find tracebacks and errors quickly
    for line in reversed(lines):
        line_str = line.strip()
        if "Traceback (most recent call last):" in line_str:
            in_traceback = False
            current_block.insert(0, line_str)
            tb_text = "\n".join(current_block)
            
            # Extract exception name
            match = re.search(r"(\w+Error|Exception):\s*(.*)", tb_text)
            err_type = match.group(1) if match else "Exception"
            err_msg = match.group(2) if match else "Unknown traceback exception"
            
            errors.append({
                "type": err_type,
                "message": err_msg,
                "raw": tb_text,
                "file": filepath.name
            })
            current_block = []
            if len(errors) >= count:
                break
        elif in_traceback:
            current_block.insert(0, line_str)
        elif "ERROR" in line_str or "CRITICAL" in line_str or "Exception" in line_str:
            # Check if this line starts a traceback block above it
            in_traceback = True
            current_block = [line_str]
            # If not a traceback line but a raw error line
            if len(lines) > lines.index(line) + 1 and "File \"" not in lines[lines.index(line) + 1]:
                # Single line error
                errors.append({
                    "type": "LogError",
                    "message": line_str,
                    "raw": line_str,
                    "file": filepath.name
                })
                in_traceback = False
                current_block = []
                if len(errors) >= count:
                    break

    return errors


def get_diagnostics(err_type: str, raw_msg: str) -> dict[str, str]:
    """Finds matching diagnostics for the given error type/message."""
    for key, data in PROJECT_ERROR_MAP.items():
        if key in err_type or key in raw_msg:
            return data
    return {
        "severity": "medium",
        "explanation": "An unexpected error occurred during execution.",
        "root_cause": "Undocumented error trace. Check variable states, network status, or third-party library boundaries.",
        "steps": "1. Search project repository issues for similar traces.\n2. Add logging around the failing function to capture local variable states.\n3. Verify if input parameters match expected type structures."
    }


def menu() -> None:
    print("=" * 60)
    print("  Telegram DL Guard — Interactive Developer Bug Assistant")
    print("=" * 60)
    print()
    print("  1  Diagnose Latest Logs (Analyze guard.log)")
    print("  2  Diagnose TUI Logs (Analyze tui_debug.log)")
    print("  3  Manual Error Lookup & Explanation")
    print("  4  Draft Bug Report / Information Request Comment")
    print("  5  Generate Copy-Paste Prompts for LLM (ChatGPT/Claude)")
    print()
    print("  0  Exit")
    print()


def show_diagnostics(err: dict[str, Any]) -> None:
    diag = get_diagnostics(err["type"], err["raw"])
    print("-" * 60)
    print(f"Error Source:  {err['file']}")
    print(f"Exception Type: {err['type']}")
    print(f"Message:       {err['message']}")
    print("-" * 60)
    print(f"[Prompt 1] Severity Classification: {diag['severity'].upper()}")
    print()
    print("[Prompt 7] Explanation in Plain Language:")
    print(f"  {diag['explanation']}")
    print()
    print("[Prompt 2] Likely Root Cause:")
    print(f"  {diag['root_cause']}")
    print()
    print("[Prompt 8] Recommended Investigation & Resolution Steps:")
    for line in diag["steps"].split("\n"):
        print(f"  {line}")
    print()
    print("Raw Stack Trace:")
    print(err["raw"])
    print("-" * 60)


def main() -> None:
    while True:
        menu()
        choice = input("> ").strip()
        if choice == "0":
            break
        elif choice == "1":
            print("\nScanning logs/guard.log for errors...")
            errors = read_last_errors(GUARD_LOG)
            if not errors:
                print("No active errors or tracebacks found in guard.log.")
            else:
                print(f"Found {len(errors)} recent errors. Showing latest:")
                show_diagnostics(errors[0])
            input("\nPress Enter to continue...")
        elif choice == "2":
            print("\nScanning logs/tui_debug.log for errors...")
            errors = read_last_errors(TUI_LOG)
            if not errors:
                print("No active errors or tracebacks found in tui_debug.log.")
            else:
                print(f"Found {len(errors)} recent errors. Showing latest:")
                show_diagnostics(errors[0])
            input("\nPress Enter to continue...")
        elif choice == "3":
            print("\n--- Manual Error Lookup ---")
            err_query = input("Enter error keyword or exception name: ").strip()
            if not err_query:
                continue
            diag = get_diagnostics(err_query, err_query)
            print("-" * 60)
            print(f"Manual Diagnostic for: {err_query}")
            print("-" * 60)
            print(f"Severity:     {diag['severity'].upper()}")
            print(f"Explanation:  {diag['explanation']}")
            print(f"Root Cause:   {diag['root_cause']}")
            print(f"Resolutions:\n{diag['steps']}")
            print("-" * 60)
            input("\nPress Enter to continue...")
        elif choice == "4":
            print("\n--- Draft Information Request (Prompt 10) ---")
            print("Generate a customized response asking the reporter for critical logs.")
            print()
            reporter = input("Enter reporter name (default: User): ").strip() or "User"
            err_type = input("Enter reported issue category (e.g. video playback, TUI hang): ").strip()
            comment = (
                f"Hi @{reporter},\n\n"
                f"Thank you for reporting this issue regarding {err_type or 'the system behavior'}.\n\n"
                f"To help us isolate the component and verify the root cause, "
                f"could you please provide the following details:\n"
                f"1. The latest execution logs from your 'logs/guard.log' or 'logs/tui_debug.log' folder.\n"
                f"2. Your system configuration (processing mode, database sizes from your dashboard).\n"
                f"3. A brief description of the steps taken right before the failure occurred.\n\n"
                f"We will review your logs against our database locks and API throttling layers immediately. Thanks!"
            )
            print("-" * 60)
            print(comment)
            print("-" * 60)
            input("\nPress Enter to continue...")
        elif choice == "5":
            print("\n--- Generate Prompts for LLM (Prompts 1-10 Template) ---")
            print("Select a prompt template to copy-paste directly to ChatGPT or Claude:")
            print("  1. Classify severity of local logs")
            print("  2. Suggest root cause of last exception")
            print("  3. Suggest minimal reproduction code")
            print()
            p_choice = input("Prompt select (1-3): ").strip()
            
            errors = read_last_errors(GUARD_LOG)
            err_text = errors[0]["raw"] if errors else "database is locked (caused by write transaction)"
            
            if p_choice == "1":
                print("\n[Copy-Paste Prompt]:")
                print("-" * 60)
                print(f"Classify this bug report by severity: critical, high, medium, or low.\n\nError Context:\n{err_text}")
                print("-" * 60)
            elif p_choice == "2":
                print("\n[Copy-Paste Prompt]:")
                print("-" * 60)
                print(f"Suggest the most likely root cause of this error based on the stack trace.\n\nStack Trace:\n{err_text}")
                print("-" * 60)
            elif p_choice == "3":
                print("\n[Copy-Paste Prompt]:")
                print("-" * 60)
                print(f"Suggest a minimal reproduction case for this reported issue.\n\nException Details:\n{err_text}")
                print("-" * 60)
            
            input("\nPress Enter to continue...")


if __name__ == "__main__":
    main()
