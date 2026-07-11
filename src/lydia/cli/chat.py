"""The interactive Lydia chat REPL."""

from __future__ import annotations

from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.styles import Style

from lydia.agent import facts
from lydia.agent.loop import run_agent_turn
from lydia.agent.memory import SessionHistory
from lydia.agent.prompts import build_system_prompt
from lydia.agent.tools import ToolContext, build_registry
from lydia.cli import ui
from lydia.config.settings import GLOBAL_DIR, LydiaConfig, find_project_root
from lydia.context.scanner import ProjectSummary, scan_project
from lydia.llm.client import OllamaError
from lydia.llm.factory import build_client
from lydia.llm.models import pick_default_model, supports_tool_calling
from lydia.llm.protocol import ModelClient
from lydia.llm.types import Message

HELP_TEXT = """\
| Command | Effect |
|---|---|
| `/help` | Show this help |
| `/model <name>` | Switch model for this session |
| `/models` | List installed Ollama models |
| `/new` | Start a fresh conversation |
| `/remember <fact>` | Save a fact that persists across sessions |
| `/memory` | List remembered facts |
| `/forget <n>` | Remove remembered fact #n |
| `/exit` | Quit (also Ctrl-D) |
"""

PROMPT_STYLE = Style.from_dict({"prompt": "ansimagenta bold"})


class ChatSession:
    """Holds the state of one interactive session."""

    def __init__(self, config: LydiaConfig, client: ModelClient, model: str,
                 summary: ProjectSummary | None, project_root: Path | None) -> None:
        self.config = config
        self.client = client
        self.model = model
        self.root = project_root or Path.cwd()
        self.summary = summary
        self.facts = facts.load_facts(self.root)
        self.system_prompt = build_system_prompt(summary, self.facts)
        self.messages: list[Message] = []
        self.history = SessionHistory(project_root)
        self.registry = build_registry()

    def reset(self) -> None:
        self.messages.clear()

    def refresh_facts(self) -> None:
        """Reload remembered facts from disk and fold them back into the prompt."""
        self.facts = facts.load_facts(self.root)
        self.system_prompt = build_system_prompt(self.summary, self.facts)

    def send(self, user_text: str) -> None:
        user_message = Message(role="user", content=user_text)
        self.messages.append(user_message)
        self.history.append(user_message)
        ctx = ToolContext(root=self.root, config=self.config, confirm=ui.confirm, client=self.client)
        try:
            reply, stats = run_agent_turn(
                client=self.client,
                model=self.model,
                temperature=self.config.temperature,
                num_ctx=self.config.num_ctx,
                think=self.config.think_flag,
                keep_alive=self.config.keep_alive,
                system_prompt=self.system_prompt,
                messages=self.messages,
                registry=self.registry,
                ctx=ctx,
                stream_fn=ui.stream_agent_response,
                on_tool_call=ui.print_tool_call,
                on_tool_result=ui.print_tool_result,
            )
        except KeyboardInterrupt:
            ui.console.print("\n[dim]interrupted[/dim]")
            return
        except OllamaError as exc:
            ui.print_error(str(exc))
            return
        self.history.append(Message(role="assistant", content=reply))
        self.refresh_facts()  # pick up anything remembered via the tool this turn
        line = ui.format_stats(stats)
        if line:
            ui.console.print(f"[dim]{line}[/dim]")
        ui.console.print()


def resolve_model(client: ModelClient, config: LydiaConfig) -> str:
    """Use the configured model if installed, otherwise auto-pick."""
    models = client.list_models()
    if not models:
        raise OllamaError("No models installed. Pull one first, e.g. `ollama pull qwen3.5`.")

    chosen: str | None = None
    if config.model:
        if any(m.name == config.model or m.name.split(":")[0] == config.model for m in models):
            chosen = config.model
        else:
            ui.print_error(f"Configured model '{config.model}' is not installed; auto-selecting.")
    if chosen is None:
        chosen = pick_default_model(models) or models[0].name

    # Covers both cases: an explicitly-configured bad model, and auto-select
    # being forced to fall back to one because nothing else qualifies (e.g.
    # a remote backend whose only installed models all lack tool support).
    if not supports_tool_calling(chosen):
        ui.print_warning(
            f"'{chosen}' is known not to support structured tool calling — "
            "file/git/assistant tools will silently do nothing or error. Install a "
            "tool-capable model (e.g. `ollama pull qwen3.5` or a llama3.1+ model) on "
            "whichever Ollama instance is actually handling requests, or use `lydia "
            "ask` without --yes for plain Q&A."
        )
    return chosen


