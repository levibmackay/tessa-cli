"""The interactive Tessa chat REPL."""

from __future__ import annotations

from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.styles import Style

from tessa.agent.loop import run_agent_turn
from tessa.agent.memory import SessionHistory
from tessa.agent.prompts import build_system_prompt
from tessa.agent.tools import ToolContext, build_registry
from tessa.cli import ui
from tessa.config.settings import GLOBAL_DIR, TessaConfig, find_project_root
from tessa.context.scanner import ProjectSummary, scan_project
from tessa.llm.client import OllamaClient, OllamaError
from tessa.llm.models import pick_default_model
from tessa.llm.types import Message

HELP_TEXT = """\
| Command | Effect |
|---|---|
| `/help` | Show this help |
| `/model <name>` | Switch model for this session |
| `/models` | List installed Ollama models |
| `/new` | Start a fresh conversation |
| `/exit` | Quit (also Ctrl-D) |
"""

PROMPT_STYLE = Style.from_dict({"prompt": "ansimagenta bold"})


class ChatSession:
    """Holds the state of one interactive session."""

    def __init__(self, config: TessaConfig, client: OllamaClient, model: str,
                 summary: ProjectSummary | None, project_root: Path | None) -> None:
        self.config = config
        self.client = client
        self.model = model
        self.root = project_root or Path.cwd()
        self.system_prompt = build_system_prompt(summary)
        self.messages: list[Message] = []
        self.history = SessionHistory(project_root)
        self.registry = build_registry()

    def reset(self) -> None:
        self.messages.clear()

    def send(self, user_text: str) -> None:
        user_message = Message(role="user", content=user_text)
        self.messages.append(user_message)
        self.history.append(user_message)
        ctx = ToolContext(root=self.root, config=self.config, confirm=ui.confirm)
        try:
            reply, stats = run_agent_turn(
                client=self.client,
                model=self.model,
                temperature=self.config.temperature,
                num_ctx=self.config.num_ctx,
                think=self.config.think_flag,
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
        line = ui.format_stats(stats)
        if line:
            ui.console.print(f"[dim]{line}[/dim]")
        ui.console.print()


def resolve_model(client: OllamaClient, config: TessaConfig) -> str:
    """Use the configured model if installed, otherwise auto-pick."""
    models = client.list_models()
    if not models:
        raise OllamaError("No models installed. Pull one first, e.g. `ollama pull qwen3.5`.")
    if config.model:
        if any(m.name == config.model or m.name.split(":")[0] == config.model for m in models):
            return config.model
        ui.print_error(f"Configured model '{config.model}' is not installed; auto-selecting.")
    return pick_default_model(models) or models[0].name


def run_chat(config: TessaConfig) -> int:
    client = OllamaClient(host=config.ollama_host)
    if not client.is_alive():
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
            text = prompt_session.prompt([("class:prompt", "Tessa > ")]).strip()
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
    else:
        ui.print_error(f"Unknown command {command}. Try /help.")
    return False
