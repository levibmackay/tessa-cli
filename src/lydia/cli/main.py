"""Lydia command-line entry point.

    lydia                      interactive chat (default)
    lydia ask "question"       one-shot question, prints the answer
    lydia analyze              summarize the current project
    lydia index                build/refresh the semantic search index
    lydia restore list         list file backups
    lydia restore apply N      restore a file to a backed-up version
    lydia models               list installed Ollama models
    lydia init                 create .lydia/ in the current project
    lydia config show          print effective configuration
    lydia config set KEY VAL   set a config value (global or --project)
    lydia auth login PROVIDER  connect gmail, outlook, or canvas
    lydia auth status          show which sources are connected
    lydia auth logout PROVIDER disconnect a source
    lydia briefing run         generate today's personal briefing
    lydia briefing show        print the last generated briefing
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import typer
from rich.syntax import Syntax
from rich.table import Table

from lydia import __version__
from lydia.agent import facts
from lydia.cli import ui
from lydia.cli.chat import resolve_model, run_chat
from lydia.config.settings import (
    LydiaConfig,
    coerce_value,
    find_project_root,
    global_config_path,
    load_config,
    project_config_path,
    save_config_value,
)
from lydia.context.indexer import EMBED_MODEL, build_index
from lydia.context.scanner import scan_project
from lydia.llm.client import OllamaError
from lydia.llm.factory import build_client
from lydia.llm.protocol import ModelClient
from lydia.llm.types import Message
from lydia.tools.filesystem import apply_write, list_backups, restore_backup

app = typer.Typer(
    name="lydia",
    help="Lydia — a local AI coding agent powered by Ollama.",
    add_completion=False,
    no_args_is_help=False,
)
config_app = typer.Typer(help="View and change configuration.")
app.add_typer(config_app, name="config")
memory_app = typer.Typer(help="View and manage remembered project facts.")
app.add_typer(memory_app, name="memory")
restore_app = typer.Typer(help="List and restore file backups made by write_file/delete_file.")
app.add_typer(restore_app, name="restore")
auth_app = typer.Typer(help="Connect Lydia to Gmail, Outlook, and Canvas for the personal-assistant tools.")
app.add_typer(auth_app, name="auth")
briefing_app = typer.Typer(help="Generate and view Lydia's daily personal briefing.")
app.add_typer(briefing_app, name="briefing")
schedule_app = typer.Typer(help="Manage the daily scheduled briefing (macOS launchd).")
briefing_app.add_typer(schedule_app, name="schedule")


def _memory_root() -> Path:
    return find_project_root() or Path.cwd()


@app.callback(invoke_without_command=True)
def default(
    ctx: typer.Context,
    version: bool = typer.Option(False, "--version", "-V", help="Print version and exit."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging."),
) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    if version:
        ui.console.print(f"lydia {__version__}")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        raise typer.Exit(run_chat(load_config()))


@app.command()
def ask(
    question: str = typer.Argument(..., help="A single question for Lydia."),
    model: str | None = typer.Option(None, "--model", "-m", help="Override the model."),
    yes: bool = typer.Option(
        False, "--yes", "-y",
        help="Give Lydia tool access (read/write/run/git) for this question, "
        "auto-approving anything that isn't flagged dangerous. For scripts/CI "
        "where there's no one to answer a y/n prompt.",
    ),
) -> None:
    """Ask one question and print the answer (useful for scripts)."""
    config = load_config()
    if model:
        config.model = model
    with build_client(config) as client:
        try:
            resolved = resolve_model(client, config)
            if yes:
                reply, _ = _ask_with_tools(client, resolved, config, question)
            else:
                reply, _ = ui.stream_response(
                    client.chat_stream(
                        model=resolved,
                        messages=[Message(role="user", content=question)],
                        temperature=config.temperature,
                        num_ctx=config.num_ctx,
                        think=config.think_flag,
                        keep_alive=config.keep_alive,
                    )
                )
        except OllamaError as exc:
            ui.print_error(str(exc))
            raise typer.Exit(1)
    if not reply.strip():
        raise typer.Exit(1)


def _ask_with_tools(client: ModelClient, model: str, config: LydiaConfig, question: str) -> tuple[str, dict]:
    """Run one question through the full agent loop (tools + auto-confirm)."""
    from lydia.agent.loop import run_agent_turn
    from lydia.agent.prompts import build_system_prompt
    from lydia.agent.tools import ToolContext, build_registry

    root = find_project_root() or Path.cwd()
    summary = scan_project(root)
    ctx = ToolContext(root=root, config=config, confirm=ui.auto_confirm, client=client)
    messages = [Message(role="user", content=question)]
    return run_agent_turn(
        client=client, model=model, temperature=config.temperature,
        num_ctx=config.num_ctx, think=config.think_flag, keep_alive=config.keep_alive,
        system_prompt=build_system_prompt(summary), messages=messages,
        registry=build_registry(), ctx=ctx, stream_fn=ui.stream_agent_response,
        on_tool_call=ui.print_tool_call, on_tool_result=ui.print_tool_result,
    )


@app.command()
def analyze(
    path: Path = typer.Argument(Path("."), help="Project directory to analyze."),
) -> None:
    """Scan a project and print a summary."""
    if not path.is_dir():
        ui.print_error(f"Not a directory: {path}")
        raise typer.Exit(1)
    summary = scan_project(path)

    table = Table(show_header=False, box=None, pad_edge=False)
    table.add_column(style="dim", min_width=12)
    table.add_column()
    table.add_row("Project", f"[bold]{summary.project_kind}[/bold]")
    table.add_row("Root", str(summary.root))
    table.add_row("Files", str(summary.file_count))
    table.add_row("Code lines", f"{summary.total_lines:,}")
    languages = "  ".join(f"{name} [bold]{pct}%[/bold]" for name, pct in summary.languages.items())
    table.add_row("Languages", languages or "[dim]none detected[/dim]")
    if summary.manifest_files:
        table.add_row("Key files", "\n".join(summary.manifest_files[:8]))
    if summary.largest_source_files:
        largest = "\n".join(f"{p}  [dim]{n:,} lines[/dim]" for p, n in summary.largest_source_files[:5])
        table.add_row("Largest", largest)
    ui.console.print(table)


@app.command(name="index")
def build_semantic_index(
    path: Path = typer.Argument(Path("."), help="Project directory to index."),
    force: bool = typer.Option(False, "--force", "-f", help="Re-embed every file, ignoring the incremental cache."),
) -> None:
    """Build or refresh the semantic search index (used by the search_semantic tool)."""
    if not path.is_dir():
        ui.print_error(f"Not a directory: {path}")
        raise typer.Exit(1)
    root = path.resolve()
    config = load_config(project_root=root)
    with build_client(config) as client:
        if not client.is_alive():
            target = config.server_url or config.ollama_host
            ui.print_error(f"Cannot reach {target}.")
            raise typer.Exit(1)
        if not client.has_model(EMBED_MODEL):
            ui.print_error(f"Embedding model not installed. Run `ollama pull {EMBED_MODEL}` first.")
            raise typer.Exit(1)
        with ui.console.status("Indexing..."):
            stats = build_index(root, client, force=force)
    ui.print_info(
        f"Scanned {stats.files_scanned} file(s); embedded {stats.files_indexed} changed file(s) "
        f"({stats.chunks_indexed} chunks); removed {stats.files_removed} deleted file(s) from the index."
    )


@app.command()
def models() -> None:
    """List models installed in Ollama."""
    config = load_config()
    with build_client(config) as client:
        try:
            installed = client.list_models()
        except OllamaError as exc:
            ui.print_error(str(exc))
            raise typer.Exit(1)
    if not installed:
        ui.print_info("No models installed. Try `ollama pull qwen3.5`.")
        return
    table = Table(box=None)
    table.add_column("Model", style="bold")
    table.add_column("Size", style="dim")
    for m in installed:
        table.add_row(m.name, m.size_human)
    ui.console.print(table)


@app.command()
def init() -> None:
    """Create a .lydia/ directory in the current project."""
    root = Path.cwd()
    config_file = project_config_path(root)
    if config_file.exists():
        ui.print_info(f"Already initialized: {config_file}")
        return
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(json.dumps({}, indent=2) + "\n", encoding="utf-8")
    gitignore = config_file.parent / ".gitignore"
    gitignore.write_text("history/\nbackups/\nindex.sqlite3\n", encoding="utf-8")
    ui.print_info(f"Initialized {config_file.parent}/ (history/, backups/, and index.sqlite3 are git-ignored)")


@config_app.command("show")
def config_show() -> None:
    """Print the effective merged configuration."""
    config = load_config()
    root = find_project_root()
    ui.console.print(f"[dim]global:[/dim]  {global_config_path()}")
    if root:
        ui.console.print(f"[dim]project:[/dim] {project_config_path(root)}")
    unset_labels = {"model": "auto", "server_url": "not set (using local Ollama)", "api_key": "not set"}
    for key, value in vars(config).items():
        shown = value if value is not None else f"[dim]{unset_labels.get(key, 'not set')}[/dim]"
        ui.console.print(f"  {key} = {shown}")


SECRET_KEYS = {"api_key"}


@config_app.command("set")
def config_set(
    key: str = typer.Argument(..., help="Config key, e.g. model"),
    value: str = typer.Argument(..., help="New value"),
    project: bool = typer.Option(False, "--project", "-p", help="Write to the project config instead of global."),
) -> None:
    """Set a configuration value, e.g. `lydia config set model qwen3.5:9b`."""
    if project and key in SECRET_KEYS:
        ui.print_error(
            f"'{key}' can't be set with --project — <project>/.lydia/config.json is meant to be "
            "committed to git, and would leak this secret to anyone with repo access. "
            f"Run `lydia config set {key} <value>` without --project (global config, ~/.lydia/config.json, "
            "never part of any repo) instead."
        )
        raise typer.Exit(1)
    if project:
        root = find_project_root()
        if root is None:
            ui.print_error("Not inside a project (no .lydia/ or .git found). Run `lydia init` first.")
            raise typer.Exit(1)
        path = project_config_path(root)
    else:
        path = global_config_path()
    try:
        save_config_value(key, coerce_value(key, value), path)
    except (KeyError, ValueError) as exc:
        ui.print_error(str(exc))
        raise typer.Exit(1)
    ui.print_info(f"Set {key} = {value} in {path}")


@memory_app.command("list")
def memory_list() -> None:
    """List remembered facts about the current project."""
    remembered = facts.load_facts(_memory_root())
    if not remembered:
        ui.print_info("No facts remembered yet. Use `lydia memory add <fact>` to add one.")
        return
    for i, fact in enumerate(remembered, start=1):
        ui.console.print(f"  {i}. {fact.text}  [dim]{fact.created_at}[/dim]")


@memory_app.command("add")
def memory_add(fact: str = typer.Argument(..., help="The fact to remember")) -> None:
    """Remember a fact about the current project."""
    saved = facts.remember(_memory_root(), fact)
    ui.print_info(f"Remembered: {saved.text}")


@memory_app.command("forget")
def memory_forget(index: int = typer.Argument(..., help="Fact number, as shown by `lydia memory list`")) -> None:
    """Forget a remembered fact by number."""
    try:
        removed = facts.forget(_memory_root(), index)
    except ValueError as exc:
        ui.print_error(str(exc))
        raise typer.Exit(1)
    ui.print_info(f"Forgot: {removed.text}")


@restore_app.command("list")
def restore_list() -> None:
    """List available backups, newest first."""
    root = find_project_root() or Path.cwd()
    entries = list_backups(root)
    if not entries:
        ui.print_info("No backups yet — they're created automatically when Lydia writes or deletes a file.")
        return
    for i, entry in enumerate(entries, start=1):
        ui.console.print(f"  {i}. {entry.path}  [dim]{entry.stamp}[/dim]")


@restore_app.command("apply")
def restore_apply(index: int = typer.Argument(..., help="Backup number, as shown by `lydia restore list`")) -> None:
    """Restore a file to a previous backed-up version."""
    root = find_project_root() or Path.cwd()
    entries = list_backups(root)
    if not 1 <= index <= len(entries):
        ui.print_error(f"No backup #{index}. There are {len(entries)}; see `lydia restore list`.")
        raise typer.Exit(1)
    entry = entries[index - 1]
    proposal = restore_backup(root, entry)
    ui.console.print(Syntax(proposal.diff, "diff", background_color="default", word_wrap=True))
    if not typer.confirm(f"Restore {entry.path} to its {entry.stamp} version?"):
        ui.print_info("Cancelled.")
        return
    message = apply_write(root, proposal)
    ui.print_info(message)


AUTH_PROVIDERS = ("gmail", "outlook", "canvas")


@auth_app.command("login")
def auth_login(
    provider: str = typer.Argument(..., help="gmail | outlook | canvas"),
    client_id: str | None = typer.Option(
        None, "--client-id", help="Outlook only: the Azure app's Application (client) ID."
    ),
    base_url: str | None = typer.Option(
        None, "--base-url", help="Canvas only: e.g. https://school.instructure.com"
    ),
    token: str | None = typer.Option(
        None, "--token", help="Canvas only: a personal access token (prompted if omitted)."
    ),
) -> None:
    """Connect a personal-assistant data source (Gmail, Outlook, or Canvas)."""
    if provider == "gmail":
        from lydia.connectors.auth import gmail_oauth
        ui.print_info("Opening a browser to sign in to Gmail...")
        try:
            gmail_oauth.login()
        except gmail_oauth.GmailAuthError as exc:
            ui.print_error(str(exc))
            raise typer.Exit(1)
        ui.print_info("Signed in to Gmail.")
    elif provider == "outlook":
        from lydia.connectors.auth import outlook_oauth
        if not client_id:
            client_id = typer.prompt("Azure app Application (client) ID")
        try:
            outlook_oauth.login(client_id, on_code=lambda msg: ui.console.print(msg))
        except outlook_oauth.OutlookAuthError as exc:
            ui.print_error(str(exc))
            raise typer.Exit(1)
        ui.print_info("Signed in to Outlook.")
    elif provider == "canvas":
        from lydia.config import secrets
        if not base_url:
            base_url = typer.prompt("Canvas base URL (e.g. https://school.instructure.com)")
        if not token:
            token = typer.prompt("Canvas personal access token", hide_input=True)
        save_config_value("canvas_base_url", base_url, global_config_path())
        secrets.set_secret(secrets.CANVAS_TOKEN, token)
        ui.print_info(f"Canvas configured: {base_url}")
    else:
        ui.print_error(f"Unknown provider '{provider}'. Use one of: {', '.join(AUTH_PROVIDERS)}.")
        raise typer.Exit(1)


@auth_app.command("status")
def auth_status() -> None:
    """Show which personal-assistant sources are connected."""
    from lydia.config import secrets
    from lydia.connectors.auth import gmail_oauth, outlook_oauth

    config = load_config()
    rows = [
        ("gmail", gmail_oauth.is_logged_in()),
        ("outlook", outlook_oauth.is_logged_in()),
        ("canvas", bool(config.canvas_base_url and secrets.get_secret(secrets.CANVAS_TOKEN))),
    ]
    for name, connected in rows:
        marker = "[green]connected[/green]" if connected else "[dim]not connected[/dim]"
        ui.console.print(f"  {name:<8} {marker}")


@auth_app.command("logout")
def auth_logout(provider: str = typer.Argument(..., help="gmail | outlook | canvas")) -> None:
    """Disconnect a personal-assistant data source."""
    if provider == "gmail":
        from lydia.connectors.auth import gmail_oauth
        gmail_oauth.logout()
    elif provider == "outlook":
        from lydia.connectors.auth import outlook_oauth
        outlook_oauth.logout()
    elif provider == "canvas":
        from lydia.config import secrets
        secrets.delete_secret(secrets.CANVAS_TOKEN)
    else:
        ui.print_error(f"Unknown provider '{provider}'. Use one of: {', '.join(AUTH_PROVIDERS)}.")
        raise typer.Exit(1)
    ui.print_info(f"Disconnected {provider}.")


@briefing_app.command("run")
def briefing_run(
    notify: bool = typer.Option(
        False, "--notify", help="Also push a macOS notification with a one-line summary."
    ),
) -> None:
    """Generate today's personal briefing (email, Canvas, stock market, AI news)."""
    from lydia.cli.briefing import run_briefing
    raise typer.Exit(run_briefing(load_config(), notify=notify))


