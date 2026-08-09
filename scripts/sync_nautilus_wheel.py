"""Sync the canonical Nautilus wheel manifest into project build inputs.

The manifest at docs/runtime_verification/nautilus-polysignal-wheel.json is the
source of truth for the immutable Nautilus wheel. This script rewrites the two
pyproject.toml direct references, the rendered requirements file, and the
Dockerfile OCI provenance labels so the artifact is represented once. Callers
should run `uv lock` afterward so uv.lock also reflects the promoted artifact.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
CANONICAL_MANIFEST = ROOT / "docs/runtime_verification/nautilus-polysignal-wheel.json"
PYPROJECT = ROOT / "pyproject.toml"
DOCKERFILE = ROOT / "Dockerfile"
REQUIREMENT_FILE = ROOT / "requirements" / "nautilus.txt"

REQUIREMENT_RE = re.compile(
    r"nautilus_trader\[polymarket\] @ [^\s]+?\.whl#sha256=[0-9a-f]{64}"
)
DOCKER_LABELS = (
    ("upstream-sha", "upstream_base_sha"),
    ("patch-sha", "source_commit_sha"),
    ("release-tag", "release_tag"),
    ("version", "version"),
    ("wheel-sha256", "wheel_sha256"),
)


def _fail(message: str) -> None:
    raise SystemExit(f"sync: {message}")


def _load_manifest(path: Path) -> dict:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _fail(f"cannot read manifest {path}: {exc}")
    if not isinstance(manifest, dict):
        _fail(f"manifest {path} is not a JSON object")
    return manifest


def _requirement(manifest: dict) -> str:
    wheel_url = manifest.get("wheel_url")
    if not wheel_url:
        release_url = manifest.get("release_url", "").rstrip("/")
        wheel_filename = manifest.get("wheel_filename", "").replace("+", "%2B")
        wheel_url = f"{release_url}/{wheel_filename}"
    wheel_sha256 = manifest.get("wheel_sha256")
    if not wheel_sha256:
        _fail("manifest wheel_sha256 is missing")
    return f"nautilus_trader[polymarket] @ {wheel_url}#sha256={wheel_sha256}"


def _source_sha(manifest: dict) -> str:
    return str(
        manifest.get("source_commit_sha")
        or manifest.get("patch_commit_sha")
        or ""
    )


def _sync_pyproject(manifest: dict) -> None:
    text = PYPROJECT.read_text(encoding="utf-8")
    requirement = _requirement(manifest)
    updated, count = REQUIREMENT_RE.subn(requirement, text)
    if count != 2:
        _fail(f"pyproject.toml expected 2 nautilus direct references, found {count}")
    PYPROJECT.write_text(updated, encoding="utf-8")


def _sync_dockerfile(manifest: dict) -> None:
    text = DOCKERFILE.read_text(encoding="utf-8")
    for label, field in DOCKER_LABELS:
        if field == "source_commit_sha":
            value = _source_sha(manifest)
        else:
            value = manifest.get(field, "")
        if not value:
            _fail(f"manifest {field} is missing")
        pattern = re.compile(rf'(io\.polysignal\.nautilus\.{label}=")[^"]*(")')
        text, count = pattern.subn(lambda m: f"{m.group(1)}{value}{m.group(2)}", text)
        if count != 1:
            _fail(f"Dockerfile label {label} expected exactly once, found {count}")
    DOCKERFILE.write_text(text, encoding="utf-8")


def _sync_requirement_file(manifest: dict) -> None:
    REQUIREMENT_FILE.parent.mkdir(parents=True, exist_ok=True)
    REQUIREMENT_FILE.write_text(_requirement(manifest) + "\n", encoding="utf-8")


def _sync_command(args: argparse.Namespace) -> None:
    manifest = _load_manifest(Path(args.manifest))
    _sync_pyproject(manifest)
    _sync_requirement_file(manifest)
    _sync_dockerfile(manifest)
    changed = [
        PYPROJECT.relative_to(ROOT),
        REQUIREMENT_FILE.relative_to(ROOT),
        DOCKERFILE.relative_to(ROOT),
    ]
    print(f"sync: updated {', '.join(str(path) for path in changed)}")


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(required=True)
    sync_parser = subparsers.add_parser("sync", help="sync the canonical manifest")
    sync_parser.add_argument("--manifest", default=CANONICAL_MANIFEST)
    sync_parser.set_defaults(handler=_sync_command)
    args = parser.parse_args()
    args.handler(args)


if __name__ == "__main__":
    main()
