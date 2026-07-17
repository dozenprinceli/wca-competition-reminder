from __future__ import annotations

import argparse
import sqlite3
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from wca_competition_reminder.config import ConfigurationError, load_config
from wca_competition_reminder.locking import AlreadyRunningError, ProcessLock
from wca_competition_reminder.state import StateError, StateStore

CONFIRMATION_WORD = "CLEAR"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Clear all WCA competition reminder database state.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config.toml"),
        help="TOML configuration path (default: ./config.toml)",
    )
    parser.add_argument("--state", type=Path, help="override the SQLite state path")
    parser.add_argument("--lock", type=Path, help="override the process lock path")
    return parser


def _print_error(message: str) -> None:
    print(message, file=sys.stderr)


def _confirm(
    state_path: Path,
    *,
    input_func: Callable[[str], str],
    output: Callable[[str], None],
) -> bool:
    output(f"WARNING: all reminder state in {state_path} will be permanently cleared.")
    try:
        response = input_func(f'Type "{CONFIRMATION_WORD}" to continue: ')
    except (EOFError, KeyboardInterrupt):
        output("Database clear cancelled; no data was changed.")
        return False
    if response != CONFIRMATION_WORD:
        output("Database clear cancelled; no data was changed.")
        return False
    return True


def main(
    argv: Sequence[str] | None = None,
    *,
    input_func: Callable[[str], str] = input,
    output: Callable[[str], None] = print,
    error_output: Callable[[str], None] = _print_error,
) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        config = load_config(arguments.config)
    except ConfigurationError as exc:
        error_output(f"Cannot load configuration: {exc}")
        return 1

    state_path = arguments.state.resolve() if arguments.state else config.state_path
    lock_path = arguments.lock.resolve() if arguments.lock else config.lock_path
    if not state_path.exists():
        output(f"Database does not exist; nothing to clear: {state_path}")
        return 0
    if not _confirm(state_path, input_func=input_func, output=output):
        return 0

    try:
        with ProcessLock(lock_path):
            if not state_path.exists():
                output(f"Database no longer exists; nothing to clear: {state_path}")
                return 0
            with StateStore(state_path) as state:
                removed = state.clear_all()
    except (AlreadyRunningError, StateError, sqlite3.Error, OSError) as exc:
        error_output(f"Cannot clear database: {exc}")
        return 1

    output(
        "Database cleared: "
        f"competitions={removed['competitions']} deliveries={removed['deliveries']}"
    )
    output("The next poll will create a new silent baseline.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
