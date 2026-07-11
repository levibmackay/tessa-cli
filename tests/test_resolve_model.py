"""Tests for model resolution and its tool-calling capability warning."""

import pytest

from lydia.cli import chat
from lydia.cli.chat import resolve_model
from lydia.config.settings import LydiaConfig
from lydia.llm.types import ModelInfo


class _FakeClient:
    def __init__(self, models: list[ModelInfo]) -> None:
        self._models = models

    def list_models(self) -> list[ModelInfo]:
        return self._models


def test_resolve_explicit_bad_model_warns(monkeypatch: pytest.MonkeyPatch) -> None:
    warnings: list[str] = []
    monkeypatch.setattr(chat.ui, "print_warning", warnings.append)
    client = _FakeClient([ModelInfo(name="qwen2.5-coder:7b", size_bytes=1)])
    chosen = resolve_model(client, LydiaConfig(model="qwen2.5-coder:7b"))
    assert chosen == "qwen2.5-coder:7b"
    assert warnings and "not to support structured tool calling" in warnings[0]


def test_resolve_auto_select_fallback_to_bad_model_warns(monkeypatch: pytest.MonkeyPatch) -> None:
    # Mirrors Levi's real remote server: config.model isn't installed there,
    # and every installed model is known not to support tool calling.
    warnings: list[str] = []
    monkeypatch.setattr(chat.ui, "print_warning", warnings.append)
    client = _FakeClient([
        ModelInfo(name="qwen2.5-coder:32b", size_bytes=100),
        ModelInfo(name="deepseek-coder:6.7b", size_bytes=10),
        ModelInfo(name="phi3.5:latest", size_bytes=5),
    ])
    chosen = resolve_model(client, LydiaConfig(model="qwen3.5:9b"))  # not installed on this backend
    assert chosen == "qwen2.5-coder:32b"
    assert warnings and "not to support structured tool calling" in warnings[0]


def test_resolve_good_model_no_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    warnings: list[str] = []
    monkeypatch.setattr(chat.ui, "print_warning", warnings.append)
    client = _FakeClient([ModelInfo(name="qwen3.5:9b", size_bytes=1)])
    chosen = resolve_model(client, LydiaConfig(model=None))
    assert chosen == "qwen3.5:9b"
    assert warnings == []
