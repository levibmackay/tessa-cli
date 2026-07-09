"""Tests for llm/factory.py::build_client selecting the right client type."""

from tessa.config.settings import TessaConfig
from tessa.llm.client import OllamaClient
from tessa.llm.factory import build_client
from tessa.llm.remote_client import RemoteClient


def test_build_client_defaults_to_local_ollama() -> None:
    client = build_client(TessaConfig())
    assert isinstance(client, OllamaClient)
    client.close()


def test_build_client_uses_remote_when_server_url_set() -> None:
    client = build_client(TessaConfig(server_url="https://gaming-pc.example:8000", api_key="tok"))
    assert isinstance(client, RemoteClient)
    assert client.base_url == "https://gaming-pc.example:8000"
    client.close()


def test_build_client_local_uses_configured_host() -> None:
    client = build_client(TessaConfig(ollama_host="http://10.0.0.5:11434"))
    assert isinstance(client, OllamaClient)
    assert client.host == "http://10.0.0.5:11434"
    client.close()
