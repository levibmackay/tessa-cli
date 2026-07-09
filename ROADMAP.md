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
- **M6 — Persistent project memory.** `agent/facts.py` stores a curated,
  capped list of facts at `.tessa/memory.json` (separate from the raw
  session transcript in `agent/memory.py`, which is a log, not something fed
  back into future conversations). Facts are folded into the system prompt
  via `agent/prompts.py::build_system_prompt`. Three ways to add one: the
  model calling the `remember` tool mid-conversation, `/remember <fact>` /
  `/memory` / `/forget <n>` slash commands in chat, or `tessa memory
  add/list/forget` outside of chat. Verified end-to-end: a fact added in one
  process is present in a fresh process's system prompt with no extra steps.

- **CI.** `.github/workflows/test.yml` runs the full suite on Python
  3.11-3.13 for every push/PR. Verified against a clean clone with no
  pre-existing git identity — the git-tool tests set repo-local identity
  themselves, so no CI-side git config is needed.
- **M2 — Retrieval for large repos.** `context/indexer.py` chunks source
  files into language-agnostic ~60-line windows (snapped to the nearest
  blank line within a short lookahead, so boundaries usually land between
  functions) and embeds each one via Ollama (`nomic-embed-text`, 768-dim).
  `database/sqlite.py` stores chunks + embeddings as float32 blobs in
  `.tessa/index.sqlite3`. Re-indexing is incremental — a file is only
  re-embedded if its content hash changed since the last index. New safe
  tool `search_semantic` in `agent/tools.py`, offered alongside literal
  `search_code`; it reports "not indexed yet" cleanly if `tessa index`
  hasn't been run. Verified end-to-end: indexed a real project, confirmed
  incremental re-runs skip unchanged files and pick up changed/deleted
  ones, and confirmed the real agent loop (not just the retriever in
  isolation) chooses `search_semantic` correctly and gives the right
  answer against a live Ollama daemon, 3/3 runs.

**Model gotcha found while shipping M2:** not every model that emits
reasonable-looking tool-call JSON actually wires it into Ollama's
structured `tool_calls` field — `qwen2.5-coder:7b` writes the call as
plain text in `message.content` instead, which `run_agent_turn` never
parses, so it silently never uses *any* tool. Confirmed via a direct
`/api/chat` call with a trivial tool before trusting it as a default.
Verify tool-calling support empirically (a simple curl test, not vibes)
before recommending a new default model — see `CLAUDE.md` for the check.

M3 was done before M2 on purpose: it was the part that turns Tessa into an
*agent* rather than a chatbot, and every repo tested against so far fits
comfortably in a model's context window, so retrieval wasn't yet the
bottleneck as of M3. M2 removes that ceiling for larger repos.

## Next up

### M7 — Plugins (stretch)

Lowest priority; only worth doing once M2 is solid. Original idea from
project scoping: VS Code extension, browser automation, voice mode, web
search, doc lookup, CI/CD integration. No design work has started — if you
pick this up, start by defining what a "plugin" actually extends (a new
tool? a new slash command? both?) before writing code.

## Smaller polish items (no milestone, pick up anytime)

- ~~**Undo command.**~~ Done: `tessa restore list` / `tessa restore apply
  <n>`. Fixed a real bug along the way — backups were previously named
  `{stamp}-{filename}` with no directory info, so two files with the same
  name in different directories (e.g. `src/utils.py` and
  `tests/utils.py`) would silently collide. Backups now live at
  `.tessa/backups/{stamp}/{original/relative/path}`, mirroring the
  project tree, so restoring is unambiguous.
- ~~**More CLI-level tests.**~~ Done: `tests/test_cli_commands.py` covers
  `analyze`, `init`, `config show/set`, `restore list/apply`, and
  `--version` via `CliRunner` (121 tests total). `ask`/`models`/the chat
  REPL are deliberately not covered this way since they need a live
  Ollama daemon — see "Testing against the real Ollama daemon" in
  `CLAUDE.md` for how those get verified instead.
- **Cross-platform.** Checked (not run): grepped the source for hardcoded
  macOS paths, unix-only path joins, and `os.name`/`sys.platform`
  branches — none found; everything routes through `pathlib`. The one
  real, unavoidable limitation: `tools/terminal.py::run_command` uses
  `subprocess.run(..., shell=True)`, which invokes `cmd.exe` on Windows,
  not bash — so unix-style commands a model generates (`ls`, `grep`,
  `rm -rf`) won't translate as-is. This has never actually been run on
  Windows or Linux; "checked via static analysis" is not the same claim
  as "tested," and the distinction matters if you're about to rely on it.
- **Undo command.** Writes/deletes already back up to `.tessa/backups/`
  before touching a file, but there's no `tessa restore` to pull one back —
  right now that's a manual `cp`.
- ~~**`--yes` / non-interactive mode.**~~ Done: `tessa ask "..." --yes`
  gives `ask` full tool access via `ui.auto_confirm`, which approves
  everything except tools/commands flagged dangerous (no human present to
  approve real danger, so it fails safe rather than approving blindly).
  Plain `tessa ask` without `--yes` is unchanged — still tool-free chat.
- **Packaging.** `pyproject.toml` is set up for `pip install -e .`; hasn't
  been published anywhere (PyPI, or even a simple `brew tap`) so the README
  install instructions still say "clone this repo."
- **Cross-platform check.** Everything is written with `pathlib` and should
  be OS-agnostic, but has only actually been run on macOS (Apple Silicon);
  the README's symlink step (`/opt/homebrew/bin`) is Mac-specific — worth a
  pass to confirm behavior on Linux, and Windows is untested entirely.
