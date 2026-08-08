#!/usr/bin/env python3
"""Derive and validate PolySignal application image versions."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

import tomllib

SEMVER_RE = re.compile(
    r"^(?P<major>0|[1-9][0-9]*)\."
    r"(?P<minor>0|[1-9][0-9]*)\."
    r"(?P<patch>0|[1-9][0-9]*)$"
)
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _base_version(pyproject: Path) -> str:
    project = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]
    version = project["version"]
    if not isinstance(version, str) or SEMVER_RE.fullmatch(version) is None:
        raise ValueError("project.version must be a stable X.Y.Z SemVer version")
    return version


def _require_sha(value: str) -> None:
    if SHA_RE.fullmatch(value) is None:
        raise ValueError("source SHA must be a full lowercase commit SHA")


def _debug_tag(ref_name: str) -> str:
    branch_name = ref_name.removeprefix("debug/")
    slug = re.sub(r"[^a-z0-9._-]+", "-", branch_name.lower()).strip(".-")
    slug = re.sub(r"-+", "-", slug)
    if not slug:
        raise ValueError("debug branch must have a name after debug/")
    branch_id = hashlib.sha256(ref_name.encode()).hexdigest()[:8]
    return f"debug-{slug[:96]}-{branch_id}"


def plan_build(
    *, ref_name: str, source_sha: str, run_number: int, base_version: str
) -> dict[str, str]:
    _require_sha(source_sha)
    if run_number < 1:
        raise ValueError("run number must be a positive integer")

    if ref_name == "main":
        channel = "main"
        moving_tag = "main"
    elif ref_name.startswith("debug/"):
        channel = "debug"
        moving_tag = _debug_tag(ref_name)
    else:
        raise ValueError("image builds are allowed only from main or debug/**")

    return {
        "base_version": base_version,
        "build_version": (
            f"{base_version}-{channel}.{run_number}+{source_sha[:12]}"
        ),
        "channel": channel,
        "immutable_tag": f"sha-{source_sha}",
        "moving_tag": moving_tag,
        "source_ref": ref_name,
        "source_sha": source_sha,
    }


def plan_release(*, tag: str, source_sha: str, base_version: str) -> dict[str, str]:
    _require_sha(source_sha)
    match = SEMVER_RE.fullmatch(base_version)
    assert match is not None
    expected_tag = f"v{base_version}"
    if tag != expected_tag:
        raise ValueError(
            f"release tag {tag!r} must exactly match project version {expected_tag!r}"
        )
    return {
        "base_version": base_version,
        "immutable_tag": f"sha-{source_sha}",
        "major_minor_tag": f"{match.group('major')}.{match.group('minor')}",
        "release_tag": base_version,
        "source_sha": source_sha,
    }


def _write_github_output(path: Path, values: dict[str, str]) -> None:
    with path.open("a", encoding="utf-8") as output:
        for key, value in values.items():
            output.write(f"{key}={value}\n")


def _run(args: argparse.Namespace) -> None:
    base_version = _base_version(args.pyproject)
    if args.command == "build":
        values = plan_build(
            ref_name=args.ref_name,
            source_sha=args.source_sha,
            run_number=args.run_number,
            base_version=base_version,
        )
    else:
        values = plan_release(
            tag=args.tag,
            source_sha=args.source_sha,
            base_version=base_version,
        )
    if args.github_output is not None:
        _write_github_output(args.github_output, values)
    print(json.dumps(values, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    build_parser = subparsers.add_parser("build")
    build_parser.add_argument("--ref-name", required=True)
    build_parser.add_argument("--source-sha", required=True)
    build_parser.add_argument("--run-number", required=True, type=int)
    build_parser.add_argument("--pyproject", type=Path, default=Path("pyproject.toml"))
    build_parser.add_argument("--github-output", type=Path)

    release_parser = subparsers.add_parser("release")
    release_parser.add_argument("--tag", required=True)
    release_parser.add_argument("--source-sha", required=True)
    release_parser.add_argument(
        "--pyproject", type=Path, default=Path("pyproject.toml")
    )
    release_parser.add_argument("--github-output", type=Path)

    args = parser.parse_args()
    try:
        _run(args)
    except (KeyError, OSError, tomllib.TOMLDecodeError, ValueError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
