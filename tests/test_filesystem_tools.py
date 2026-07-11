"""Tests for read/write/search filesystem tools."""

from pathlib import Path

import pytest

from lydia.tools.filesystem import (
    ToolError,
    apply_delete,
    apply_write,
    list_dir,
    propose_edit,
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
    backups = list((tmp_path / ".lydia" / "backups").glob("*/a.py"))
    assert len(backups) == 1
    assert backups[0].read_text() == "old\n"


def test_apply_delete_backs_up_and_removes(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("content\n")
    apply_delete(tmp_path, "a.py")
    assert not (tmp_path / "a.py").exists()
    backups = list((tmp_path / ".lydia" / "backups").glob("*/a.py"))
    assert len(backups) == 1


def test_backups_dont_collide_across_directories(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "utils.py").write_text("src version\n")
    (tmp_path / "tests" / "utils.py").write_text("tests version\n")

    apply_write(tmp_path, propose_write(tmp_path, "src/utils.py", "src v2\n"))
    apply_write(tmp_path, propose_write(tmp_path, "tests/utils.py", "tests v2\n"))

    from lydia.tools.filesystem import list_backups
    entries = list_backups(tmp_path)
    paths = sorted(e.path for e in entries)
    assert paths == ["src/utils.py", "tests/utils.py"]


def test_list_and_restore_backup(tmp_path: Path) -> None:
    from lydia.tools.filesystem import list_backups, restore_backup

    (tmp_path / "a.py").write_text("original\n")
    apply_write(tmp_path, propose_write(tmp_path, "a.py", "modified\n"))

    entries = list_backups(tmp_path)
    assert len(entries) == 1
    assert entries[0].path == "a.py"

    proposal = restore_backup(tmp_path, entries[0])
    assert proposal.new_content == "original\n"
    apply_write(tmp_path, proposal)
    assert (tmp_path / "a.py").read_text() == "original\n"


def test_list_backups_empty_when_none_exist(tmp_path: Path) -> None:
    from lydia.tools.filesystem import list_backups
    assert list_backups(tmp_path) == []


def test_write_blocked_outside_root(tmp_path: Path) -> None:
    from lydia.tools.paths import PathEscapesProjectError

    with pytest.raises(PathEscapesProjectError):
        propose_write(tmp_path, "../escape.py", "x")


def test_propose_edit_replaces_unique_match(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def foo():\n    return 1\n")
    proposal = propose_edit(tmp_path, "a.py", "return 1", "return 2")
    assert proposal.is_new_file is False
    assert proposal.new_content == "def foo():\n    return 2\n"
    assert "-    return 1" in proposal.diff
    assert "+    return 2" in proposal.diff


def test_propose_edit_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(ToolError):
        propose_edit(tmp_path, "nope.py", "x", "y")


def test_propose_edit_not_found_raises(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("hello\n")
    with pytest.raises(ToolError):
        propose_edit(tmp_path, "a.py", "goodbye", "hi")


def test_propose_edit_not_unique_without_replace_all_raises(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x = 1\nx = 1\n")
    with pytest.raises(ToolError):
        propose_edit(tmp_path, "a.py", "x = 1", "x = 2")


def test_propose_edit_replace_all_replaces_every_occurrence(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x = 1\nx = 1\n")
    proposal = propose_edit(tmp_path, "a.py", "x = 1", "x = 2", replace_all=True)
    assert proposal.new_content == "x = 2\nx = 2\n"


def test_propose_edit_identical_strings_raises(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("same\n")
    with pytest.raises(ToolError):
        propose_edit(tmp_path, "a.py", "same", "same")


def test_propose_edit_blocked_outside_root(tmp_path: Path) -> None:
    from lydia.tools.paths import PathEscapesProjectError

    with pytest.raises(PathEscapesProjectError):
        propose_edit(tmp_path, "../escape.py", "x", "y")
