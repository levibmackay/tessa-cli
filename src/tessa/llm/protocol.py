"""The structural interface every model client must satisfy.

`OllamaClient` (talks directly to a local Ollama daemon) and `RemoteClient`
(talks to a Tessa Server over HTTPS) both satisfy this shape. Everything
downstream — `agent/loop.py`, `agent/tools.py`, `context/indexer.py`,
`context/retriever.py` — type-hints against `ModelClient` rather than a
concrete class, so swapping which one gets constructed (see
`llm/factory.py`) requires no changes anywhere else.

This is a `Protocol`, not an ABC: neither client needs to inherit from
anything, and the existing test doubles (`FakeClient`, `FakeEmbedClient`)
already satisfy it structurally with no changes.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol, runtime_checkable

from tessa.llm.types import ChatChunk, Message, ModelInfo


@runtime_checkable
class ModelClient(Protocol):
    def is_alive(self) -> bool: ...

    def list_models(self) -> list[ModelInfo]: ...

    def has_model(self, name: str) -> bool: ...

    def embed(self, model: str, inputs: list[str]) -> list[list[float]]: ...

    def chat_stream(
        self,
        model: str,
        messages: list[Message],
        temperature: float = 0.7,
        num_ctx: int = 8192,
        think: bool | None = None,
        tools: list[dict] | None = None,
        keep_alive: str | None = None,
    ) -> Iterator[ChatChunk]: ...

    def close(self) -> None: ...

    def __enter__(self) -> "ModelClient": ...

    def __exit__(self, *exc_info: object) -> None: ...
