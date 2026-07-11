"""CLI tests for `lydia briefing schedule enable/disable`.

These monkeypatch `scheduler.enable`/`disable` themselves (already covered
in isolation by test_scheduler.py) so the CLI command never shells out to
the real `launchctl` on the machine running the tests.
"""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from lydia.cli import scheduler
from lydia.cli.main import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("lydia.config.settings.GLOBAL_DIR", tmp_path / "home" / ".lydia")


def test_schedule_enable_writes_config(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    monkeypatch.setattr(scheduler, "enable", lambda time_str: calls.append(time_str) or Path("/tmp/fake.plist"))

    result = runner.invoke(app, ["briefing", "schedule", "enable", "--time", "07:30"])
    assert result.exit_code == 0, result.stdout
    assert calls == ["07:30"]

    from lydia.config.settings import load_config
    config = load_config()
    assert config.briefing_schedule_enabled is True
    assert config.briefing_schedule_time == "07:30"


def test_schedule_enable_surfaces_schedule_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(time_str: str) -> Path:
        raise scheduler.ScheduleError("launchctl load failed: boom")

    monkeypatch.setattr(scheduler, "enable", boom)
    result = runner.invoke(app, ["briefing", "schedule", "enable", "--time", "07:30"])
    assert result.exit_code == 1


def test_schedule_disable_writes_config(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    monkeypatch.setattr(scheduler, "disable", lambda: calls.append(True))

    result = runner.invoke(app, ["briefing", "schedule", "disable"])
    assert result.exit_code == 0, result.stdout
    assert calls == [True]

    from lydia.config.settings import load_config
    assert load_config().briefing_schedule_enabled is False