@briefing_app.command("show")
def briefing_show() -> None:
    """Print the last generated briefing."""
    from lydia.cli.briefing import show_briefing
    raise typer.Exit(show_briefing())


@schedule_app.command("enable")
def schedule_enable(
    time: str | None = typer.Option(
        None, "--time", help="24-hour HH:MM, e.g. 08:00. Defaults to the last-used (or 08:00) time."
    ),
) -> None:
    """Schedule `lydia briefing run --notify` to fire automatically every day."""
    from lydia.cli import scheduler

    config = load_config()
    chosen_time = time or config.briefing_schedule_time
    try:
        plist_path = scheduler.enable(chosen_time)
    except scheduler.ScheduleError as exc:
        ui.print_error(str(exc))
        raise typer.Exit(1)
    save_config_value("briefing_schedule_enabled", True, global_config_path())
    save_config_value("briefing_schedule_time", chosen_time, global_config_path())
    ui.print_info(f"Scheduled daily briefing at {chosen_time} ({plist_path}).")


@schedule_app.command("disable")
def schedule_disable() -> None:
    """Stop the scheduled daily briefing."""
    from lydia.cli import scheduler

    scheduler.disable()
    save_config_value("briefing_schedule_enabled", False, global_config_path())
    ui.print_info("Scheduled briefing disabled.")


def main() -> None:
    try:
        app()
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
