"""Tests for read/write/search filesystem tools."""

from pathlib import Path

import pytest

from tessa.tools.filesystem import (
    ToolError,
    apply_delete,
    apply_write,
    list_dir,
    propose_write,
    read_file,
    search_code,
)


def test_read_file_numbers_lines(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("one\ntwo\nthree\n")
    content = read_file(tmp_path, "a.py")
    assert content == "    1\tone\n    2\ttwo\n    3\tthree"


def test_read_file_line_range(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("one\ntwo\nthree\n")
    content = read_file(tmp_path, "a.py", start_line=2, end_line=2)
    assert content == "    2\ttwo"


def test_read_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(ToolError):
        read_file(tmp_path, "nope.py")


def test_list_dir_shows_directories_and_files(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "README.md").write_text("hi")
    output = list_dir(tmp_path, ".")
    assert "src/" in output
    assert "README.md" in output


def test_search_code_finds_matches(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def foo():\n    return bar()\n")
    output = search_code(tmp_path, "bar")
    assert "a.py:2:return bar()" in output


def test_search_code_no_matches(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("hello\n")
    output = search_code(tmp_path, "nonexistent_xyz")
    assert "No matches" in output


def test_propose_write_new_file_has_no_old_content(tmp_path: Path) -> None:
    proposal = propose_write(tmp_path, "new.py", "print(1)\n")
    assert proposal.is_new_file is True
    assert proposal.old_content is None
    assert "print(1)" in proposal.diff


def test_propose_write_modify_produces_unified_diff(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("old\n")
    proposal = propose_write(tmp_path, "a.py", "new\n")
    assert proposal.is_new_file is False
    assert "-old" in proposal.diff
    assert "+new" in proposal.diff


def test_apply_write_creates_file_and_backup_on_overwrite(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("old\n")
    proposal = propose_write(tmp_path, "a.py", "new\n")
    apply_write(tmp_path, proposal)
    assert (tmp_path / "a.py").read_text() == "new\n"
    backups = list((tmp_path / ".tessa" / "backups").glob("*a.py"))
    assert len(backups) == 1
    assert backups[0].read_text() == "old\n"


def test_apply_delete_backs_up_and_removes(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("content\n")
    apply_delete(tmp_path, "a.py")
    assert not (tmp_path / "a.py").exists()
    backups = list((tmp_path / ".tessa" / "backups").glob("*a.py"))
    assert len(backups) == 1


def test_write_blocked_outside_root(tmp_path: Path) -> None:
    from tessa.tools.paths import PathEscapesProjectError

    with pytest.raises(PathEscapesProjectError):
        propose_write(tmp_path, "../escape.py", "x")
