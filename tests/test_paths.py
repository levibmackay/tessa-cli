"""Path escape protection shared by all filesystem-touching tools."""

from pathlib import Path

import pytest

from tessa.tools.paths import PathEscapesProjectError, resolve_within


def test_resolves_relative_path(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    resolved = resolve_within(tmp_path, "src/app.py")
    assert resolved == (tmp_path / "src" / "app.py").resolve()


def test_blocks_parent_traversal(tmp_path: Path) -> None:
    with pytest.raises(PathEscapesProjectError):
        resolve_within(tmp_path, "../outside.txt")


def test_blocks_absolute_path_outside_root(tmp_path: Path) -> None:
    with pytest.raises(PathEscapesProjectError):
        resolve_within(tmp_path, "/etc/passwd")


def test_allows_dot(tmp_path: Path) -> None:
    assert resolve_within(tmp_path, ".") == tmp_path.resolve()
