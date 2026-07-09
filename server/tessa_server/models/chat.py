"""Pydantic request/response schemas for the /v1/* API.

Deliberately shaped like Ollama's own /api/chat and /api/embed bodies (see
CLAUDE.md in the repo root for why) so `tessa.llm.client`'s existing
payload-building and chunk-parsing logic works against this API almost
unmodified.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ChatOptions(BaseModel):
    temperature: float = 0.7
    num_ctx: int = 8192


class ChatMessage(BaseModel):
    role: str
    content: str
    tool_calls: list[dict] | None = None


class ChatRequest(BaseModel):
    model: str
    messages: list[ChatMessage]
    stream: bool = True
    options: ChatOptions = Field(default_factory=ChatOptions)
    think: bool | None = None
    tools: list[dict] | None = None
    keep_alive: str | None = None


class EmbedRequest(BaseModel):
    model: str
    input: list[str]


class EmbedResponse(BaseModel):
    embeddings: list[list[float]]


class ModelEntry(BaseModel):
    name: str
    size: int = 0
    modified_at: str = ""


class ModelsResponse(BaseModel):
    models: list[ModelEntry]


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str
