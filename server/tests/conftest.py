"""Shared fixtures: a TestClient wired to a fake provider, no real Ollama needed."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from tessa.llm.types import ChatChunk, Message, ModelInfo

from tessa_server.api.v1 import get_provider
from tessa_server.config.settings import ServerSettings, get_settings
from tessa_server.main import create_app


class FakeProvider:
    """A ModelClient double: scripted responses, records what it was asked."""

    def __init__(self) -> None:
        self.closed = False
        self.chat_calls: list[dict] = []
        self.embed_calls: list[tuple[str, list[str]]] = []
        self.chat_chunks: list[ChatChunk] = [ChatChunk(content="Hello!", done=True, stats={"eval_count": 3})]
        self.embeddings: list[list[float]] = [[0.1, 0.2, 0.3]]
        self.models: list[ModelInfo] = [ModelInfo(name="qwen3.5:9b", size_bytes=100, modified_at="t")]
        self.raise_on_chat: Exception | None = None

    def is_alive(self) -> bool:
        return True

    def list_models(self) -> list[ModelInfo]:
        return self.models

    def has_model(self, name: str) -> bool:
        return any(m.name == name for m in self.models)

    def embed(self, model: str, inputs: list[str]) -> list[list[float]]:
        self.embed_calls.append((model, inputs))
        return self.embeddings

    def chat_stream(self, model: str, messages: list[Message], **kwargs) -> Iterator[ChatChunk]:
        self.chat_calls.append({"model": model, "messages": messages, **kwargs})
        if self.raise_on_chat:
            raise self.raise_on_chat
        yield from self.chat_chunks

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def fake_provider() -> FakeProvider:
    return FakeProvider()


@pytest.fixture
def test_settings() -> ServerSettings:
    return ServerSettings(tokens={"good-token": "levi"})


@pytest.fixture
def api_client(fake_provider: FakeProvider, test_settings: ServerSettings) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: test_settings
    app.dependency_overrides[get_provider] = lambda: fake_provider
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer good-token"}
