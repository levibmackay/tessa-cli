"""Model selection heuristics.

When the user has not configured a model, pick the best coding-capable
model they already have installed. Matching is by substring on the model
name, in priority order.
"""

from __future__ import annotations

from lydia.llm.types import ModelInfo

# Higher in the list = preferred. Substrings matched against model names.
MODEL_PRIORITY: tuple[str, ...] = (
    "qwen3.5-coder",
    "qwen3-coder",
    "qwen2.5-coder",
    "deepseek-coder",
    "codellama",
    "codegemma",
    "qwen3.5",
    "qwen3",
    "llama3",
    "mistral",
)

# Models empirically confirmed not to work with tool calling in Ollama, by
# one of two failure modes: qwen2.5-coder's chat template declares tool
# support but the model just writes the call as plain JSON text in
# message.content instead of populating the structured message.tool_calls
# field (see CLAUDE.md) — silent, tools just never fire. deepseek-coder and
# phi3.5's Ollama templates don't declare tool support at all, so Ollama
# rejects any request that includes `tools` outright with "model 'X' does
# not support tools" — loud, but still means auto-select must skip them.
KNOWN_NON_TOOL_CALLING: tuple[str, ...] = (
    "qwen2.5-coder",
    "deepseek-coder",
    "phi3.5",
)


def supports_tool_calling(model_name: str) -> bool:
    """Best-effort check: False only for models confirmed broken, not "unknown"."""
    name = model_name.lower()
    return not any(pattern in name for pattern in KNOWN_NON_TOOL_CALLING)


def pick_default_model(models: list[ModelInfo]) -> str | None:
    """Choose the best installed model for coding work.

    Among models matching the same priority tier, prefer the largest
    (more parameters generally means better code quality). Models known not
    to support structured tool calling are excluded so auto-select can't
    silently pick one and make every tool call a no-op.
    """
    if not models:
        return None
    candidates = [m for m in models if supports_tool_calling(m.name)] or models
    for pattern in MODEL_PRIORITY:
        matches = [m for m in candidates if pattern in m.name.lower()]
        if matches:
            return max(matches, key=lambda m: m.size_bytes).name
    return max(candidates, key=lambda m: m.size_bytes).name
