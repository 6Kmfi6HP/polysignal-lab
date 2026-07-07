"""
Input: __future__, __future__.annotations, subprocess, sys, pathlib, pathlib.Path
Output: test_accepts_project_conventional_commit_with_scope, test_rejects_missing_conventional_type, test_rejects_vague_subject, test_rejects_long_subject, test_allows_git_generated_merge_and_revert_messages
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "validate_commit_msg.py"


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
