"""Generate and store Lydia's daily personal briefing.

Sources are fetched deterministically (directly calling each check_* tool
handler in agent/tools.py) rather than letting the model decide which tools
to call: live testing showed the model would sometimes skip a tool and just
fabricate plausible-looking content for that source instead (e.g. inventing
an Outlook email even when Outlook wasn't connected at all). Pre-fetching
every source removes that failure mode entirely — the model's only job is
to synthesize a checklist from data it's already been handed, with a system
prompt (`agent/prompts.py::BRIEFING_SYSTEM_PROMPT`) telling it not to add
anything beyond that.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from rich.markdown import Markdown

from lydia.agent.prompts import BRIEFING_SYSTEM_PROMPT
from lydia.agent.tools import ToolContext, _check_canvas, _check_email, _check_news, _check_stocks
from lydia.cli import ui
from lydia.config.settings import GLOBAL_DIR, LydiaConfig
from lydia.llm.client import OllamaError
from lydia.llm.factory import build_client
from lydia.llm.types import Message

BRIEFING_FILE = GLOBAL_DIR / "briefing.json"


def _gather_sources(ctx: ToolContext) -> str:
    """Call every source directly and return their raw results as labeled sections."""
    sections = [
        ("Canvas", _check_canvas({}, ctx)),
        ("Personal email (Gmail)", _check_email({"account": "personal"}, ctx)),
        ("School email (Outlook)", _check_email({"account": "school"}, ctx)),
        ("Stock market", _check_stocks({}, ctx)),
        ("AI news", _check_news({}, ctx)),
    ]
    return "\n\n".join(f"## {label}\n{result.content}" for label, result in sections)


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
        source_data = _gather_sources(ctx)
        messages = [Message(
            role="user",
            content=(
                "Here is today's raw data, already fetched from each source below. "
                "Compose the checklist from exactly this — do not invent anything "
                "beyond what's given, and don't ask to call any tools.\n\n" + source_data
            ),
        )]
        try:
            text, _ = ui.stream_response(client.chat_stream(
                model=model, messages=[Message(role="system", content=BRIEFING_SYSTEM_PROMPT), *messages],
                temperature=config.temperature, num_ctx=config.num_ctx,
                think=config.think_flag, keep_alive=config.keep_alive,
            ))
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
