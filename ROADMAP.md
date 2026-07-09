# Roadmap

Status snapshot and a concrete plan for what's next. Written so either Levi
or a future Claude Code session can pick up any item without re-deriving
context — each one names the files to touch and what "done" looks like.

## Done

- **M1 — Core CLI.** Typer commands (`tessa`, `ask`, `analyze`, `models`,
  `init`, `config show/set`), a `prompt_toolkit` REPL with history and slash
  commands, Rich streaming Markdown rendering, layered JSON config, model
  auto-selection preferring installed coder models, thinking-model support,
  a gradient ASCII banner.
- **M3 — Agent loop.** Native Ollama tool calling; tools for
  read/list/search/write/delete file, `run_command` with a dangerous-command
  classifier and a permission-mode policy, and git status/diff/add/commit/
  push. File writes/deletes/commits/pushes always show a diff or message and
  require y/n approval; writes/deletes keep a timestamped backup. All
  filesystem tools refuse to touch paths outside the project root.

M3 was done before M2 on purpose: it was the part that turns Tessa into an
*agent* rather than a chatbot, and every repo tested against so far fits
comfortably in a model's context window, so retrieval wasn't yet the
bottleneck. Revisit that ordering call if you start using Tessa on a large
repo and full-file reads start blowing the context budget.

## Next up

### M2 — Retrieval for large repos

**Problem it solves:** `context/scanner.py` gives Tessa a project *summary*,
but the agent still reads whole files via the `read_file` tool. That's fine
up to a few thousand lines; it breaks down on a large monorepo where the
right file isn't obvious and reading candidates one by one burns the context
window.

**Approach:**
1. `context/indexer.py` — chunk source files (function/class-sized, not
   fixed-size — a naive line-count chunker will split mid-function) and
   embed each chunk with Ollama's embeddings API (`nomic-embed-text` is
   small and good for code; not currently pulled, would need `ollama pull
   nomic-embed-text`). Store vectors + chunk metadata (file, line range) in
   SQLite (`database/sqlite.py`, per the original architecture sketch) —
   no need for FAISS/Chroma at the repo sizes Tessa targets; a plain
   `sqlite-vec` or brute-force cosine scan over a few thousand rows is fast
   enough and keeps the "no extra services" philosophy intact.
2. `context/retriever.py` — given a query, embed it and return the top-k
   chunks by cosine similarity.
3. Add a new safe tool, `search_semantic` (alongside the existing literal
   `search_code`), in `agent/tools.py`, so the model can choose between
   exact substring search and meaning-based search.
4. Incremental indexing: hash each file's content; only re-embed files whose
   hash changed since the last `tessa index` (new CLI command) or since the
   index was auto-built at `tessa` startup for small repos.
5. Decide the trigger: auto-index silently for small repos (< some file
   count threshold) on every `tessa` launch, but require an explicit `tessa
   index` for large ones so startup doesn't get slow.

**Done when:** a query about a feature in a 5,000+ file repo finds the
right file without the model needing to `list_dir` its way there manually.

### M6 — Persistent project memory

**Problem it solves:** `agent/memory.py::SessionHistory` is a transcript —
useful for `/new` and debugging, useless for "remember this project uses
PostgreSQL" persisting *across* sessions. Nothing currently reads old
session files back into a new conversation.

**Approach:**
1. `.tessa/memory.json` — a small list of curated facts (not a full
   transcript), each with the text and a timestamp. Add functions to
   `agent/memory.py` (or a new `agent/facts.py`) to load/append/list them.
2. Add a `remember` tool (safe risk tier) to `agent/tools.py` so the model
   can call `remember(fact="this project uses PostgreSQL")` when the user
   says something worth persisting, plus a `/remember <text>` slash command
   in `cli/chat.py` for the user to add one directly.
3. Fold stored facts into `agent/prompts.py::build_system_prompt`, the same
   way project-scanner output already is.
4. Consider a size cap / summarization step so memory.json doesn't grow
   unbounded — out of scope for a first pass, but note it so it doesn't
   surprise anyone later.

**Done when:** telling Tessa a fact in one session and starting a fresh
`tessa` session later (after `/new` or a new process) shows the model still
knows it.

### M7 — Plugins (stretch)

Lowest priority; only worth doing once M2/M6 are solid. Original idea from
project scoping: VS Code extension, browser automation, voice mode, web
search, doc lookup, CI/CD integration. No design work has started — if you
pick this up, start by defining what a "plugin" actually extends (a new
tool? a new slash command? both?) before writing code.

## Smaller polish items (no milestone, pick up anytime)

- **CI.** No GitHub Actions workflow yet. Add `.github/workflows/test.yml`
  running `pytest` on push/PR — the test suite has zero external
  dependencies (Ollama calls are all mocked), so this is a quick win.
- **CLI-level tests.** All 59 existing tests exercise `tools/`, `agent/`,
  `llm/`, `config/`, `context/` directly; nothing uses Typer's `CliRunner`
  against `cli/main.py`. Worth adding a thin layer of tests for `tessa
  analyze`, `tessa config set`, etc.
- **Undo command.** Writes/deletes already back up to `.tessa/backups/`
  before touching a file, but there's no `tessa restore` to pull one back —
  right now that's a manual `cp`.
- **`--yes` / non-interactive mode.** For scripting `tessa ask` with tools,
  or CI usage, a flag that auto-approves `confirm`-tier tools (or a
  permission_mode value for it) would help. Currently `ask` doesn't use
  tools at all, which is a deliberate simplification — revisit if that
  turns out to be too limiting.
- **Packaging.** `pyproject.toml` is set up for `pip install -e .`; hasn't
  been published anywhere (PyPI, or even a simple `brew tap`) so the README
  install instructions still say "clone this repo."
- **Cross-platform check.** Everything is written with `pathlib` and should
  be OS-agnostic, but has only actually been run on macOS (Apple Silicon);
  the README's symlink step (`/opt/homebrew/bin`) is Mac-specific — worth a
  pass to confirm behavior on Linux, and Windows is untested entirely.
