"""HTTP client for the local Ollama daemon.

Uses the native Ollama REST API (http://localhost:11434) directly so there
is no dependency on the `ollama` Python package — just httpx and NDJSON.

Endpoints used:
    GET  /api/version  — health check
    GET  /api/tags     — installed models
    POST /api/chat     — streaming chat completions
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator

import httpx

from tessa.llm.types import ChatChunk, Message, ModelInfo, ToolCall

logger = logging.getLogger(__name__)


class OllamaError(Exception):
    """The Ollama daemon returned an error."""


class OllamaConnectionError(OllamaError):
    """Could not reach the Ollama daemon at all."""

    def __init__(self, host: str) -> None:
        super().__init__(
            f"Cannot reach Ollama at {host}.\n"
            "Start it with `ollama serve` or by opening the Ollama app."
        )
        self.host = host


class OllamaClient:
    """Thin, synchronous client for a local Ollama daemon."""

    def __init__(self, host: str = "http://localhost:11434", timeout: float = 300.0) -> None:
        self.host = host.rstrip("/")
        # Generous read timeout: local models can pause while loading layers.
        self._client = httpx.Client(
            base_url=self.host,
            timeout=httpx.Timeout(timeout, connect=5.0),
        )

    # -- health -----------------------------------------------------------

    def is_alive(self) -> bool:
        try:
            return self._client.get("/api/version").status_code == 200
        except httpx.HTTPError:
            return False

    # -- models -----------------------------------------------------------

    def list_models(self) -> list[ModelInfo]:
        try:
            response = self._client.get("/api/tags")
            response.raise_for_status()
        except httpx.ConnectError as exc:
            raise OllamaConnectionError(self.host) from exc
        except httpx.HTTPError as exc:
            raise OllamaError(f"Failed to list models: {exc}") from exc
        models = response.json().get("models", [])
        return [
            ModelInfo(
                name=m.get("name", ""),
                size_bytes=m.get("size", 0),
                modified_at=m.get("modified_at", ""),
            )
            for m in models
        ]

    def has_model(self, name: str) -> bool:
        return any(m.name == name or m.name.split(":")[0] == name for m in self.list_models())

    # -- chat -------------------------------------------------------------

    def chat_stream(
        self,
        model: str,
        messages: list[Message],
        temperature: float = 0.7,
        num_ctx: int = 8192,
        think: bool | None = None,
        tools: list[dict] | None = None,
    ) -> Iterator[ChatChunk]:
        """Stream a chat completion as it is generated.

        Yields ChatChunk objects; the final chunk has done=True and carries
        generation stats (token counts, duration). A model that decides to
        call a tool sends the whole call in one non-final chunk rather than
        streaming it token by token.

        *think*: force reasoning on/off for thinking-capable models.
        None leaves the model's default behaviour untouched (safe for
        models that don't support the parameter at all).
        *tools*: JSON-schema tool definitions (Ollama/OpenAI function-calling
        format) to offer the model this turn.
        """
        payload: dict = {
            "model": model,
            "messages": [m.to_dict() for m in messages],
            "stream": True,
            "options": {"temperature": temperature, "num_ctx": num_ctx},
        }
        if think is not None:
            payload["think"] = think
        if tools:
            payload["tools"] = tools
        try:
            with self._client.stream("POST", "/api/chat", json=payload) as response:
                if response.status_code != 200:
                    body = response.read().decode("utf-8", errors="replace")
                    raise OllamaError(_extract_error(body, response.status_code))
                for line in response.iter_lines():
                    if not line.strip():
                        continue
                    chunk = self._parse_chunk(line)
                    if chunk is not None:
                        yield chunk
                        if chunk.done:
                            return
        except httpx.ConnectError as exc:
            raise OllamaConnectionError(self.host) from exc
        except httpx.HTTPError as exc:
            raise OllamaError(f"Chat request failed: {exc}") from exc

    @staticmethod
    def _parse_chunk(line: str) -> ChatChunk | None:
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            logger.warning("Skipping malformed stream line: %.120s", line)
            return None
        if "error" in data:
            raise OllamaError(data["error"])
        message = data.get("message", {})
        tool_calls = [
            ToolCall(
                name=tc.get("function", {}).get("name", ""),
                arguments=tc.get("function", {}).get("arguments", {}) or {},
            )
            for tc in message.get("tool_calls") or []
        ]
        if data.get("done"):
            stats = {
                k: data[k]
                for k in ("total_duration", "eval_count", "prompt_eval_count")
                if k in data
            }
            return ChatChunk(
                content=message.get("content", ""),
                thinking=message.get("thinking", ""),
                tool_calls=tool_calls,
                done=True,
                stats=stats,
            )
        return ChatChunk(
            content=message.get("content", ""),
            thinking=message.get("thinking", ""),
            tool_calls=tool_calls,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "OllamaClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


def _extract_error(body: str, status: int) -> str:
    try:
        return json.loads(body).get("error", body)
    except json.JSONDecodeError:
        return f"HTTP {status}: {body[:200]}"
