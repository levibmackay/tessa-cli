"""CLI-level tests for commands that don't need a running Ollama daemon:
analyze, config show/set, init, restore list/apply, and --version."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tessa import __version__
from tessa.cli.main import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def isolated_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_analyze_on_empty_project(tmp_path: Path) -> None:
    result = runner.invoke(app, ["analyze"])
    assert result.exit_code == 0
    assert "Unknown" in result.stdout


def test_analyze_detects_python_project(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    (tmp_path / "app.py").write_text("x = 1\n")
    result = runner.invoke(app, ["analyze"])
    assert result.exit_code == 0
    assert "Python" in result.stdout


def test_analyze_missing_directory_fails() -> None:
    result = runner.invoke(app, ["analyze", "does-not-exist"])
    assert result.exit_code == 1


def test_init_creates_project_config(tmp_path: Path) -> None:
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0
    config_file = tmp_path / ".tessa" / "config.json"
    assert config_file.exists()
    assert json.loads(config_file.read_text()) == {}
    gitignore = (tmp_path / ".tessa" / ".gitignore").read_text()
    assert "history/" in gitignore
    assert "backups/" in gitignore
    assert "index.sqlite3" in gitignore


def test_init_is_idempotent(tmp_path: Path) -> None:
    runner.invoke(app, ["init"])
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0
    assert "Already initialized" in result.stdout


def test_config_show_reports_defaults() -> None:
    result = runner.invoke(app, ["config", "show"])
    assert result.exit_code == 0
    assert "temperature" in result.stdout


def test_config_set_and_show_global(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_home = tmp_path / "home"
    monkeypatch.setattr("tessa.config.settings.GLOBAL_DIR", fake_home / ".tessa")
    set_result = runner.invoke(app, ["config", "set", "temperature", "0.3"])
    assert set_result.exit_code == 0
    show_result = runner.invoke(app, ["config", "show"])
    assert "temperature = 0.3" in show_result.stdout


def test_config_set_unknown_key_fails() -> None:
    result = runner.invoke(app, ["config", "set", "not_a_real_key", "value"])
    assert result.exit_code == 1


def test_config_set_project_requires_project_root(tmp_path: Path) -> None:
    result = runner.invoke(app, ["config", "set", "model", "x", "--project"])
    assert result.exit_code == 1
    assert "Not inside a project" in result.stdout


def test_restore_list_empty(tmp_path: Path) -> None:
    result = runner.invoke(app, ["restore", "list"])
    assert result.exit_code == 0
    assert "No backups" in result.stdout


def test_restore_apply_invalid_index_fails(tmp_path: Path) -> None:
    result = runner.invoke(app, ["restore", "apply", "1"])
    assert result.exit_code == 1


def test_restore_list_and_apply(tmp_path: Path) -> None:
    from tessa.tools.filesystem import apply_write, propose_write

    (tmp_path / "a.py").write_text("original\n")
    apply_write(tmp_path, propose_write(tmp_path, "a.py", "modified\n"))

    list_result = runner.invoke(app, ["restore", "list"])
    assert "a.py" in list_result.stdout

    apply_result = runner.invoke(app, ["restore", "apply", "1"], input="y\n")
    assert apply_result.exit_code == 0
    assert (tmp_path / "a.py").read_text() == "original\n"
