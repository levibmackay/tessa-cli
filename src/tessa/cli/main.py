"""Tessa command-line entry point.

    tessa                      interactive chat (default)
    tessa ask "question"       one-shot question, prints the answer
    tessa analyze              summarize the current project
    tessa index                build/refresh the semantic search index
    tessa models               list installed Ollama models
    tessa init                 create .tessa/ in the current project
    tessa config show          print effective configuration
    tessa config set KEY VAL   set a config value (global or --project)
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import typer
from rich.table import Table

from tessa import __version__
from tessa.agent import facts
from tessa.cli import ui
from tessa.cli.chat import resolve_model, run_chat
from tessa.config.settings import (
    coerce_value,
    find_project_root,
    global_config_path,
    load_config,
    project_config_path,
    save_config_value,
)
from tessa.context.indexer import EMBED_MODEL, build_index
from tessa.context.scanner import scan_project
from tessa.llm.client import OllamaClient, OllamaError
from tessa.llm.types import Message

app = typer.Typer(
    name="tessa",
    help="Tessa — a local AI coding agent powered by Ollama.",
    add_completion=False,
    no_args_is_help=False,
)
config_app = typer.Typer(help="View and change configuration.")
app.add_typer(config_app, name="config")
memory_app = typer.Typer(help="View and manage remembered project facts.")
app.add_typer(memory_app, name="memory")


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
        ui.console.print(f"tessa {__version__}")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        raise typer.Exit(run_chat(load_config()))


@app.command()
def ask(
    question: str = typer.Argument(..., help="A single question for Tessa."),
    model: str | None = typer.Option(None, "--model", "-m", help="Override the model."),
) -> None:
    """Ask one question and print the answer (useful for scripts)."""
    config = load_config()
    if model:
        config.model = model
    with OllamaClient(host=config.ollama_host) as client:
        try:
            resolved = resolve_model(client, config)
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
    with OllamaClient(host=config.ollama_host) as client:
        if not client.is_alive():
            ui.print_error(f"Cannot reach Ollama at {config.ollama_host}.")
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
    with OllamaClient(host=config.ollama_host) as client:
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
    """Create a .tessa/ directory in the current project."""
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
    for key, value in vars(config).items():
        shown = value if value is not None else "[dim]auto[/dim]"
        ui.console.print(f"  {key} = {shown}")


@config_app.command("set")
def config_set(
    key: str = typer.Argument(..., help="Config key, e.g. model"),
    value: str = typer.Argument(..., help="New value"),
    project: bool = typer.Option(False, "--project", "-p", help="Write to the project config instead of global."),
) -> None:
    """Set a configuration value, e.g. `tessa config set model qwen3.5:9b`."""
    if project:
        root = find_project_root()
        if root is None:
            ui.print_error("Not inside a project (no .tessa/ or .git found). Run `tessa init` first.")
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
        ui.print_info("No facts remembered yet. Use `tessa memory add <fact>` to add one.")
        return
    for i, fact in enumerate(remembered, start=1):
        ui.console.print(f"  {i}. {fact.text}  [dim]{fact.created_at}[/dim]")


@memory_app.command("add")
def memory_add(fact: str = typer.Argument(..., help="The fact to remember")) -> None:
    """Remember a fact about the current project."""
    saved = facts.remember(_memory_root(), fact)
    ui.print_info(f"Remembered: {saved.text}")


@memory_app.command("forget")
def memory_forget(index: int = typer.Argument(..., help="Fact number, as shown by `tessa memory list`")) -> None:
    """Forget a remembered fact by number."""
    try:
        removed = facts.forget(_memory_root(), index)
    except ValueError as exc:
        ui.print_error(str(exc))
        raise typer.Exit(1)
    ui.print_info(f"Forgot: {removed.text}")


def main() -> None:
    try:
        app()
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
