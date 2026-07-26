#!/usr/bin/env python3
"""Validate project commit messages.

The policy is intentionally small and local: Conventional Commits for humans
and release tooling, plus a few project-specific guardrails against vague
history.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ALLOWED_TYPES = {
    "build",
    "chore",
    "ci",
    "docs",
    "feat",
    "fix",
    "ops",
    "perf",
    "refactor",
    "revert",
    "security",
    "style",
    "test",
}

HEADER_RE = re.compile(
    r"^(?P<type>[a-z]+)(?:\((?P<scope>[a-z0-9][a-z0-9._/-]{0,31})\))?(?P<breaking>!)?: (?P<description>\S.*)$"
)
GENERATED_PREFIXES = (
    "Merge ",
    "Revert ",
    "fixup! ",
    "squash! ",
    "amend! ",
)
VAGUE_DESCRIPTIONS = {
    "change",
    "changes",
    "misc",
    "more changes",
    "stuff",
    "update",
    "update stuff",
    "updates",
    "wip",
    "work in progress",
}
MAX_HEADER_LEN = 72
ZERO_SHA = "0" * 40


def _message_lines(message: str) -> list[str]:
    return [line.rstrip() for line in message.splitlines() if not line.startswith("#")]


def _header_from_message(message: str) -> str:
    for line in _message_lines(message):
        if line.strip():
            return line.strip()
    return ""


def validate_message(message: str) -> list[str]:
    header = _header_from_message(message)
    if not header:
        return ["Commit message is empty."]

    if header.startswith(GENERATED_PREFIXES):
        return []

    errors: list[str] = []
    if len(header) > MAX_HEADER_LEN:
        errors.append(f"Subject must be {MAX_HEADER_LEN} characters or fewer.")

    match = HEADER_RE.match(header)
    if match is None:
        errors.append(
            "Expected format: <type>[optional scope][!]: <description> "
            + "(example: fix(data): filter future crypto market windows)."
        )
        return errors

    commit_type = match.group("type")
    description = match.group("description")

    if commit_type not in ALLOWED_TYPES:
        errors.append("Type must be one of: " + ", ".join(sorted(ALLOWED_TYPES)) + ".")

    description_key = re.sub(r"[.!?]+$", "", description.lower()).strip()
    if description_key in VAGUE_DESCRIPTIONS:
        errors.append("Description is too vague; name the concrete change.")

    if description.endswith("."):
        errors.append("Description must not end with a period.")

    if description[:1].isupper():
        errors.append("Description must start lowercase after the type prefix.")

    return errors


def _read_commit_messages_from_range(commit_range: str) -> list[str]:
    result = subprocess.run(
        ["git", "log", "--format=%B%x00", commit_range],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            result.stderr.strip() or f"git log failed for {commit_range}"
        )
    return [message for message in result.stdout.split("\0") if message.strip()]


def _resolve_push_range(head: str, before: str, default_branch: str) -> str:
    if before != ZERO_SHA:
        return f"{before}..{head}"

    result = subprocess.run(
        ["git", "merge-base", default_branch, head],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            result.stderr.strip()
            or f"git merge-base failed for {default_branch} and {head}"
        )
    return f"{result.stdout.strip()}..{head}"


def _validate_named_messages(named_messages: list[tuple[str, str]]) -> int:
    failed = False
    for name, message in named_messages:
        errors = validate_message(message)
        if errors:
            failed = True
            print(f"{name}: invalid commit message", file=sys.stderr)
            for error in errors:
                print(f"  - {error}", file=sys.stderr)
            print(
                "  Allowed types: " + ", ".join(sorted(ALLOWED_TYPES)),
                file=sys.stderr,
            )
    return 1 if failed else 0


class Args(argparse.Namespace):
    message_files: list[Path]
    commit_range: str | None
    head: str | None
    before: str | None
    default_branch: str | None

    def __init__(self) -> None:
        super().__init__()
        self.message_files = []
        self.commit_range = None
        self.head = None
        self.before = None
        self.default_branch = None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument("message_files", nargs="*", type=Path)
    _ = parser.add_argument("--range", dest="commit_range")
    _ = parser.add_argument("--head")
    _ = parser.add_argument("--before")
    _ = parser.add_argument("--default-branch")
    args = parser.parse_args(argv, namespace=Args())

    if args.commit_range and args.head:
        parser.error("--range and --head are mutually exclusive")
    if args.head and (args.before is None or args.default_branch is None):
        parser.error("--head requires --before and --default-branch")

    try:
        named_messages: list[tuple[str, str]] = []
        commit_range = args.commit_range
        if args.head is not None:
            assert args.before is not None
            assert args.default_branch is not None
            commit_range = _resolve_push_range(
                args.head,
                args.before,
                args.default_branch,
            )
        if commit_range:
            named_messages.extend(
                (f"commit #{index}", message)
                for index, message in enumerate(
                    _read_commit_messages_from_range(commit_range), start=1
                )
            )
        named_messages.extend(
            (str(path), path.read_text(encoding="utf-8")) for path in args.message_files
        )
    except OSError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if not named_messages:
        print("No commit messages supplied.", file=sys.stderr)
        return 2

    return _validate_named_messages(named_messages)


if __name__ == "__main__":
    raise SystemExit(main())
