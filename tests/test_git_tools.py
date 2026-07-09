"""Tests for git tool wrappers, against a real throwaway repo."""

import subprocess
from pathlib import Path

import pytest

from tessa.tools import git
from tessa.tools.filesystem import ToolError


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    (tmp_path / "a.txt").write_text("hello\n")
    return tmp_path


def test_is_repo(repo: Path, tmp_path_factory: pytest.TempPathFactory) -> None:
    assert git.is_repo(repo) is True
    not_a_repo = tmp_path_factory.mktemp("plain")
    assert git.is_repo(not_a_repo) is False


def test_status_shows_untracked(repo: Path) -> None:
    assert "a.txt" in git.status(repo)


def test_add_and_commit(repo: Path) -> None:
    git.add(repo, ["a.txt"])
    assert "a.txt" in git.diff(repo, staged=True)
    result = git.commit(repo, "Add a.txt")
    assert "Add a.txt" in result
    assert "nothing to commit" in git.status(repo) or git.status(repo).startswith("##")


def test_commit_without_staged_changes_raises(repo: Path) -> None:
    with pytest.raises(ToolError):
        git.commit(repo, "empty commit")


def test_commit_with_empty_message_raises(repo: Path) -> None:
    git.add(repo, ["a.txt"])
    with pytest.raises(ToolError):
        git.commit(repo, "   ")
