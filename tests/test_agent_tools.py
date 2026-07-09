"""Tests for the tool registry's confirmation and permission behaviour."""

from pathlib import Path

import pytest

from tessa.agent.tools import ToolContext, build_registry
from tessa.config.settings import TessaConfig


def get(name: str):
    return next(t for t in build_registry() if t.name == name)


def ctx(tmp_path: Path, confirm_result: bool = True, permission_mode: str = "ask") -> ToolContext:
    config = TessaConfig(permission_mode=permission_mode)
    return ToolContext(root=tmp_path, config=config, confirm=lambda req: confirm_result)


def test_read_file_is_safe_and_needs_no_confirm(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x = 1\n")
    result = get("read_file").handler({"path": "a.py"}, ctx(tmp_path, confirm_result=False))
    assert result.ok
    assert "x = 1" in result.content


def test_write_file_declined_does_not_touch_disk(tmp_path: Path) -> None:
    result = get("write_file").handler(
        {"path": "new.py", "content": "print(1)\n"}, ctx(tmp_path, confirm_result=False)
    )
    assert not result.ok
    assert not (tmp_path / "new.py").exists()


def test_write_file_approved_writes_to_disk(tmp_path: Path) -> None:
    result = get("write_file").handler(
        {"path": "new.py", "content": "print(1)\n"}, ctx(tmp_path, confirm_result=True)
    )
    assert result.ok
    assert (tmp_path / "new.py").read_text() == "print(1)\n"


def test_delete_file_declined_keeps_file(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x\n")
    get("delete_file").handler({"path": "a.py"}, ctx(tmp_path, confirm_result=False))
    assert (tmp_path / "a.py").exists()


def test_run_command_deny_mode_never_executes(tmp_path: Path) -> None:
    calls = []
    context = ToolContext(
        root=tmp_path,
        config=TessaConfig(permission_mode="deny"),
        confirm=lambda req: calls.append(req) or True,
    )
    result = get("run_command").handler({"command": "echo hi"}, context)
    assert not result.ok
    assert calls == []  # never even asked


def test_run_command_auto_mode_runs_safe_without_confirm(tmp_path: Path) -> None:
    asked = []
    context = ToolContext(
        root=tmp_path,
        config=TessaConfig(permission_mode="auto"),
        confirm=lambda req: asked.append(req) or True,
    )
    result = get("run_command").handler({"command": "echo hi"}, context)
    assert result.ok
    assert asked == []


def test_run_command_auto_mode_still_confirms_dangerous(tmp_path: Path) -> None:
    asked = []
    context = ToolContext(
        root=tmp_path,
        config=TessaConfig(permission_mode="auto"),
        confirm=lambda req: asked.append(req) or True,
    )
    get("run_command").handler({"command": "rm -rf ./build"}, context)
    assert len(asked) == 1
    assert asked[0].danger is True


def test_run_command_ask_mode_confirms_even_safe_commands(tmp_path: Path) -> None:
    asked = []
    context = ToolContext(
        root=tmp_path,
        config=TessaConfig(permission_mode="ask"),
        confirm=lambda req: asked.append(req) or True,
    )
    get("run_command").handler({"command": "echo hi"}, context)
    assert len(asked) == 1


def test_git_commit_requires_confirmation(tmp_path: Path) -> None:
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, check=True)
    (tmp_path / "a.txt").write_text("hi\n")
    get("git_add").handler({"paths": ["a.txt"]}, ctx(tmp_path))

    declined = get("git_commit").handler({"message": "add a"}, ctx(tmp_path, confirm_result=False))
    assert not declined.ok

    approved = get("git_commit").handler({"message": "add a"}, ctx(tmp_path, confirm_result=True))
    assert approved.ok
