"""Tests for the `lydia briefing` command (no real Ollama/network needed)."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from lydia.cli import briefing
from lydia.cli.main import app
from lydia.config.settings import LydiaConfig
from lydia.llm.types import ChatChunk, ModelInfo, ToolCall

runner = CliRunner()


class _FakeClient:
    def __init__(self, responses: list[list[ChatChunk]]) -> None:
        self.responses = responses
        self.calls: list[dict] = []

    def is_alive(self) -> bool:
        return True

    def list_models(self) -> list[ModelInfo]:
        return [ModelInfo(name="fake-model", size_bytes=1)]

    def has_model(self, name: str) -> bool:
        return name == "fake-model"

    def chat_stream(self, **kwargs):
        self.calls.append(kwargs)
        return iter(self.responses[len(self.calls) - 1])

    def close(self) -> None:
        pass

    def __enter__(self) -> "_FakeClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


class _DeadClient(_FakeClient):
    def is_alive(self) -> bool:
        return False


@pytest.fixture(autouse=True)
def isolated_briefing_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    fake_file = tmp_path / "briefing.json"
    monkeypatch.setattr(briefing, "BRIEFING_FILE", fake_file)
    return fake_file


def test_assistant_registry_only_has_assistant_tools() -> None:
    names = {spec.name for spec in briefing._assistant_registry()}
    assert names == {"check_email", "check_canvas", "check_stocks", "check_news"}


def test_save_and_load_briefing_roundtrip() -> None:
    assert briefing.load_briefing() is None
    briefing._save_briefing("- Nothing due today.")
    saved = briefing.load_briefing()
    assert saved is not None
    assert saved["text"] == "- Nothing due today."
    assert "generated_at" in saved


def test_run_briefing_unreachable_backend_returns_error() -> None:
    exit_code = briefing.run_briefing(LydiaConfig(), _client_factory=lambda config: _DeadClient([]))
    assert exit_code == 1
    assert briefing.load_briefing() is None


def test_run_briefing_calls_tools_and_saves_result(monkeypatch: pytest.MonkeyPatch) -> None:
    import lydia.connectors.stocks as stocks_mod

    fake_snapshot = [stocks_mod.IndexSnapshot(symbol="^GSPC", name="S&P 500", price=100.0, change_pct=0.5)]
    monkeypatch.setattr(stocks_mod, "get_market_summary", lambda: fake_snapshot)

    client = _FakeClient([
        [ChatChunk(tool_calls=[ToolCall(name="check_stocks", arguments={})], done=True)],
        [ChatChunk(content="- Market: S&P 500 up 0.5%.", done=True)],
    ])
    exit_code = briefing.run_briefing(LydiaConfig(), _client_factory=lambda config: client)
    assert exit_code == 0
    saved = briefing.load_briefing()
    assert saved is not None
    assert "S&P 500" in saved["text"]


def test_show_briefing_cli_without_prior_run() -> None:
    result = runner.invoke(app, ["briefing", "show"])
    assert result.exit_code == 1
    assert "No briefing yet" in result.stdout


def test_show_briefing_cli_after_saving() -> None:
    briefing._save_briefing("- All caught up.")
    result = runner.invoke(app, ["briefing", "show"])
    assert result.exit_code == 0
    assert "All caught up" in result.stdout
