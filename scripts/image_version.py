#!/usr/bin/env python3
"""Derive and validate PolySignal application image versions."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import tomllib

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from polysignal_lab.build_info import (  # noqa: E402
    SEMVER_RE,
    build_info_from_plan,
    plan_build,
    plan_release,
)


def _base_version(pyproject: Path) -> str:
    project = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]
    version = project["version"]
    if not isinstance(version, str) or SEMVER_RE.fullmatch(version) is None:
        raise ValueError("project.version must be a stable X.Y.Z SemVer version")
    return version


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
    if args.manifest_output is not None:
        if args.command != "build":
            raise ValueError("only build plans can create a build info manifest")
        manifest = build_info_from_plan(values)
        args.manifest_output.write_text(
            json.dumps(manifest.to_dict(), sort_keys=True) + "\n",
            encoding="utf-8",
        )
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
    build_parser.add_argument("--manifest-output", type=Path)

    release_parser = subparsers.add_parser("release")
    release_parser.add_argument("--tag", required=True)
    release_parser.add_argument("--source-sha", required=True)
    release_parser.add_argument(
        "--pyproject", type=Path, default=Path("pyproject.toml")
    )
    release_parser.add_argument("--github-output", type=Path)
    release_parser.set_defaults(manifest_output=None)

    args = parser.parse_args()
    try:
        _run(args)
    except (KeyError, OSError, tomllib.TOMLDecodeError, ValueError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
