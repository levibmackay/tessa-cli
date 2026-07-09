# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Tessa is a local AI coding agent CLI — a personal, API-key-free alternative to
Claude Code / Cursor, built on top of a local [Ollama](https://ollama.com)
daemon. It is a portfolio project for Levi (CS student), so code quality,
tests, and a clean architecture matter more than shipping speed.

## Commands

```bash
# Install (editable) into the project venv — do this after adding a dependency
.venv/bin/pip install -e ".[dev]"

# Run the full test suite
.venv/bin/pytest

# Run a single test file / test
.venv/bin/pytest tests/test_agent_loop.py
.venv/bin/pytest tests/test_agent_loop.py::test_tool_call_then_final_answer

# Run the CLI itself (after install -e, `tessa` is also on PATH via a symlink
# into /opt/homebrew/bin)
tessa                      # interactive chat REPL in the current project
tessa ask "question"       # one-shot, no tools, good for smoke-testing the LLM layer
tessa analyze              # project scanner output
tessa config show
```

There is no separate lint/format command configured yet.

### Testing against the real Ollama daemon

Unit tests never touch the network (`httpx.MockTransport` for the LLM client,
tmp_path repos for git/filesystem tools) — `pytest` should never require
Ollama to be running. To manually exercise the real thing:

```bash
ollama list                 # confirm a model is pulled; qwen3.5 variants are what's tested locally
tessa config set think off  # qwen3 is a thinking model; off = much faster manual testing
```

When testing the agent loop end-to-end (tool calls + confirmation prompts),
piping input via `printf ... | tessa` is unreliable — Rich's `Confirm.ask`
and `prompt_toolkit` fight over a non-tty stdin and the confirm dialog will
spuriously EOFError (it fails *safe*, i.e. auto-declines, so this looks like
a bug but isn't one). If you need to script an end-to-end test of a
confirmation flow, drive it through a real pty (see git history around the
Milestone 3 commit for a working example using Python's `pty` module), not a
plain pipe.

## Architecture

Layering, outer to inner — each layer only depends on the ones below it:

```
cli/     Typer commands + Rich rendering + prompt_toolkit REPL   (depends on: agent, llm, config, context)
agent/   orchestration: system prompt, tool registry, the loop   (depends on: llm, tools, config)
tools/   pure functions that touch the filesystem/shell/git      (depends on: nothing else in tessa)
llm/     Ollama HTTP client, streaming, types                    (depends on: nothing else in tessa)
context/ project scanner (languages, manifests, largest files)   (depends on: nothing else in tessa)
config/  layered JSON settings                                   (depends on: nothing else in tessa)
```

`tools/` must stay UI- and agent-agnostic: every function takes a project
root and plain arguments and returns plain data or raises `ToolError`. It
knows nothing about confirmation prompts, risk levels, or the LLM.

`agent/tools.py` is where UI-independent policy lives: it wraps each
`tools/*` function in a `ToolSpec` with a JSON schema (sent to the model)
and a risk tier (`safe` / `confirm` / `command`). Confirmation itself is a
callback (`ToolContext.confirm`) injected from outside — `agent/` never
imports `rich` or `cli`. The Rich-based confirm dialog lives in
`cli/ui.py::confirm` and is wired in by `cli/chat.py`.

`agent/loop.py::run_agent_turn` is the plan → call tool → observe → respond
loop. It's intentionally free of any I/O side effects it doesn't own: it
takes a `stream_fn` callable to render (or silently drain) the model's
streaming output, and `on_tool_call` / `on_tool_result` hooks for the
console. This is what makes it testable with a fake client
(`tests/test_agent_loop.py::FakeClient`) instead of hitting Ollama.

### The Ollama integration gotchas

- Ollama's *thinking* models (qwen3.5, deepseek-r1, ...) stream reasoning in
  a separate `message.thinking` field, not `message.content`. If you only
  read `content` the reply looks empty until the model finishes "thinking".
  Both fields are parsed in `llm/client.py::OllamaClient._parse_chunk` and
  rendered in `cli/ui.py` (dimmed, collapsing preview).
- Tool calls arrive as one complete (non-streamed) `message.tool_calls` list
  in a single chunk, even when `stream: true` — they are never token-by-token
  streamed. See `llm/types.py::ToolCall` and the parsing in
  `llm/client.py::OllamaClient._parse_chunk`.
- Ollama unloads a model from memory 5 minutes after its last request by
  default, and reloading costs several seconds — noticeable as a stall on
  the first message of a new session. `config.keep_alive` (default `30m`)
  is passed on every `chat_stream` call specifically to avoid this; don't
  drop it when adding a new call site.
- Not every model that looks like it supports tool calling actually wires
  it into Ollama's structured `message.tool_calls` field — some (e.g.
  `qwen2.5-coder:7b`) write the call as plain JSON text inside
  `message.content` instead, which `run_agent_turn` never parses, so the
  model silently never uses any tool. Before recommending a model as a
  default, verify empirically with a trivial curl call, not by assumption:
  ```
  curl -s http://localhost:11434/api/chat -d '{"model":"MODEL","stream":false,
  "messages":[{"role":"user","content":"weather in Paris? use the tool"}],
  "tools":[{"type":"function","function":{"name":"get_weather","description":"x",
  "parameters":{"type":"object","properties":{"city":{"type":"string"}},"required":["city"]}}}]}'
  ```
  and check the response has a `tool_calls` field on `message`, not JSON text in `content`.

### Path safety

Every tool that touches the filesystem resolves paths through
`tools/paths.py::resolve_within`, which refuses anything that escapes the
project root (`..`, absolute paths elsewhere). Don't bypass this by calling
`Path` directly on user/model-supplied paths inside a new tool.

### Config layering

`config/settings.py::load_config` merges `~/.tessa/config.json` (global) then
`<project>/.tessa/config.json` (project, found by walking up for a `.tessa/`
or `.git/` directory) — project wins. Unknown keys are ignored with a
warning rather than erroring, so old config files don't break on upgrade.

## Current state and what's next

See `README.md` for the user-facing feature list and `ROADMAP.md` for the
detailed next-steps plan. Short version: Milestones 1 (CLI + streaming
chat), 3 (agent loop + tool calling + git), and 6 (persistent project
memory — `agent/facts.py`, distinct from the raw session transcript in
`agent/memory.py`) are done. Milestone 2 (embeddings/retrieval, needed once
a project is too big for full-file context) is not started. Check
`ROADMAP.md` before picking up new work — it has the reasoning for why M3
was done before M2, and concrete next steps with file-level pointers.

## Standing preferences for this repo

- **Never add a `Co-Authored-By: Claude` (or any Claude/Anthropic)
  attribution trailer to commit messages here.** The user wants to be the
  sole contributor shown on GitHub — this was explicitly requested and
  enforced once already by rewriting pushed history to strip it.
