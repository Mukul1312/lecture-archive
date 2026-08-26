"""Thin command-line composition seam for Heritage Production."""

from __future__ import annotations

import argparse
from collections.abc import Sequence


COMMAND_GROUPS = (
    "production",
    "source",
    "proposal",
    "edition",
    "actor",
    "rubric",
    "policy",
    "gates",
    "review",
    "finding",
    "release",
    "authority",
    "operation",
    "integrity",
    "quarantine",
    "outbox",
    "backup",
    "restore",
)


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser without creating or opening a store."""
    parser = argparse.ArgumentParser(prog="heritage-production")
    parser.add_argument(
        "--store",
        default=".heritage-production",
        help="local store directory (used by future behaviour commands)",
    )
    parser.add_argument(
        "--operation-id",
        help="caller-supplied idempotency operation identifier",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="request machine-readable command output",
    )
    commands = parser.add_subparsers(dest="command", title="command groups")
    for command in COMMAND_GROUPS:
        commands.add_parser(command, help=f"{command} commands (not implemented yet)")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Parse CLI arguments; command behaviour is introduced in later tasks."""
    parser = build_parser()
    parser.parse_args(argv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
