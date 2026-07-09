"""Tests for the Ollama client using httpx.MockTransport (no daemon needed)."""

import json

import httpx
import pytest

from tessa.llm.client import OllamaClient, OllamaError
from tessa.llm.types import Message


def make_client(handler) -> OllamaClient:
    client = OllamaClient()
    client._client = httpx.Client(
        base_url=client.host, transport=httpx.MockTransport(handler)
    )
    return client


def ndjson(*objects: dict) -> bytes:
    return ("\n".join(json.dumps(o) for o in objects) + "\n").encode()


def test_list_models() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/tags"
        return httpx.Response(200, json={"models": [
            {"name": "qwen3.5:9b", "size": 6_600_000_000, "modified_at": "2026-06-01"},
        ]})

    models = make_client(handler).list_models()
    assert len(models) == 1
    assert models[0].name == "qwen3.5:9b"
    assert models[0].size_human == "6.1 GB"


def test_chat_stream_accumulates_chunks() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/chat"
        payload = json.loads(request.content)
        assert payload["stream"] is True
        assert payload["messages"][0] == {"role": "user", "content": "hi"}
        return httpx.Response(200, content=ndjson(
            {"message": {"content": "Hel"}, "done": False},
            {"message": {"content": "lo!"}, "done": False},
            {"message": {"content": ""}, "done": True,
             "eval_count": 5, "total_duration": 1_000_000_000},
        ))

    chunks = list(make_client(handler).chat_stream("m", [Message("user", "hi")]))
    assert "".join(c.content for c in chunks) == "Hello!"
    assert chunks[-1].done is True
    assert chunks[-1].stats["eval_count"] == 5


def test_chat_stream_surfaces_ollama_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "model 'nope' not found"})

    with pytest.raises(OllamaError, match="not found"):
        list(make_client(handler).chat_stream("nope", [Message("user", "hi")]))


def test_thinking_chunks_are_separated_from_content() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["think"] is False
        return httpx.Response(200, content=ndjson(
            {"message": {"content": "", "thinking": "hmm, "}, "done": False},
            {"message": {"content": "", "thinking": "let me see"}, "done": False},
            {"message": {"content": "Answer."}, "done": False},
            {"message": {"content": ""}, "done": True},
        ))

    chunks = list(make_client(handler).chat_stream("m", [Message("user", "hi")], think=False))
    assert "".join(c.thinking for c in chunks) == "hmm, let me see"
    assert "".join(c.content for c in chunks) == "Answer."


def test_keep_alive_included_when_set() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["keep_alive"] == "30m"
        return httpx.Response(200, content=ndjson({"message": {"content": "ok"}, "done": True}))

    list(make_client(handler).chat_stream("m", [Message("user", "hi")], keep_alive="30m"))


def test_keep_alive_omitted_when_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert "keep_alive" not in payload
        return httpx.Response(200, content=ndjson({"message": {"content": "ok"}, "done": True}))

    list(make_client(handler).chat_stream("m", [Message("user", "hi")]))


def test_malformed_stream_lines_are_skipped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = b'{"message": {"content": "ok"}, "done": false}\ngarbage\n' + ndjson(
            {"message": {"content": ""}, "done": True}
        )
        return httpx.Response(200, content=body)

    chunks = list(make_client(handler).chat_stream("m", [Message("user", "hi")]))
    assert "".join(c.content for c in chunks) == "ok"
