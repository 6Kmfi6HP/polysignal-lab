from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tomllib
import os


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "docs/runtime_verification/nautilus-polysignal-wheel.json"


def _git(source: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(source), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def verify(source: Path, wheel: Path | None) -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    patch_sha = manifest["patch_commit_sha"]
    base_sha = manifest["upstream_base_sha"]
    if _git(source, "rev-parse", "HEAD") != patch_sha:
        raise SystemExit(f"source HEAD does not match patch_commit_sha {patch_sha}")
    subprocess.run(
        ["git", "-C", str(source), "merge-base", "--is-ancestor", base_sha, patch_sha],
        check=True,
    )
    project = tomllib.loads((source / "pyproject.toml").read_text(encoding="utf-8"))
    if project["project"]["version"] != manifest["version"]:
        raise SystemExit("source version does not match wheel manifest")
    if wheel is None:
        return
    if wheel.name != manifest["wheel_filename"]:
        raise SystemExit("wheel filename does not match wheel manifest")
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    if digest != manifest["wheel_sha256"]:
        raise SystemExit("wheel SHA-256 does not match wheel manifest")


def build(source: Path, output_dir: Path) -> Path:
    verify(source, None)
    env = os.environ.copy()
    env["PATH"] = f"{Path.home() / '.cargo/bin'}:/usr/local/bin:/usr/bin:/bin"
    env["PYO3_PYTHON"] = "python3.12"
    subprocess.run(
        [
            "uvx",
            "uv@0.11.33",
            "build",
            "--wheel",
            "--python",
            "3.12",
            "--out-dir",
            str(output_dir),
            "--clear",
        ],
        cwd=source,
        env=env,
        check=True,
    )
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    wheel = output_dir / manifest["wheel_filename"]
    verify(source, wheel)
    return wheel


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--wheel", type=Path)
    parser.add_argument("--build-output", type=Path)
    args = parser.parse_args()
    source = args.source.resolve()
    if args.build_output is not None:
        build(source, args.build_output.resolve())
    else:
        verify(source, args.wheel.resolve() if args.wheel else None)


if __name__ == "__main__":
    main()
