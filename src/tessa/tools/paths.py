"""Path safety shared by every tool that touches the filesystem.

Every tool receives paths as strings from the model and must resolve them
relative to the project root, refusing anything that escapes it (via `..`,
absolute paths, or symlinks) so a confused or adversarial model can't touch
files outside the project.
"""

from __future__ import annotations

from pathlib import Path


class PathEscapesProjectError(Exception):
    def __init__(self, requested: str) -> None:
        super().__init__(f"'{requested}' is outside the project root and was refused.")


def resolve_within(root: Path, relative: str) -> Path:
    """Resolve *relative* against *root*, raising if it escapes the root."""
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        raise PathEscapesProjectError(relative) from None
    return candidate
