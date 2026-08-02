from __future__ import annotations

import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "validate_commit_msg.py"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
ZERO_SHA = "0" * 40


def _run_with_message(tmp_path: Path, message: str) -> subprocess.CompletedProcess[str]:
    message_file = tmp_path / "COMMIT_EDITMSG"
    _ = message_file.write_text(message, encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(message_file)],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_accepts_project_conventional_commit_with_scope(tmp_path: Path):
    result = _run_with_message(
        tmp_path,
        "fix(data): filter future crypto market windows\n\nKeep PTB reads inside active event windows.\n",
    )

    assert result.returncode == 0, result.stderr


def test_rejects_missing_conventional_type(tmp_path: Path):
    result = _run_with_message(tmp_path, "update stuff\n")

    assert result.returncode == 1
    assert "Expected format" in result.stderr


def test_rejects_vague_subject(tmp_path: Path):
    result = _run_with_message(tmp_path, "chore: update stuff\n")

    assert result.returncode == 1
    assert "too vague" in result.stderr


def test_rejects_long_subject(tmp_path: Path):
    result = _run_with_message(
        tmp_path,
        "docs(readme): document every single local development command and operational recovery checklist\n",
    )

    assert result.returncode == 1
    assert "72 characters or fewer" in result.stderr


def test_allows_git_generated_merge_and_revert_messages(tmp_path: Path):
    merge = _run_with_message(tmp_path, "Merge branch 'main' into feature/precommit\n")
    revert = _run_with_message(
        tmp_path,
        'Revert "fix(data): filter future crypto market windows"\n\nThis reverts commit abc123.\n',
    )

    assert merge.returncode == 0, merge.stderr
    assert revert.returncode == 0, revert.stderr


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        text=True,
        capture_output=True,
        check=True,
    )


def test_new_branch_range_starts_at_default_branch_merge_base(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _ = _git(repo, "init", "-b", "main")
    _ = _git(repo, "config", "user.name", "Commit Policy Test")
    _ = _git(repo, "config", "user.email", "commit-policy@example.com")

    tracked = repo / "tracked.txt"
    _ = tracked.write_text("base\n", encoding="utf-8")
    _ = _git(repo, "add", "tracked.txt")
    _ = _git(repo, "commit", "-m", "chore: establish test history")
    _ = _git(repo, "branch", "feature")

    _ = tracked.write_text("main\n", encoding="utf-8")
    _ = _git(repo, "commit", "-am", "legacy default branch subject")
    _ = _git(repo, "switch", "feature")
    _ = tracked.write_text("feature\n", encoding="utf-8")
    _ = _git(repo, "commit", "-am", "fix(ci): validate the feature commit only")

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--head",
            "HEAD",
            "--before",
            ZERO_SHA,
            "--default-branch",
            "main",
        ],
        cwd=repo,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def _commit_message_workflow_step() -> str:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    start = workflow.index("      - name: Validate commit messages")
    end = workflow.index("\n      - name:", start + 1)
    return workflow[start:end]


def test_workflow_skips_commit_gate_for_feature_branch_pushes():
    step = _commit_message_workflow_step()

    assert "github.event_name == 'pull_request'" in step
    assert (
        "github.ref == format('refs/heads/{0}', "
        "github.event.repository.default_branch)" in step
    )


def test_workflow_skips_commit_gate_for_branch_creation():
    step = _commit_message_workflow_step()

    assert f"github.event.before != '{ZERO_SHA}'" in step


def test_workflow_keeps_pull_request_and_default_branch_ranges():
    step = _commit_message_workflow_step()

    assert (
        '${{ github.event.pull_request.base.sha }}..'
        '${{ github.event.pull_request.head.sha }}' in step
    )
    assert '--head "${{ github.sha }}"' in step
    assert '--before "${{ github.event.before }}"' in step


def test_normal_push_range_starts_at_before_sha(tmp_path: Path):
    repo = tmp_path / "normal-push-repo"
    repo.mkdir()
    _ = _git(repo, "init", "-b", "main")
    _ = _git(repo, "config", "user.name", "Commit Policy Test")
    _ = _git(repo, "config", "user.email", "commit-policy@example.com")

    tracked = repo / "tracked.txt"
    _ = tracked.write_text("legacy\n", encoding="utf-8")
    _ = _git(repo, "add", "tracked.txt")
    _ = _git(repo, "commit", "-m", "legacy inherited subject")
    before = _git(repo, "rev-parse", "HEAD").stdout.strip()

    _ = tracked.write_text("new\n", encoding="utf-8")
    _ = _git(repo, "commit", "-am", "fix(ci): validate only the pushed commit")

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--head",
            "HEAD",
            "--before",
            before,
            "--default-branch",
            "main",
        ],
        cwd=repo,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
