"""Picks which ModelClient implementation to construct from config.

If `server_url` is set, talk to a remote Tessa Server; otherwise, exactly
today's behavior — a local Ollama daemon at `ollama_host`. This is the one
place that needs to know both concrete client types; everything else in
the codebase only ever sees the `ModelClient` protocol.
"""

from __future__ import annotations

from tessa.config.settings import TessaConfig
from tessa.llm.client import OllamaClient
from tessa.llm.protocol import ModelClient
from tessa.llm.remote_client import RemoteClient


def build_client(config: TessaConfig) -> ModelClient:
    if config.server_url:
        return RemoteClient(base_url=config.server_url, api_key=config.api_key)
    return OllamaClient(host=config.ollama_host)
