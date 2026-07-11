"""Generate and store Lydia's daily personal briefing.

Drives the same agent loop the coding REPL uses (`agent/loop.py::run_agent_turn`),
but with only the personal-assistant tools in scope and a dedicated system
prompt (`agent/prompts.py::BRIEFING_SYSTEM_PROMPT`) — composing over
heterogeneous sources (email, assignments, market data, headlines) benefits
from the same LLM-driven prioritization the coding agent already does,
rather than a bespoke deterministic template.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from rich.markdown import Markdown

from lydia.agent.loop import run_agent_turn
from lydia.agent.prompts import BRIEFING_SYSTEM_PROMPT
from lydia.agent.tools import ToolContext, ToolSpec, build_registry
from lydia.cli import ui
from lydia.config.settings import GLOBAL_DIR, LydiaConfig
from lydia.llm.client import OllamaError
from lydia.llm.factory import build_client
from lydia.llm.types import Message

ASSISTANT_TOOL_NAMES = {"check_email", "check_canvas", "check_stocks", "check_news"}
BRIEFING_FILE = GLOBAL_DIR / "briefing.json"


def _assistant_registry() -> list[ToolSpec]:
    return [spec for spec in build_registry() if spec.name in ASSISTANT_TOOL_NAMES]


def _save_briefing(text: str) -> None:
    BRIEFING_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {"text": text, "generated_at": datetime.now(timezone.utc).isoformat()}
    BRIEFING_FILE.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def load_briefing() -> dict | None:
    if not BRIEFING_FILE.is_file():
        return None
    try:
        return json.loads(BRIEFING_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _notify(summary: str) -> None:
    """Fire a short macOS notification via osascript — ships with macOS, no extra dependency."""
    script = f'display notification {json.dumps(summary)} with title "Lydia" subtitle "Daily briefing"'
    subprocess.run(["osascript", "-e", script], check=False)


def run_briefing(config: LydiaConfig, notify: bool = False, _client_factory=build_client) -> int:
    """Generate one briefing turn. `_client_factory` is injectable for tests."""
    from lydia.cli.chat import resolve_model

    with _client_factory(config) as client:
        if not client.is_alive():
            target = config.server_url or config.ollama_host
            ui.print_error(f"Cannot reach {target}.")
            return 1
        try:
            model = resolve_model(client, config)
        except OllamaError as exc:
            ui.print_error(str(exc))
            return 1

        ctx = ToolContext(root=Path.home(), config=config, confirm=ui.auto_confirm, client=client)
        messages = [Message(role="user", content="Give me today's briefing.")]
        try:
            text, _ = run_agent_turn(
                client=client, model=model, temperature=config.temperature,
                num_ctx=config.num_ctx, think=config.think_flag, keep_alive=config.keep_alive,
                system_prompt=BRIEFING_SYSTEM_PROMPT, messages=messages,
                registry=_assistant_registry(), ctx=ctx,
                stream_fn=ui.stream_agent_response,
                on_tool_call=ui.print_tool_call, on_tool_result=ui.print_tool_result,
            )
        except OllamaError as exc:
            ui.print_error(str(exc))
            return 1

    _save_briefing(text)
    ui.console.print(Markdown(text))
    if notify:
        first_line = next((line for line in text.strip().splitlines() if line.strip()), "Briefing ready.")
        _notify(first_line.lstrip("-* ").strip()[:200])
    return 0


def show_briefing() -> int:
    saved = load_briefing()
    if saved is None:
        ui.print_info("No briefing yet. Run `lydia briefing run` first.")
        return 1
    ui.console.print(f"[dim]generated {saved['generated_at']}[/dim]\n")
    ui.console.print(Markdown(saved["text"]))
    return 0