def run_chat(config: LydiaConfig) -> int:
    client = build_client(config)
    if not client.is_alive():
        if config.server_url:
            ui.print_error(f"Cannot reach the Lydia Server at {config.server_url}.")
        else:
            ui.print_error(
                f"Cannot reach Ollama at {config.ollama_host}.\n"
                "  Start it with `ollama serve` or by opening the Ollama app."
            )
        return 1

    try:
        model = resolve_model(client, config)
    except OllamaError as exc:
        ui.print_error(str(exc))
        return 1

    project_root = find_project_root()
    summary = scan_project(project_root) if project_root else None
    session = ChatSession(config, client, model, summary, project_root)

    ui.print_banner(model, summary.project_kind if summary else None)

    GLOBAL_DIR.mkdir(parents=True, exist_ok=True)
    prompt_session: PromptSession[str] = PromptSession(
        history=FileHistory(str(GLOBAL_DIR / "prompt_history")),
        style=PROMPT_STYLE,
    )

    while True:
        try:
            text = prompt_session.prompt([("class:prompt", "Lydia > ")]).strip()
        except KeyboardInterrupt:
            continue  # clear the current line, like a shell
        except EOFError:
            break
        if not text:
            continue
        if text.startswith("/"):
            if _handle_slash(text, session):
                break
            continue
        session.send(text)

    ui.console.print("[dim]bye[/dim]")
    client.close()
    return 0


def _handle_slash(text: str, session: ChatSession) -> bool:
    """Handle a /command. Returns True if the REPL should exit."""
    command, _, argument = text.partition(" ")
    command = command.lower()
    argument = argument.strip()

    if command in ("/exit", "/quit", "/q"):
        return True
    if command == "/help":
        from rich.markdown import Markdown
        ui.console.print(Markdown(HELP_TEXT))
    elif command == "/new":
        session.reset()
        ui.print_info("Started a fresh conversation.")
    elif command == "/models":
        try:
            for m in session.client.list_models():
                marker = "→" if m.name == session.model else " "
                ui.console.print(f" {marker} {m.name}  [dim]{m.size_human}[/dim]")
        except OllamaError as exc:
            ui.print_error(str(exc))
    elif command == "/model":
        if not argument:
            ui.print_info(f"Current model: {session.model}")
        elif session.client.has_model(argument):
            session.model = argument
            ui.print_info(f"Switched to {argument} for this session.")
        else:
            ui.print_error(f"Model '{argument}' is not installed. Try `ollama pull {argument}`.")
    elif command == "/remember":
        if not argument:
            ui.print_error("Usage: /remember <fact>")
        else:
            fact = facts.remember(session.root, argument)
            session.refresh_facts()
            ui.print_info(f"Remembered: {fact.text}")
    elif command == "/memory":
        if not session.facts:
            ui.print_info("No facts remembered yet. Use /remember <fact> to add one.")
        else:
            for i, fact in enumerate(session.facts, start=1):
                ui.console.print(f"  {i}. {fact.text}  [dim]{fact.created_at}[/dim]")
    elif command == "/forget":
        try:
            index = int(argument)
        except ValueError:
            ui.print_error("Usage: /forget <n> — see /memory for fact numbers.")
        else:
            try:
                removed = facts.forget(session.root, index)
            except ValueError as exc:
                ui.print_error(str(exc))
            else:
                session.refresh_facts()
                ui.print_info(f"Forgot: {removed.text}")
    else:
        ui.print_error(f"Unknown command {command}. Try /help.")
    return False
