"""Tests for session mode switching in the chat REPL.

Only `_apply_mode` and `_handle_slash`'s /mode branch are meaningfully
testable without a real terminal — the Shift-Tab keybinding and live
prompt rendering aren't (see CLAUDE.md's documented pty/tty testing
limitation for this REPL).
"""

from pathlib import Path

from lydia.cli.chat import VALID_MODES, ChatSession, _apply_mode, _handle_slash
from lydia.config.settings import LydiaConfig


class _FakeClient:
    def list_models(self):
        return []


def make_session(tmp_path: Path, mode: str = "ask") -> ChatSession:
    config = LydiaConfig(mode=mode)
    return ChatSession(config, _FakeClient(), "fake-model", summary=None, project_root=tmp_path)


def test_apply_mode_accepts_valid_modes(tmp_path: Path) -> None:
    session = make_session(tmp_path)
    for mode in VALID_MODES:
        assert _apply_mode(session, mode) is True
        assert session.config.mode == mode


def test_apply_mode_rejects_unknown_mode(tmp_path: Path) -> None:
    session = make_session(tmp_path)
    assert _apply_mode(session, "yolo") is False
    assert session.config.mode == "ask"  # unchanged


def test_mode_slash_command_shows_current_mode(tmp_path: Path, capsys) -> None:
    session = make_session(tmp_path, mode="plan")
    _handle_slash("/mode", session)
    assert "plan" in capsys.readouterr().out


def test_mode_slash_command_switches_mode(tmp_path: Path) -> None:
    session = make_session(tmp_path)
    _handle_slash("/mode auto", session)
    assert session.config.mode == "auto"


def test_mode_slash_command_rejects_typo(tmp_path: Path, capsys) -> None:
    session = make_session(tmp_path)
    _handle_slash("/mode atuo", session)
    assert session.config.mode == "ask"  # unchanged
    assert "Unknown mode" in capsys.readouterr().out


def test_send_rebuilds_system_prompt_for_current_mode(tmp_path: Path) -> None:
    session = make_session(tmp_path, mode="ask")
    assert "plan mode" not in session.system_prompt
    session.config.mode = "plan"
    session.system_prompt = session._build_system_prompt()
    assert "plan mode" in session.system_prompt
