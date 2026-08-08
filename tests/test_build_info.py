from __future__ import annotations

import json
from pathlib import Path

import pytest

from polysignal_lab import build_info
from polysignal_lab.build_info import BuildInfo, load_build_info

SHA = "abcdef1234567890abcdef1234567890abcdef12"


def _production_payload() -> dict[str, str]:
    return {
        "application_version": "1.0.0",
        "build_version": "1.0.0-main.185+abcdef123456",
        "channel": "main",
        "source_ref": "main",
        "commit_sha": SHA,
        "short_commit_sha": "abcdef123456",
        "immutable_tag": f"sha-{SHA}",
    }


def test_load_build_info_validates_production_manifest(tmp_path: Path) -> None:
    path = tmp_path / "build-info.json"
    _ = path.write_text(json.dumps(_production_payload()), encoding="utf-8")

    info = load_build_info(path, required=True)

    assert info.to_dict() == _production_payload()


def test_load_build_info_falls_back_to_explicit_local_identity(tmp_path: Path) -> None:
    info = load_build_info(tmp_path / "missing.json", required=False)

    assert info.channel == "local"
    assert info.build_version == f"{info.application_version}-local"
    assert info.commit_sha is None
    assert info.short_commit_sha is None
    assert info.immutable_tag is None


def test_load_build_info_local_fallback_survives_unknown_package_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(build_info, "__version__", "0+unknown")

    info = load_build_info(tmp_path / "missing.json", required=False)

    assert info.application_version == "0.0.0"
    assert info.build_version == "0.0.0-local"
    assert info.channel == "local"


def test_load_build_info_fails_when_required_manifest_is_missing(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="required build info is missing"):
        _ = load_build_info(tmp_path / "missing.json", required=True)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("application_version", "1.0", "stable X.Y.Z SemVer"),
        ("build_version", "1.0.0-main.0+abcdef123456", "inconsistent"),
        ("channel", "release", "main or debug"),
        ("source_ref", "feature/example", "main or debug"),
        ("commit_sha", "abc", "full lowercase commit SHA"),
        ("short_commit_sha", "000000000000", "does not match"),
        ("immutable_tag", "sha-deadbeef", "does not match"),
    ],
)
def test_build_info_rejects_inconsistent_fields(
    field: str, value: str, message: str
) -> None:
    payload = _production_payload()
    payload[field] = value

    with pytest.raises(ValueError, match=message):
        _ = BuildInfo.from_mapping(payload)


def test_build_info_rejects_missing_or_extra_fields() -> None:
    payload = _production_payload()
    del payload["channel"]

    with pytest.raises(ValueError, match="required schema"):
        _ = BuildInfo.from_mapping(payload)
