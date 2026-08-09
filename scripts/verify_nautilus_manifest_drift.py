"""Drift check across the Nautilus wheel provenance sources.

Ensures the canonical manifest, the two `pyproject.toml` direct references,
`uv.lock`, the rendered wheel requirement, and the `Dockerfile` OCI labels all
describe the *same* immutable wheel. The manifest is the source of truth and
can point at any immutable wheel URL; every other source must agree with it.

Exit code is 0 only when every source agrees with the canonical manifest.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tomllib
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parents[1]
CANONICAL_MANIFEST = ROOT / "docs/runtime_verification/nautilus-polysignal-wheel.json"
PYPROJECT = ROOT / "pyproject.toml"
UV_LOCK = ROOT / "uv.lock"
DOCKERFILE = ROOT / "Dockerfile"
REQUIREMENT_FILE = ROOT / "requirements" / "nautilus.txt"

DOCKER_LABELS = (
    ("upstream-sha", "upstream_base_sha"),
    ("patch-sha", "source_commit_sha"),
    ("release-tag", "release_tag"),
    ("version", "version"),
    ("wheel-sha256", "wheel_sha256"),
)


def _wheel_url(manifest: dict) -> str:
    url = manifest.get("wheel_url")
    if url:
        return str(url)
    release_url = str(manifest["release_url"]).rstrip("/")
    filename = str(manifest["wheel_filename"]).replace("+", "%2B")
    return f"{release_url}/{filename}"


def _canonical_view(manifest: dict) -> dict:
    try:
        return {
            "version": manifest["version"],
            "release_tag": manifest["release_tag"],
            "wheel_url": _wheel_url(manifest),
            "wheel_filename": manifest["wheel_filename"],
            "wheel_sha256": manifest["wheel_sha256"],
            "upstream_base_sha": manifest["upstream_base_sha"],
            "source_commit_sha": manifest.get("source_commit_sha")
            or manifest["patch_commit_sha"],
            "patch_commit_sha": manifest["patch_commit_sha"],
            "release_url": manifest["release_url"],
            "repository": manifest.get("repository"),
            "source_ref": manifest.get("source_ref"),
            "source_kind": manifest.get("source_kind"),
        }
    except KeyError as exc:
        raise ValueError(f"canonical manifest missing field {exc.args[0]}") from exc


def _requirement(view: dict) -> str:
    return (
        f"nautilus_trader[polymarket] @ "
        f"{view['wheel_url']}#sha256={view['wheel_sha256']}"
    )


def _same_url(left: str, right: str) -> bool:
    return unquote(left) == unquote(right)


def _check_manifest(manifest: dict, view: dict, errors: list[str]) -> None:
    if len(view["wheel_sha256"]) != 64 or any(
        char not in "0123456789abcdef" for char in view["wheel_sha256"]
    ):
        errors.append("manifest: wheel_sha256 must be a 64-character hex digest")
    parsed = urlparse(view["wheel_url"])
    if parsed.scheme not in {"https", "file"}:
        errors.append("manifest: wheel_url must use https or file scheme")
    url_filename = unquote(parsed.path.rstrip("/").rsplit("/", 1)[-1])
    if url_filename != view["wheel_filename"]:
        errors.append("manifest: wheel_url filename differs from wheel_filename")
    if not view.get("source_kind"):
        errors.append("manifest: source_kind is required")
    if not view.get("repository"):
        errors.append("manifest: repository is required")
    if not view.get("source_ref"):
        errors.append("manifest: source_ref is required")


def _check_pyproject(view: dict, errors: list[str]) -> None:
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
    expected = _requirement(view)
    if requirement != expected:
        errors.append("pyproject.toml: requirement differs from manifest")
    if project["project"]["requires-python"] != ">=3.12,<3.13":
        errors.append("pyproject.toml: requires-python drifted from >=3.12,<3.13")


def _check_requirement_file(view: dict, errors: list[str]) -> None:
    if not REQUIREMENT_FILE.exists():
        errors.append(f"{REQUIREMENT_FILE}: missing rendered requirement file")
        return
    lines = [
        line.strip()
        for line in REQUIREMENT_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if lines != [_requirement(view)]:
        errors.append(f"{REQUIREMENT_FILE}: requirement differs from manifest")


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
    if not _same_url(url, view["wheel_url"]):
        errors.append("uv.lock: nautilus-trader URL differs from manifest")
    if view["wheel_filename"] not in unquote(url):
        errors.append("uv.lock: nautilus-trader URL wheel filename differs from manifest")
    wheels = package.get("wheels", [])
    if not wheels or "hash" not in wheels[0]:
        errors.append("uv.lock: nautilus-trader wheel hash missing")
    elif wheels[0]["hash"] != f"sha256:{view['wheel_sha256']}":
        errors.append("uv.lock: nautilus-trader wheel hash differs from manifest")


def _check_dockerfile(view: dict, errors: list[str]) -> None:
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    for label, field in DOCKER_LABELS:
        expected = f'io.polysignal.nautilus.{label}="{view[field]}"'
        if expected not in dockerfile:
            errors.append(f"Dockerfile: label {label} differs from manifest")
    if "git+https://" in dockerfile:
        errors.append("Dockerfile: nautilus_trader must be sourced from a wheel URL, not git")


def main() -> None:
    errors: list[str] = []
    try:
        manifest = json.loads(CANONICAL_MANIFEST.read_text(encoding="utf-8"))
        view = _canonical_view(manifest)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"drift: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    _check_manifest(manifest, view, errors)
    _check_pyproject(view, errors)
    _check_requirement_file(view, errors)
    _check_uv_lock(manifest, view, errors)
    _check_dockerfile(view, errors)

    if errors:
        raise SystemExit("|\n".join(f"drift: {error}" for error in errors))
    print(
        f"drift: {view['source_kind']} {view['release_tag']} ({view['version']}) "
        "is consistent across all sources"
    )


if __name__ == "__main__":
    main()
