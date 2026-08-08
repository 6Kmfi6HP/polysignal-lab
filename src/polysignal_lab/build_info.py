from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final, Self, cast

from polysignal_lab import __version__

BUILD_INFO_PATH: Final = Path("/app/build-info.json")
BUILD_INFO_REQUIRED_MARKER: Final = Path("/app/.require-build-info")
SEMVER_RE: Final = re.compile(
    r"^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)$"
)
SHA_RE: Final = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True, slots=True)
class BuildInfo:
    application_version: str
    build_version: str
    channel: str
    source_ref: str
    commit_sha: str | None
    short_commit_sha: str | None
    immutable_tag: str | None

    @classmethod
    def production(
        cls,
        *,
        application_version: str,
        build_version: str,
        channel: str,
        source_ref: str,
        commit_sha: str,
        short_commit_sha: str,
        immutable_tag: str,
    ) -> Self:
        if SEMVER_RE.fullmatch(application_version) is None:
            raise ValueError("application_version must be a stable X.Y.Z SemVer")
        if channel not in {"main", "debug"}:
            raise ValueError("channel must be main or debug")
        if source_ref != "main" and not source_ref.startswith("debug/"):
            raise ValueError("source_ref must be main or debug/**")
        if (channel == "main") != (source_ref == "main"):
            raise ValueError("channel does not match source_ref")
        if SHA_RE.fullmatch(commit_sha) is None:
            raise ValueError("commit_sha must be a full lowercase commit SHA")
        if short_commit_sha != commit_sha[:12]:
            raise ValueError("short_commit_sha does not match commit_sha")
        expected_build = re.compile(
            rf"^{re.escape(application_version)}-{channel}\.[1-9][0-9]*"
            + rf"\+{re.escape(short_commit_sha)}$"
        )
        if expected_build.fullmatch(build_version) is None:
            raise ValueError("build_version is inconsistent with build identity")
        if immutable_tag != f"sha-{commit_sha}":
            raise ValueError("immutable_tag does not match commit_sha")
        return cls(
            application_version=application_version,
            build_version=build_version,
            channel=channel,
            source_ref=source_ref,
            commit_sha=commit_sha,
            short_commit_sha=short_commit_sha,
            immutable_tag=immutable_tag,
        )

    @classmethod
    def from_mapping(cls, value: object) -> Self:
        if not isinstance(value, dict):
            raise ValueError("build info must be a JSON object")
        mapping = cast("dict[object, object]", value)
        required = {
            "application_version",
            "build_version",
            "channel",
            "source_ref",
            "commit_sha",
            "short_commit_sha",
            "immutable_tag",
        }
        if set(mapping) != required:
            raise ValueError("build info fields do not match the required schema")
        if not all(isinstance(mapping[key], str) for key in required):
            raise ValueError("production build info fields must be strings")
        data = cast("dict[str, str]", mapping)
        return cls.production(**data)

    @classmethod
    def local(cls, application_version: str | None = None) -> Self:
        if application_version is None:
            application_version = __version__
        if SEMVER_RE.fullmatch(application_version) is None:
            raise ValueError("local application version must be a stable X.Y.Z SemVer")
        return cls(
            application_version=application_version,
            build_version=f"{application_version}-local",
            channel="local",
            source_ref="local",
            commit_sha=None,
            short_commit_sha=None,
            immutable_tag=None,
        )

    def to_dict(self) -> dict[str, str | None]:
        return asdict(self)


def load_build_info(
    path: Path = BUILD_INFO_PATH,
    *,
    required: bool | None = None,
) -> BuildInfo:
    must_exist = BUILD_INFO_REQUIRED_MARKER.exists() if required is None else required
    try:
        raw = cast("object", json.loads(path.read_text(encoding="utf-8")))
    except FileNotFoundError:
        if must_exist:
            raise RuntimeError(f"required build info is missing: {path}") from None
        try:
            return BuildInfo.local()
        except ValueError:
            # 包元数据与 pyproject 都不可读时 __version__ 为 "0+unknown"，
            # 本地降级必须以稳定 SemVer 继续工作，而不是让模块导入崩溃。
            return BuildInfo.local(application_version="0.0.0")
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"cannot load build info from {path}: {exc}") from exc

    try:
        return BuildInfo.from_mapping(raw)
    except ValueError as exc:
        raise RuntimeError(f"invalid build info in {path}: {exc}") from exc


BUILD_INFO: Final = load_build_info()


def plan_build(
    *, ref_name: str, source_sha: str, run_number: int, base_version: str
) -> dict[str, str]:
    _require_sha(source_sha)
    if SEMVER_RE.fullmatch(base_version) is None:
        raise ValueError("base_version must be a stable X.Y.Z SemVer")
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
        "application_version": base_version,
        "build_version": f"{base_version}-{channel}.{run_number}+{source_sha[:12]}",
        "channel": channel,
        "immutable_tag": f"sha-{source_sha}",
        "moving_tag": moving_tag,
        "source_ref": ref_name,
        "commit_sha": source_sha,
        "short_commit_sha": source_sha[:12],
    }


def plan_release(*, tag: str, source_sha: str, base_version: str) -> dict[str, str]:
    _require_sha(source_sha)
    match = SEMVER_RE.fullmatch(base_version)
    if match is None:
        raise ValueError("base_version must be a stable X.Y.Z SemVer")
    expected_tag = f"v{base_version}"
    if tag != expected_tag:
        raise ValueError(
            f"release tag {tag!r} must exactly match project version {expected_tag!r}"
        )
    major, minor, _patch = base_version.split(".")
    return {
        "application_version": base_version,
        "immutable_tag": f"sha-{source_sha}",
        "major_minor_tag": f"{major}.{minor}",
        "release_tag": base_version,
        "commit_sha": source_sha,
    }


def build_info_from_plan(values: dict[str, str]) -> BuildInfo:
    return BuildInfo.production(
        application_version=values["application_version"],
        build_version=values["build_version"],
        channel=values["channel"],
        source_ref=values["source_ref"],
        commit_sha=values["commit_sha"],
        short_commit_sha=values["short_commit_sha"],
        immutable_tag=values["immutable_tag"],
    )


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
