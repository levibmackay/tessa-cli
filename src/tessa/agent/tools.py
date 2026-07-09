"""The tool registry: what Tessa can do, and how dangerous each action is.

Each ToolSpec pairs a JSON-schema definition (sent to the model so it knows
what it can call) with a handler that performs the real work by delegating
to `tessa.tools.*`. Handlers may raise `ToolError`; the agent loop turns
that into a message the model can read and react to.

Risk levels:
    safe    — runs immediately, no confirmation (reads, git status/diff/add)
    confirm — always shown to the user for a yes/no before running
              (file writes/deletes, git commit, git push)
    command — arbitrary shell; policy decided by config.permission_mode
              combined with tessa.tools.terminal.classify_command
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal

from tessa.config.settings import TessaConfig
from tessa.tools import filesystem, git
from tessa.tools.terminal import classify_command, run_command

Risk = Literal["safe", "confirm", "command"]

MAX_TOOL_OUTPUT_CHARS = 6000


@dataclass
class ConfirmRequest:
    """Something a tool wants to do that needs the user's yes/no."""

    title: str
    detail: str
    danger: bool = False


@dataclass
class ToolContext:
    root: Path
    config: TessaConfig
    confirm: Callable[[ConfirmRequest], bool]


@dataclass
class ToolResult:
    ok: bool
    content: str  # fed back to the model verbatim
    summary: str = ""  # short line for the console; falls back to content

    def display(self) -> str:
        return self.summary or _truncate(self.content, 200)


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    risk: Risk
    handler: Callable[[dict[str, Any], ToolContext], ToolResult]

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


