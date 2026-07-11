"""Tests for model auto-selection."""

from lydia.llm.models import pick_default_model, supports_tool_calling
from lydia.llm.types import ModelInfo


def m(name: str, size: int = 1) -> ModelInfo:
    return ModelInfo(name=name, size_bytes=size)


def test_empty_returns_none() -> None:
    assert pick_default_model([]) is None


def test_prefers_coder_models() -> None:
    chosen = pick_default_model([m("llama3.2:latest", 100), m("qwen3.5-coder:7b", 10)])
    assert chosen == "qwen3.5-coder:7b"


def test_excludes_known_non_tool_calling_models() -> None:
    # qwen2.5-coder writes tool calls as plain JSON text instead of Ollama's
    # structured tool_calls field (see CLAUDE.md); deepseek-coder and phi3.5
    # have no tool-calling chat template at all, so Ollama rejects the
    # request outright ("model 'X' does not support tools") — both failure
    # modes mean auto-select must skip them, even though qwen2.5-coder would
    # otherwise win on MODEL_PRIORITY + size.
    chosen = pick_default_model([
        m("qwen2.5-coder:32b", 100), m("deepseek-coder:6.7b", 10),
        m("phi3.5:latest", 5), m("llama3.2:latest", 1),
    ])
    assert chosen == "llama3.2:latest"


def test_falls_back_to_excluded_model_if_nothing_else_installed() -> None:
    # Better to return something than nothing when every installed model is
    # known-bad — resolve_model() surfaces a warning in this case instead.
    # This is the real situation on Levi's remote Lydia Server today: none
    # of its installed models (qwen2.5-coder, deepseek-coder, phi3.5)
    # actually support tool calling in Ollama.
    chosen = pick_default_model([
        m("qwen2.5-coder:7b", 10), m("qwen2.5-coder:32b", 100),
        m("deepseek-coder:6.7b", 20), m("phi3.5:latest", 5),
    ])
    assert chosen == "qwen2.5-coder:32b"  # largest overall, once nothing qualifies


def test_supports_tool_calling() -> None:
    assert supports_tool_calling("qwen2.5-coder:7b") is False
    assert supports_tool_calling("deepseek-coder:6.7b") is False
    assert supports_tool_calling("phi3.5:latest") is False
    assert supports_tool_calling("qwen3.5:9b") is True
    assert supports_tool_calling("llama3.2:latest") is True


def test_prefers_larger_within_family() -> None:
    chosen = pick_default_model([
        m("qwen3.5:0.8b", 1), m("qwen3.5:9b", 9), m("qwen3.5:4b", 4),
    ])
    assert chosen == "qwen3.5:9b"


def test_unknown_models_fall_back_to_largest() -> None:
    chosen = pick_default_model([m("mystery:1b", 1), m("mystery:13b", 13)])
    assert chosen == "mystery:13b"
