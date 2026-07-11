"""Filesystem tools: read, list, search, and write with diff preview.

Reads never touch disk destructively so they run without confirmation.
Writes and deletes never happen blind — callers must show `WriteProposal` /
the deletion path to the user and only call `apply_write` / `apply_delete`
after they say yes. A timestamped backup is kept for every write so a bad
edit is always recoverable.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from pathlib import Path

from lydia.context.scanner import IGNORED_DIRS
from lydia.tools.paths import resolve_within

MAX_READ_BYTES = 300_000  # guard against dumping huge binaries/logs into context
MAX_SEARCH_MATCHES = 100
BACKUP_DIR_NAME = ".lydia/backups"


class ToolError(Exception):
    """A tool could not complete the request; message is shown to the model."""


@dataclass
class WriteProposal:
    path: str
    diff: str
    is_new_file: bool
    old_content: str | None
    new_content: str


def read_file(root: Path, path: str, start_line: int = 1, end_line: int | None = None) -> str:
    """Return file content with 1-based line numbers, like `cat -n`."""
    target = resolve_within(root, path)
    if not target.is_file():
        raise ToolError(f"No such file: {path}")
    try:
        data = target.read_bytes()
    except OSError as exc:
        raise ToolError(f"Could not read {path}: {exc}") from exc
    if len(data) > MAX_READ_BYTES:
        raise ToolError(
            f"{path} is {len(data):,} bytes, too large to read in full. "
            "Use search_code to find the relevant section, or request a line range."
        )
    text = data.decode("utf-8", errors="replace")
    lines = text.splitlines()
    end = end_line if end_line is not None else len(lines)
    selected = lines[max(start_line - 1, 0):end]
    numbered = "\n".join(f"{i:>5}\t{line}" for i, line in enumerate(selected, start=start_line))
    return numbered or "(empty file)"


def list_dir(root: Path, path: str = ".") -> str:
    """List immediate children of a directory, directories first."""
    target = resolve_within(root, path)
    if not target.is_dir():
        raise ToolError(f"No such directory: {path}")
    entries = sorted(
        (e for e in target.iterdir() if e.name not in IGNORED_DIRS),
        key=lambda e: (e.is_file(), e.name.lower()),
    )
    if not entries:
        return "(empty directory)"
    return "\n".join(f"{'  ' if e.is_dir() else '  '}{e.name}{'/' if e.is_dir() else ''}" for e in entries)


def search_code(root: Path, pattern: str, path: str = ".", case_sensitive: bool = False) -> str:
    """Plain-substring search across text files under *path*. Returns file:line:text."""
    target = resolve_within(root, path)
    if not target.exists():
        raise ToolError(f"No such path: {path}")
    needle = pattern if case_sensitive else pattern.lower()
    matches: list[str] = []
    files = [target] if target.is_file() else _walk_files(target)
    for file_path in files:
        if len(matches) >= MAX_SEARCH_MATCHES:
            break
        try:
            text = file_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for line_no, line in enumerate(text.splitlines(), start=1):
            haystack = line if case_sensitive else line.lower()
            if needle in haystack:
                relative = file_path.relative_to(root)
                matches.append(f"{relative}:{line_no}:{line.strip()}")
                if len(matches) >= MAX_SEARCH_MATCHES:
                    break
    if not matches:
        return f"No matches for '{pattern}' under {path}"
    suffix = "\n(truncated)" if len(matches) >= MAX_SEARCH_MATCHES else ""
    return "\n".join(matches) + suffix


def _walk_files(directory: Path):
    stack = [directory]
    while stack:
        current = stack.pop()
        try:
            entries = list(current.iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry.name in IGNORED_DIRS:
                continue
            if entry.is_dir():
                stack.append(entry)
            elif entry.is_file():
                yield entry


def _unified_diff(old_content: str | None, new_content: str, path: str, is_new: bool) -> str:
    diff = "".join(
        difflib.unified_diff(
            (old_content.splitlines(keepends=True) if old_content is not None else []),
            new_content.splitlines(keepends=True),
            fromfile=f"a/{path}" if not is_new else "/dev/null",
            tofile=f"b/{path}",
        )
    )
    if not diff and not is_new:
        diff = "(no changes — file content is identical)"
    return diff


def propose_write(root: Path, path: str, content: str) -> WriteProposal:
    """Build a diff for a create-or-modify without touching disk."""
    target = resolve_within(root, path)
    is_new = not target.exists()
    old_content = None if is_new else target.read_text(encoding="utf-8", errors="replace")
    diff = _unified_diff(old_content, content, path, is_new)
    return WriteProposal(path=path, diff=diff, is_new_file=is_new, old_content=old_content, new_content=content)


def propose_edit(root: Path, path: str, old_string: str, new_string: str, replace_all: bool = False) -> WriteProposal:
    """Build a diff for a targeted find/replace within an existing file, without touching disk.

    Unlike propose_write, this never creates a file — it only edits one
    that already exists, and requires old_string to appear exactly once
    unless replace_all is set, so the model can't accidentally rewrite the
    wrong occurrence (or all of them) without saying so.
    """
    target = resolve_within(root, path)
    if not target.is_file():
        raise ToolError(f"No such file: {path}")
    old_content = target.read_text(encoding="utf-8", errors="replace")
    if old_string == new_string:
        raise ToolError("old_string and new_string are identical — no change to make.")
    count = old_content.count(old_string)
    if count == 0:
        raise ToolError(f"old_string not found in {path}. Re-read the file and match the text exactly.")
    if count > 1 and not replace_all:
        raise ToolError(
            f"old_string appears {count} times in {path}; it must be unique. "
            "Add more surrounding context to pin down one occurrence, or pass replace_all=true "
            "to replace every occurrence."
        )
    new_content = old_content.replace(old_string, new_string)
    diff = _unified_diff(old_content, new_content, path, is_new=False)
    return WriteProposal(path=path, diff=diff, is_new_file=False, old_content=old_content, new_content=new_content)


def apply_write(root: Path, proposal: WriteProposal) -> str:
    """Write the proposed content to disk, backing up any prior version first."""
    target = resolve_within(root, proposal.path)
    if proposal.old_content is not None:
        _backup(root, target, proposal.old_content)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(proposal.new_content, encoding="utf-8")
    action = "Created" if proposal.is_new_file else "Updated"
    return f"{action} {proposal.path}"


def apply_delete(root: Path, path: str) -> str:
    target = resolve_within(root, path)
    if not target.is_file():
        raise ToolError(f"No such file: {path}")
    _backup(root, target, target.read_text(encoding="utf-8", errors="replace"))
    target.unlink()
    return f"Deleted {path}"


def _backup(root: Path, target: Path, old_content: str) -> None:
    from datetime import datetime, timezone

    # A timestamped directory mirroring the file's own relative path, so
    # two files with the same name in different directories can't collide,
    # and restore_backup can reconstruct the original location exactly.
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    relative = target.relative_to(root)
    backup_path = root / BACKUP_DIR_NAME / stamp / relative
    try:
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        backup_path.write_text(old_content, encoding="utf-8")
    except OSError:
        pass  # backups are best-effort; never block the edit over this


@dataclass
class BackupEntry:
    stamp: str
    path: str  # relative to the project root
    backup_file: Path


def list_backups(root: Path) -> list[BackupEntry]:
    """All backups, newest first."""
    backups_dir = root / BACKUP_DIR_NAME
    if not backups_dir.is_dir():
        return []
    entries: list[BackupEntry] = []
    for stamp_dir in sorted((d for d in backups_dir.iterdir() if d.is_dir()), reverse=True):
        for file_path in _walk_files(stamp_dir):
            relative = file_path.relative_to(stamp_dir)
            entries.append(BackupEntry(stamp=stamp_dir.name, path=str(relative), backup_file=file_path))
    return entries


def restore_backup(root: Path, entry: BackupEntry) -> WriteProposal:
    """Build a write proposal that restores a backup's content to its original path."""
    content = entry.backup_file.read_text(encoding="utf-8", errors="replace")
    return propose_write(root, entry.path, content)