def _truncate(text: str, limit: int = MAX_TOOL_OUTPUT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... [truncated, {len(text) - limit} more characters]"


def _declined(what: str) -> ToolResult:
    return ToolResult(
        ok=False,
        content=(
            f"DECLINED. The user said no to {what}. Nothing was changed on disk or in git. "
            "Do not tell the user this action succeeded or was applied — it was not. "
            "Explain that it was declined and ask how they'd like to proceed."
        ),
        summary="declined",
    )


# -- filesystem ---------------------------------------------------------


def _read_file(args: dict, ctx: ToolContext) -> ToolResult:
    content = filesystem.read_file(ctx.root, args["path"], args.get("start_line", 1), args.get("end_line"))
    return ToolResult(ok=True, content=_truncate(content), summary=f"read {args['path']}")


def _list_dir(args: dict, ctx: ToolContext) -> ToolResult:
    content = filesystem.list_dir(ctx.root, args.get("path", "."))
    return ToolResult(ok=True, content=content, summary=f"listed {args.get('path', '.')}")


def _search_code(args: dict, ctx: ToolContext) -> ToolResult:
    content = filesystem.search_code(ctx.root, args["pattern"], args.get("path", "."))
    return ToolResult(ok=True, content=_truncate(content), summary=f"searched for '{args['pattern']}'")


def _write_file(args: dict, ctx: ToolContext) -> ToolResult:
    path, content = args["path"], args["content"]
    proposal = filesystem.propose_write(ctx.root, path, content)
    verb = "Create" if proposal.is_new_file else "Update"
    approved = ctx.confirm(ConfirmRequest(title=f"{verb} {path}", detail=proposal.diff))
    if not approved:
        return _declined(f"writing {path}")
    message = filesystem.apply_write(ctx.root, proposal)
    return ToolResult(ok=True, content=message, summary=message)


def _delete_file(args: dict, ctx: ToolContext) -> ToolResult:
    path = args["path"]
    approved = ctx.confirm(ConfirmRequest(
        title=f"Delete {path}",
        detail=f"This will permanently delete {path} (a backup is kept in .tessa/backups/).",
        danger=True,
    ))
    if not approved:
        return _declined(f"deleting {path}")
    message = filesystem.apply_delete(ctx.root, path)
    return ToolResult(ok=True, content=message, summary=message)


# -- terminal -------------------------------------------------------------


def _run_command(args: dict, ctx: ToolContext) -> ToolResult:
    command = args["command"]
    risk = classify_command(command)
    mode = ctx.config.permission_mode
    if mode == "deny":
        return ToolResult(
            ok=False,
            content="Command execution is disabled (permission_mode=deny). "
            "Tell the user what you'd like to run and let them run it themselves.",
            summary="blocked by permission_mode=deny",
        )
    needs_confirm = mode == "ask" or risk == "dangerous"
    if needs_confirm:
        approved = ctx.confirm(ConfirmRequest(
            title=f"Run: {command}",
            detail=command,
            danger=(risk == "dangerous"),
        ))
        if not approved:
            return _declined(f"running `{command}`")
    result = run_command(command, ctx.root)
    body = f"exit code: {result.returncode}\n"
    if result.stdout.strip():
        body += f"stdout:\n{result.stdout.strip()}\n"
    if result.stderr.strip():
        body += f"stderr:\n{result.stderr.strip()}\n"
    summary = f"ran `{command}` (exit {result.returncode})"
    return ToolResult(ok=result.success, content=_truncate(body), summary=summary)


# -- git --------------------------------------------------------------------


def _git_status(args: dict, ctx: ToolContext) -> ToolResult:
    return ToolResult(ok=True, content=git.status(ctx.root), summary="checked git status")


def _git_diff(args: dict, ctx: ToolContext) -> ToolResult:
    content = git.diff(ctx.root, staged=args.get("staged", False), path=args.get("path"))
    return ToolResult(ok=True, content=_truncate(content), summary="checked git diff")


def _git_add(args: dict, ctx: ToolContext) -> ToolResult:
    message = git.add(ctx.root, args["paths"])
    return ToolResult(ok=True, content=message, summary=message)


def _git_commit(args: dict, ctx: ToolContext) -> ToolResult:
    message = args["message"]
    approved = ctx.confirm(ConfirmRequest(title="Commit", detail=message))
    if not approved:
        return _declined("creating this commit")
    result = git.commit(ctx.root, message)
    return ToolResult(ok=True, content=result, summary=result)


def _git_push(args: dict, ctx: ToolContext) -> ToolResult:
    remote, branch = args.get("remote", "origin"), args.get("branch")
    label = f"{remote}/{branch}" if branch else remote
    approved = ctx.confirm(ConfirmRequest(
        title=f"Push to {label}",
        detail=f"This pushes local commits to {label}, a shared/remote location.",
        danger=True,
    ))
    if not approved:
        return _declined(f"pushing to {label}")
    result = git.push(ctx.root, remote, branch)
    return ToolResult(ok=True, content=result, summary=result)


def build_registry() -> list[ToolSpec]:
    return [
        ToolSpec(
            "read_file", "Read a text file from the project, with line numbers.",
            {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path relative to the project root"},
                    "start_line": {"type": "integer", "description": "1-based first line (optional)"},
                    "end_line": {"type": "integer", "description": "1-based last line (optional)"},
                },
                "required": ["path"],
            },
            "safe", _read_file,
        ),
        ToolSpec(
            "list_dir", "List the files and subdirectories directly inside a directory.",
            {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory relative to the project root, default '.'"},
                },
            },
            "safe", _list_dir,
        ),
        ToolSpec(
            "search_code", "Search project files for a substring and return matching file:line:text.",
            {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Text to search for"},
                    "path": {"type": "string", "description": "Restrict search to this file or directory, default '.'"},
                },
                "required": ["pattern"],
            },
            "safe", _search_code,
        ),
        ToolSpec(
            "write_file",
            "Create a new file or overwrite an existing one with full new content. "
            "Always shows a diff and asks the user to approve before writing.",
            {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path relative to the project root"},
                    "content": {"type": "string", "description": "The complete new file content"},
                },
                "required": ["path", "content"],
            },
            "confirm", _write_file,
        ),
        ToolSpec(
            "delete_file", "Permanently delete a file (a backup is kept). Asks the user to approve first.",
            {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "Path relative to the project root"}},
                "required": ["path"],
            },
            "confirm", _delete_file,
        ),
        ToolSpec(
            "run_command",
            "Run a shell command in the project root and return its output. "
            "Destructive commands are always confirmed with the user first.",
            {
                "type": "object",
                "properties": {"command": {"type": "string", "description": "The shell command to run"}},
                "required": ["command"],
            },
            "command", _run_command,
        ),
        ToolSpec(
            "git_status", "Show the working tree status (changed/staged/untracked files).",
            {"type": "object", "properties": {}}, "safe", _git_status,
        ),
        ToolSpec(
            "git_diff", "Show unstaged (or staged) changes as a unified diff.",
            {
                "type": "object",
                "properties": {
                    "staged": {"type": "boolean", "description": "Show staged changes instead of unstaged"},
                    "path": {"type": "string", "description": "Restrict the diff to this path"},
                },
            },
            "safe", _git_diff,
        ),
        ToolSpec(
            "git_add", "Stage files for commit.",
            {
                "type": "object",
                "properties": {"paths": {"type": "array", "items": {"type": "string"}, "description": "Paths to stage"}},
                "required": ["paths"],
            },
            "safe", _git_add,
        ),
        ToolSpec(
            "git_commit", "Commit currently staged changes. Always confirmed with the user first.",
            {
                "type": "object",
                "properties": {"message": {"type": "string", "description": "Commit message"}},
                "required": ["message"],
            },
            "confirm", _git_commit,
        ),
        ToolSpec(
            "git_push", "Push committed changes to a remote. Always confirmed with the user first.",
            {
                "type": "object",
                "properties": {
                    "remote": {"type": "string", "description": "Remote name, default 'origin'"},
                    "branch": {"type": "string", "description": "Branch name, default the current branch"},
                },
            },
            "confirm", _git_push,
        ),
    ]
