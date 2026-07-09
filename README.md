# Tessa

A local AI coding agent for your terminal. No API keys, no cloud — everything
runs on your machine through [Ollama](https://ollama.com).

```
╭─ TESSA ─────────────────────────╮
│ model    qwen3.5:9b             │
│ project  Python                 │
╰── local AI coding agent v0.1.0 ─╯

Tessa > explain this project
```

## Requirements

- Python 3.11+
- [Ollama](https://ollama.com) with at least one model pulled
  (`ollama pull qwen3.5`)

## Install

```bash
git clone <this repo> && cd tessa
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
ln -s "$PWD/.venv/bin/tessa" /opt/homebrew/bin/tessa   # or anywhere on your PATH
```

## Usage

| Command | What it does |
|---|---|
| `tessa` | Interactive chat with your codebase context |
| `tessa ask "why is this failing?"` | One-shot question |
| `tessa analyze` | Project summary: languages, size, key files |
| `tessa models` | List installed Ollama models |
| `tessa init` | Create `.tessa/` project config |
| `tessa config show` | Show effective config |
| `tessa config set model qwen3.5:9b` | Set a config value (`--project` for per-repo) |

Inside chat: `/help`, `/model <name>`, `/models`, `/new`, `/exit`.

## Configuration

Layered JSON config — project overrides global:

- `~/.tessa/config.json` — global defaults
- `<project>/.tessa/config.json` — per-repository (created by `tessa init`)

Keys: `model` (default: auto-pick best installed coder model), `temperature`,
`num_ctx`, `ollama_host`, `think` (`auto`/`on`/`off` — reasoning for thinking
models like qwen3; `off` gives much faster replies), `permission_mode`
(`ask`/`auto`/`deny` — controls whether `run_command` prompts before running
safe-looking shell commands; destructive ones always prompt regardless).

## Agent tools

Inside chat, Tessa can call tools against your project (needs a model that
supports Ollama tool calling — qwen3.5, qwen2.5, llama3.1+ all work):

| Tool | Risk | Behavior |
|---|---|---|
| `read_file`, `list_dir`, `search_code` | safe | runs immediately |
| `git_status`, `git_diff`, `git_add` | safe | runs immediately |
| `write_file`, `delete_file` | confirm | shows a diff, asks y/n, keeps a backup in `.tessa/backups/` |
| `git_commit`, `git_push` | confirm | shows the message/target, asks y/n |
| `run_command` | policy | safe-looking commands follow `permission_mode`; commands matching a destructive pattern (`rm -rf`, `git push --force`, `sudo`, piping curl into a shell, ...) always ask |

All file paths are resolved relative to the project root and refused if
they try to escape it (`..`, absolute paths outside the project).

## Architecture

```
src/tessa/
├── cli/       Typer commands, chat REPL, Rich rendering
├── config/    layered JSON settings
├── llm/       Ollama HTTP client, streaming, model selection
├── agent/     prompts, conversation memory   (agent loop: Milestone 3)
├── context/   repository scanner             (retrieval: Milestone 2)
└── tools/     filesystem / terminal / git tools (Milestones 3–5)
```

## Roadmap

- [x] **M1** — packaged CLI, streaming chat, config, project analysis
- [x] **M3** — agent loop with tool calling, safe file editing (diff + confirm), command execution with a permission system, git workflows (status/diff/add/commit/push)
- [ ] **M2** — code indexing and retrieval (embeddings via Ollama) — for repos too large for full-file context
- [ ] **M6** — persistent project memory (remembered facts across sessions, not just history)
- [ ] **M7** — plugins

## Development

```bash
.venv/bin/pytest
```
