"""Drift check across the four Nautilus wheel provenance sources.

Ensures the canonical manifest, the two `pyproject.toml` direct references,
`uv.lock` and the `Dockerfile` OCI labels all describe the *same* immutable
wheel.  Running this in CI before and after a promotion guards against the
sources drifting apart when the official nightly wheel reference is updated.

The wheel is sourced from the official Nautech Systems package index
(`packages.nautechsystems.io`) — no git fork or GitHub Release is involved.
The nightly wheel's version carries the PEP-440 `aYYYYMMDD` date suffix;
its source commit is the official `nightly` branch HEAD at build time.

Exit code is 0 only when every source agrees with the canonical manifest.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]
CANONICAL_MANIFEST = ROOT / "docs/runtime_verification/nautilus-polysignal-wheel.json"
PYPROJECT = ROOT / "pyproject.toml"
UV_LOCK = ROOT / "uv.lock"
DOCKERFILE = ROOT / "Dockerfile"

DOCKER_LABELS = (
    ("upstream-sha", "upstream_base_sha"),
    ("patch-sha", "patch_commit_sha"),
    ("release-tag", "release_tag"),
    ("version", "version"),
    ("wheel-sha256", "wheel_sha256"),
)

# Official nightly wheel URL root.
INDEX_BASE = "https://packages.nautechsystems.io/simple/nautilus-trader"


def _canonical_view(manifest: dict) -> dict:
    try:
        return {
            "version": manifest["version"],
            "release_tag": manifest["release_tag"],
            "wheel_filename": manifest["wheel_filename"],
            "wheel_sha256": manifest["wheel_sha256"],
            "upstream_base_sha": manifest["upstream_base_sha"],
            "patch_commit_sha": manifest["patch_commit_sha"],
        }
    except KeyError as exc:
        raise ValueError(f"canonical manifest missing field {exc.args[0]}") from exc


def _check_pyproject(manifest: dict, view: dict, errors: list[str]) -> None:
    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    dependencies = project["project"]["dependencies"]
    requirement = next(
        (dep for dep in dependencies if dep.startswith("nautilus_trader[polymarket] @ ")),
        None,
    )
    if requirement is None:
        errors.append("pyproject.toml: missing nautilus_trader direct dependency")
        return
    nautilus_extra = project["project"]["optional-dependencies"]["nautilus"]
    if nautilus_extra != [requirement]:
        errors.append(
            "pyproject.toml: nautilus extra differs from the default direct dependency"
        )
    if f"#sha256={view['wheel_sha256']}" not in requirement:
        errors.append("pyproject.toml: requirement wheel SHA-256 differs from manifest")
    if INDEX_BASE not in requirement:
        errors.append(
            "pyproject.toml: requirement not sourced from the official Nautech index"
        )
    if view["wheel_filename"] not in requirement:
        errors.append("pyproject.toml: requirement wheel filename differs from manifest")
    if project["project"]["requires-python"] != ">=3.12,<3.13":
        errors.append("pyproject.toml: requires-python drifted from >=3.12,<3.13")


def _check_uv_lock(manifest: dict, view: dict, errors: list[str]) -> None:
    lock = tomllib.loads(UV_LOCK.read_text(encoding="utf-8"))
    packages = [pkg for pkg in lock["package"] if pkg["name"] == "nautilus-trader"]
    if len(packages) != 1:
        errors.append(f"uv.lock: expected exactly one nautilus-trader, found {len(packages)}")
        return
    package = packages[0]
    if package["version"] != view["version"]:
        errors.append("uv.lock: nautilus-trader version differs from manifest")
    source = package.get("source", {})
    if "git" in source:
        errors.append("uv.lock: nautilus-trader is a git source build")
    url = source.get("url", package.get("wheels", [{}])[0].get("url", ""))
    if INDEX_BASE not in url:
        errors.append("uv.lock: nautilus-trader URL not from the official Nautech index")
    if view["wheel_filename"] not in url:
        errors.append("uv.lock: nautilus-trader URL wheel filename differs from manifest")
    wheels = package.get("wheels", [])
    if not wheels or "hash" not in wheels[0]:
        errors.append("uv.lock: nautilus-trader wheel hash missing")
    elif wheels[0]["hash"] != f"sha256:{view['wheel_sha256']}":
        errors.append("uv.lock: nautilus-trader wheel hash differs from manifest")


def _check_dockerfile(manifest: dict, view: dict, errors: list[str]) -> None:
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    for label, field in DOCKER_LABELS:
        expected = f'io.polysignal.nautilus.{label}="{view[field]}"'
        if expected not in dockerfile:
            errors.append(f"Dockerfile: label {label} differs from manifest")
    if re.search(r"git\+https://github\.com/6Kmfi6HP/nautilus_trader", dockerfile):
        errors.append("Dockerfile: nautilus_trader sourced via git fork")


def main() -> None:
    errors: list[str] = []
    try:
        manifest = json.loads(CANONICAL_MANIFEST.read_text(encoding="utf-8"))
        view = _canonical_view(manifest)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"drift: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    _check_pyproject(manifest, view, errors)
    _check_uv_lock(manifest, view, errors)
    _check_dockerfile(manifest, view, errors)

    if errors:
        raise SystemExit("|\n".join(f"drift: {error}" for error in errors))
    print(
        f"drift: official nightly {view['release_tag']} ({view['version']}) "
        "is consistent across all sources"
    )


if __name__ == "__main__":
    main()
