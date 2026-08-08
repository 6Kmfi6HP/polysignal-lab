"""Consumer half of the Nautilus wheel promotion pipeline.

The fork workflow
(`6Kmfi6HP/nautilus_trader/.github/workflows/polysignal-release.yml`) publishes an
immutable GitHub Release containing `polysignal-release.json` (the release
manifest), the wheel, `SHA256SUMS` and a SPDX SBOM.  This tool is the *consumer*
half: it validates that manifest against an immutable whitelist and then rewrites
this repository's canonical manifest, direct dependency URLs and Docker labels.

The `promote-nautilus` workflow runs this tool in order:

  1. gh release verify                  -- immutable release + attestation
  2. sha256sum --check SHA256SUMS       -- wheel + manifest digests
  3. promote_nautilus_release.py verify --manifest ... --wheel ...
  4. promote_nautilus_release.py sync   --manifest ...
  5. uv lock                            -- regenerate the lockfile
  6. verify_nautilus_manifest_drift.py  -- all five sources agree

Only `sync` mutates the working tree; `verify` is read-only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CANONICAL_MANIFEST = ROOT / "docs/runtime_verification/nautilus-polysignal-wheel.json"
PYPROJECT = ROOT / "pyproject.toml"
DOCKERFILE = ROOT / "Dockerfile"

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
REQUIRED_REPOSITORY = "6Kmfi6HP/nautilus_trader"
REQUIRED_WORKFLOW_IDENTITY = (
    f"{REQUIRED_REPOSITORY}/.github/workflows/polysignal-release.yml"
)
REQUIRED_ABI = "cp312"
REQUIRED_PLATFORM = "manylinux_2_36_x86_64"
WHEEL_RE = re.compile(
    rf"^nautilus_trader-(?P<version>[^-]+)-{re.escape(REQUIRED_ABI)}-cp312-"
    rf"{re.escape(REQUIRED_PLATFORM)}\.whl$"
)
RELEASE_TAG_RE = re.compile(r"^polysignal-(?P<base>.+)\.(?P<serial>[0-9]+)$")
BASE_VERSION_RE = re.compile(r"[0-9]+(?:\.[0-9]+)+(?:a|b|rc)?[0-9]*")

# `dependencies` and the `nautilus` extra carry the identical direct reference.
REQUIREMENT_RE = re.compile(
    r"nautilus_trader\[polymarket\] @ https://[^\s]+?\.whl#sha256=[0-9a-f]{64}"
)
DOCKER_LABELS = (
    ("upstream-sha", "upstream_base_sha"),
    ("patch-sha", "source_commit_sha"),
    ("release-tag", "release_tag"),
    ("version", "version"),
    ("wheel-sha256", "wheel_sha256"),
)


def _fail(message: str) -> None:
    raise SystemExit(f"promote: {message}")


def _load_manifest(path: Path) -> dict[str, Any]:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        _fail(f"cannot read release manifest {path}: {exc}")
    if not isinstance(manifest, dict):
        _fail(f"release manifest {path} is not a JSON object")
    return manifest


def verify_manifest(
    manifest: dict[str, Any],
    wheel: Path | None = None,
    expected_release_tag: str | None = None,
) -> dict[str, Any]:
    """Validate a fork release manifest against the immutable whitelist."""
    required = (
        "schema_version",
        "repository",
        "release_tag",
        "release_url",
        "version",
        "source_commit_sha",
        "upstream_base_sha",
        "wheel_filename",
        "wheel_sha256",
        "python_abi",
        "platform",
        "workflow_identity",
    )
    missing = [key for key in required if key not in manifest]
    if missing:
        _fail(f"release manifest missing fields: {', '.join(missing)}")

    if manifest["schema_version"] != 1:
        _fail("schema_version must be 1")
    if manifest["repository"] != REQUIRED_REPOSITORY:
        _fail(f"repository must be {REQUIRED_REPOSITORY}")
    if manifest["workflow_identity"] != REQUIRED_WORKFLOW_IDENTITY:
        _fail(f"workflow_identity must be {REQUIRED_WORKFLOW_IDENTITY}")
    if manifest["python_abi"] != REQUIRED_ABI:
        _fail(f"python_abi must be {REQUIRED_ABI}")
    if manifest["platform"] != REQUIRED_PLATFORM:
        _fail(f"platform must be {REQUIRED_PLATFORM}")

    for key in ("source_commit_sha", "upstream_base_sha"):
        if SHA_RE.fullmatch(manifest[key]) is None:
            _fail(f"{key} must be a full lowercase commit SHA")

    version: str = manifest["version"]
    if ".dev" in version:
        _fail("refusing ephemeral develop wheel (version contains '.dev')")
    tag: str = manifest["release_tag"]
    if expected_release_tag is not None and tag != expected_release_tag:
        _fail("manifest release_tag does not match the requested release tag")
    tag_match = RELEASE_TAG_RE.fullmatch(tag)
    if tag_match is None:
        _fail(f"release_tag {tag} is not a polysignal-<version>.<serial> tag")
    if f"{tag_match.group('base')}+polysignal.{tag_match.group('serial')}" != version:
        _fail("release_tag and version do not agree on the polysignal serial")

    wheel_name = manifest["wheel_filename"]
    wheel_match = WHEEL_RE.fullmatch(wheel_name)
    if wheel_match is None:
        _fail(f"wheel_filename {wheel_name} is not the pinned CPython 3.12 artifact")
    if wheel_match.group("version") != version:
        _fail("wheel_filename version does not match release version")
    if SHA256_RE.fullmatch(manifest["wheel_sha256"]) is None:
        _fail("wheel_sha256 must be a 64-char hex digest")

    if wheel is not None:
        resolved = wheel.resolve()
        if not resolved.is_file():
            _fail(f"wheel {wheel} does not exist")
        if resolved.name != wheel_name:
            _fail(f"wheel {resolved.name} does not match manifest wheel_filename")
        digest = hashlib.sha256(resolved.read_bytes()).hexdigest()
        if digest != manifest["wheel_sha256"]:
            _fail("wheel SHA-256 does not match manifest wheel_sha256")

    return manifest


def _canonical_manifest(release: dict[str, Any]) -> dict[str, Any]:
    source_sha = release["source_commit_sha"]
    wheel = release["wheel_filename"]
    build_command = (
        "uv build --wheel --python 3.12 --out-dir dist && "
        f"python3 scripts/ci/polysignal_release.py manifest "
        f"--wheel dist/{wheel} --source-sha {source_sha} "
        f"--upstream-base-sha {release['upstream_base_sha']} "
        f"--version {release['version']} --release-tag {release['release_tag']} "
        f"--repository {release['repository']} "
        f"--workflow-identity {release['workflow_identity']} "
        "--output dist/polysignal-release.json"
    )
    verification_command = (
        f"python3 scripts/promote_nautilus_release.py verify "
        f"--manifest dist/polysignal-release.json --wheel dist/{wheel} && "
        "uv run python scripts/verify_nautilus_wheel_provenance.py "
        f"--source <fork-checkout-at-{source_sha}> --wheel dist/{wheel}"
    )
    return {
        "schema_version": release["schema_version"],
        "repository": release["repository"],
        "release_tag": release["release_tag"],
        "release_url": release["release_url"],
        "version": release["version"],
        "source_commit_sha": source_sha,
        # Back-compat alias kept for the existing dependency-boundary gates.
        "patch_commit_sha": source_sha,
        "upstream_base_sha": release["upstream_base_sha"],
        "wheel_filename": wheel,
        "wheel_sha256": release["wheel_sha256"],
        "python_abi": release["python_abi"],
        "platform": release["platform"],
        "workflow_identity": release["workflow_identity"],
        "build_command": build_command,
        "verification_command": verification_command,
    }


def _requirement(release: dict[str, Any]) -> str:
    wheel = release["wheel_filename"].replace("+", "%2B")
    return (
        f"nautilus_trader[polymarket] @ "
        f"https://github.com/{release['repository']}/releases/download/"
        f"{release['release_tag']}/{wheel}#sha256={release['wheel_sha256']}"
    )


def _sync_pyproject(release: dict[str, Any]) -> None:
    text = PYPROJECT.read_text(encoding="utf-8")
    requirement = _requirement(release)
    updated, count = REQUIREMENT_RE.subn(requirement, text)
    if count != 2:
        _fail(f"pyproject.toml expected 2 nautilus direct references, found {count}")
    PYPROJECT.write_text(updated, encoding="utf-8")


def _sync_dockerfile(release: dict[str, Any]) -> None:
    text = DOCKERFILE.read_text(encoding="utf-8")
    values = {key: str(release[field]) for key, field in DOCKER_LABELS}
    for label, value in values.items():
        pattern = re.compile(rf'(io\.polysignal\.nautilus\.{label}=")[^"]*(")')
        text, count = pattern.subn(lambda m: f"{m.group(1)}{value}{m.group(2)}", text)
        if count != 1:
            _fail(f"Dockerfile label {label} expected exactly once, found {count}")
    DOCKERFILE.write_text(text, encoding="utf-8")


def _verify_command(args: argparse.Namespace) -> None:
    manifest = _load_manifest(Path(args.manifest))
    wheel = Path(args.wheel).resolve() if args.wheel else None
    verify_manifest(manifest, wheel, args.release_tag)
    print("release manifest verified")


def _sync_command(args: argparse.Namespace) -> None:
    release = verify_manifest(_load_manifest(Path(args.manifest)))
    CANONICAL_MANIFEST.write_text(
        json.dumps(_canonical_manifest(release), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _sync_pyproject(release)
    _sync_dockerfile(release)
    print(f"promoted {release['release_tag']} -> "
          f"{CANONICAL_MANIFEST.relative_to(ROOT)}, "
          f"{PYPROJECT.relative_to(ROOT)}, {DOCKERFILE.relative_to(ROOT)}")


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(required=True)

    verify_parser = subparsers.add_parser(
        "verify", help="validate a fork release manifest (read-only)"
    )
    verify_parser.add_argument("--manifest", required=True)
    verify_parser.add_argument("--wheel")
    verify_parser.add_argument("--release-tag")
    verify_parser.set_defaults(handler=_verify_command)

    sync_parser = subparsers.add_parser(
        "sync", help="promote a verified manifest into this repo"
    )
    sync_parser.add_argument("--manifest", required=True)
    sync_parser.set_defaults(handler=_sync_command)

    args = parser.parse_args()
    args.handler(args)


if __name__ == "__main__":
    main()
