from __future__ import annotations

import pytest

from polysignal_lab.build_info import build_info_from_plan, plan_build, plan_release

SHA = "abcdef1234567890abcdef1234567890abcdef12"


def test_plan_main_build_produces_complete_identity() -> None:
    plan = plan_build(
        ref_name="main",
        source_sha=SHA,
        run_number=185,
        base_version="1.0.0",
    )

    assert plan == {
        "application_version": "1.0.0",
        "build_version": "1.0.0-main.185+abcdef123456",
        "channel": "main",
        "immutable_tag": f"sha-{SHA}",
        "moving_tag": "main",
        "source_ref": "main",
        "commit_sha": SHA,
        "short_commit_sha": "abcdef123456",
    }
    assert build_info_from_plan(plan).build_version == plan["build_version"]


def test_plan_debug_build_has_stable_branch_channel() -> None:
    plan = plan_build(
        ref_name="debug/Book Recovery",
        source_sha=SHA,
        run_number=7,
        base_version="1.0.0",
    )

    assert plan["channel"] == "debug"
    assert plan["build_version"] == "1.0.0-debug.7+abcdef123456"
    assert plan["moving_tag"].startswith("debug-book-recovery-")


def test_plan_build_rejects_invalid_inputs() -> None:
    with pytest.raises(ValueError, match="main or debug"):
        _ = plan_build(
            ref_name="feature/x",
            source_sha=SHA,
            run_number=1,
            base_version="1.0.0",
        )
    with pytest.raises(ValueError, match="full lowercase commit SHA"):
        _ = plan_build(
            ref_name="main",
            source_sha="abc",
            run_number=1,
            base_version="1.0.0",
        )
    with pytest.raises(ValueError, match="positive integer"):
        _ = plan_build(
            ref_name="main",
            source_sha=SHA,
            run_number=0,
            base_version="1.0.0",
        )


def test_plan_release_requires_matching_stable_version_tag() -> None:
    assert plan_release(tag="v1.0.0", source_sha=SHA, base_version="1.0.0") == {
        "application_version": "1.0.0",
        "immutable_tag": f"sha-{SHA}",
        "major_minor_tag": "1.0",
        "release_tag": "1.0.0",
        "commit_sha": SHA,
    }

    with pytest.raises(ValueError, match="must exactly match"):
        _ = plan_release(tag="v1.0.1", source_sha=SHA, base_version="1.0.0")
