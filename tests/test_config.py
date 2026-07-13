"""Tests for the layered config system."""

import json
from pathlib import Path

import pytest

from lydia.config import settings
from lydia.config.settings import LydiaConfig, coerce_value, load_config, save_config_value


@pytest.fixture
def isolated_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """Point the global config at a temp dir and build a fake project."""
    global_dir = tmp_path / "home" / ".lydia"
    monkeypatch.setattr(settings, "GLOBAL_DIR", global_dir)
    project = tmp_path / "project"
    (project / ".lydia").mkdir(parents=True)
    return global_dir, project


def test_defaults() -> None:
    config = LydiaConfig()
    assert config.model is None
    assert config.temperature == 0.7
    assert config.ollama_host == "http://localhost:11434"


def test_project_overrides_global(isolated_dirs: tuple[Path, Path]) -> None:
    global_dir, project = isolated_dirs
    global_dir.mkdir(parents=True)
    (global_dir / "config.json").write_text(json.dumps({"model": "global-model", "temperature": 0.2}))
    (project / ".lydia" / "config.json").write_text(json.dumps({"model": "project-model"}))

    config = load_config(project_root=project)
    assert config.model == "project-model"  # project wins
    assert config.temperature == 0.2  # global still applies


def test_unknown_keys_ignored(isolated_dirs: tuple[Path, Path]) -> None:
    _, project = isolated_dirs
    (project / ".lydia" / "config.json").write_text(json.dumps({"bogus": 1, "num_ctx": 4096}))
    config = load_config(project_root=project)
    assert config.num_ctx == 4096
    assert not hasattr(config, "bogus")


def test_corrupt_config_falls_back_to_defaults(isolated_dirs: tuple[Path, Path]) -> None:
    _, project = isolated_dirs
    (project / ".lydia" / "config.json").write_text("{not json")
    config = load_config(project_root=project)
    assert config.temperature == 0.7


def test_save_and_coerce(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    save_config_value("temperature", coerce_value("temperature", "0.3"), path)
    save_config_value("model", coerce_value("model", "qwen3.5:9b"), path)
    data = json.loads(path.read_text())
    assert data == {"temperature": 0.3, "model": "qwen3.5:9b"}


def test_save_rejects_unknown_key(tmp_path: Path) -> None:
    with pytest.raises(KeyError):
        save_config_value("nope", "x", tmp_path / "config.json")

def test_save_rejects_unknown_key(tmp_path: Path) -> None:
    with pytest.raises(KeyError):
        save_config_value("nope", "x", tmp_path / "config.json")


def test_boolean_coercion(tmp_path: Path) -> None:
    path = tmp_path / "config.json"

    save_config_value(
        "briefing_schedule_enabled",
        coerce_value("briefing_schedule_enabled", "false"),
        path,
    )

    data = json.loads(path.read_text())

    assert data["briefing_schedule_enabled"] is False
