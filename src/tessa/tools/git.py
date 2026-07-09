"""Thin, safe wrappers around the git CLI.

Every function shells out to the user's own `git`, inside the project root,
with an explicit argument list (never a shell string) so there is no
injection risk from file paths or commit messages.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from tessa.tools.filesystem import ToolError


def _run(root: Path, *args: str, timeout: int = 30) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        raise ToolError("git is not installed or not on PATH.") from None
    except subprocess.TimeoutExpired:
        raise ToolError(f"git {args[0]} timed out after {timeout}s.") from None
    if result.returncode != 0:
        raise ToolError((result.stderr or result.stdout or f"git {args[0]} failed").strip())
    return result.stdout.strip()


def is_repo(root: Path) -> bool:
    try:
        _run(root, "rev-parse", "--is-inside-work-tree")
        return True
    except ToolError:
        return False


def status(root: Path) -> str:
    output = _run(root, "status", "--short", "--branch")
    return output or "Clean working tree, nothing to commit."


def diff(root: Path, staged: bool = False, path: str | None = None) -> str:
    args = ["diff"]
    if staged:
        args.append("--staged")
    if path:
        args += ["--", path]
    output = _run(root, *args)
    return output or "No changes."


def add(root: Path, paths: list[str]) -> str:
    if not paths:
        raise ToolError("No paths given to stage.")
    _run(root, "add", "--", *paths)
    return f"Staged: {', '.join(paths)}"


def commit(root: Path, message: str) -> str:
    if not message.strip():
        raise ToolError("Commit message cannot be empty.")
    staged = _run(root, "diff", "--staged", "--name-only")
    if not staged:
        raise ToolError("Nothing staged. Use git_add first.")
    _run(root, "commit", "-m", message)
    sha = _run(root, "rev-parse", "--short", "HEAD")
    return f"Committed {sha}: {message.splitlines()[0]}"


def push(root: Path, remote: str = "origin", branch: str | None = None) -> str:
    args = ["push", remote]
    if branch:
        args.append(branch)
    return _run(root, *args, timeout=60) or f"Pushed to {remote}."


def current_branch(root: Path) -> str:
    return _run(root, "branch", "--show-current")


def log(root: Path, count: int = 10) -> str:
    output = _run(root, "log", f"-{count}", "--oneline")
    return output or "No commits yet."
