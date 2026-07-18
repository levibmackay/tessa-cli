"""Tests for voice mode CLI commands (no real models, mic, or launchctl invoked)."""

from typer.testing import CliRunner

from lydia.cli import main as cli_main

runner = CliRunner()


def test_listen_status_reports_disabled(monkeypatch):
    monkeypatch.setattr("lydia.cli.scheduler.listen_enabled", lambda: False)
    result = runner.invoke(cli_main.app, ["listen", "status"])
    assert result.exit_code == 0 and "not" in result.output.lower()


def test_listen_enable_calls_scheduler(monkeypatch):
    called = {}
    monkeypatch.setattr(
        "lydia.cli.scheduler.enable_listen",
        lambda **kw: called.setdefault("yes", True) or __import__("pathlib").Path("/tmp/x"),
    )
    result = runner.invoke(cli_main.app, ["listen", "enable"])
    assert result.exit_code == 0 and called


def test_listen_disable_calls_scheduler(monkeypatch):
    called = {}

    def mock_disable(**kw):
        called["yes"] = True

    monkeypatch.setattr("lydia.cli.scheduler.disable_listen", mock_disable)
    result = runner.invoke(cli_main.app, ["listen", "disable"])
    assert result.exit_code == 0 and called
