"""Shared data types for the LLM layer."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

Role = Literal["system", "user", "assistant", "tool"]


@dataclass
class ToolCall:
    """A request from the model to invoke one tool."""

    name: str
    arguments: dict[str, Any]
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])

    def to_dict(self) -> dict[str, Any]:
        return {"function": {"name": self.name, "arguments": self.arguments}}


@dataclass
class Message:
    """A single chat message.

    Assistant messages that invoke tools carry `tool_calls`; the matching
    results are sent back as separate role="tool" messages.
    """

    role: Role
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.tool_calls:
            data["tool_calls"] = [tc.to_dict() for tc in self.tool_calls]
        return data


@dataclass
class ModelInfo:
    """An installed Ollama model."""

    name: str
    size_bytes: int = 0
    modified_at: str = ""

    @property
    def size_human(self) -> str:
        size = float(self.size_bytes)
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if size < 1024 or unit == "TB":
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"


@dataclass
class ChatChunk:
    """One streamed piece of an assistant reply.

    Thinking models (qwen3, deepseek-r1, ...) stream their reasoning in
    a separate `thinking` field before any answer content arrives.
    """

    content: str = ""
    thinking: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    done: bool = False
    stats: dict[str, Any] = field(default_factory=dict)
