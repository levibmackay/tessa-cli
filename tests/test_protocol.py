"""Both concrete clients must satisfy the ModelClient protocol structurally."""

from tessa.llm.client import OllamaClient
from tessa.llm.protocol import ModelClient
from tessa.llm.remote_client import RemoteClient


def test_ollama_client_satisfies_model_client() -> None:
    client = OllamaClient()
    assert isinstance(client, ModelClient)
    client.close()


def test_remote_client_satisfies_model_client() -> None:
    client = RemoteClient(base_url="https://example.com")
    assert isinstance(client, ModelClient)
    client.close()
