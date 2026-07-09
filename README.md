# Tessa

[![tests](https://github.com/levibmackay/tessa-cli/actions/workflows/test.yml/badge.svg)](https://github.com/levibmackay/tessa-cli/actions/workflows/test.yml)

**A local AI coding agent for your terminal — no API keys, no subscriptions,
no cloud.** Tessa reads your code, answers questions about it, edits files,
runs commands, and drives git, all through a local [Ollama](https://ollama.com)
model running on your own machine.

It's a personal alternative to tools like Claude Code, Cursor's agent, or
GitHub Copilot Workspace, built for anyone who wants that workflow without
paying for API usage or sending code to a third party.

```
████████╗███████╗███████╗███████╗ █████╗
╚══██╔══╝██╔════╝██╔════╝██╔════╝██╔══██╗
   ██║   █████╗  ███████╗███████╗███████║
   ██║   ██╔══╝  ╚════██║╚════██║██╔══██║
   ██║   ███████╗███████║███████║██║  ██║
   ╚═╝   ╚══════╝╚══════╝╚══════╝╚═╝  ╚═╝

╭───────────────────────╮
│ model  qwen3.5:9b     │
│ project  Python       │
╰───────────────────────╯
Type your request, or /help for commands. Ctrl-D to exit.

Tessa > add input validation to the login handler and run the tests
```

## Why

Claude Code and similar tools are genuinely useful, but they require an API
key and send your code to a hosted model. Tessa is the same *workflow* —
an agent that reads your project, proposes changes, and asks before doing
anything risky — running entirely against models you've already pulled with
Ollama. Nothing leaves your machine. Nothing costs anything per token.

The tradeoff is real: local models on consumer hardware are smaller and
slower than frontier hosted models, so Tessa won't be as capable. It's built
for personal projects, learning, and situations where "good enough and free"
beats "best available and metered."

## Features

- **Interactive chat** with full streaming output, Markdown rendering, and
  live-updating "thinking" previews for reasoning models like Qwen3.
- **An actual agent loop**, not just chat: Tessa can read files, search your
  codebase, propose edits as a diff, run shell commands, and drive git — by
  calling tools the model itself decides to use, via Ollama's native
  function-calling support.
- **Nothing happens to your files or repo without a diff and a yes/no
  prompt.** Writes and deletes always show what's about to change and keep
  a timestamped backup; commits and pushes always show the message/target
  first. Shell commands follow a configurable permission policy, and
  anything that matches a destructive pattern (`rm -rf`, `git push --force`,
  `sudo`, piping a remote script into a shell, ...) is *always* confirmed
  regardless of that policy.
- **Project-aware from the first message.** A repository scanner detects
  the language mix, project type, and key manifest files, and feeds that
  into the system prompt automatically.
- **Per-project and global configuration**, so you can pin a smaller/faster
  model for one repo and a larger one for another.
- **Path-sandboxed by construction.** Every filesystem tool resolves paths
  relative to the project root and refuses anything that tries to escape it.

## Requirements

- Python 3.11+
- [Ollama](https://ollama.com), running locally, with at least one model
  pulled — a model with tool-calling support is needed for the agent
  features (Qwen3.5, Qwen2.5, Llama 3.1+ all work):

  ```bash
  ollama pull qwen3.5
  ```

## Install

```bash
git clone https://github.com/levibmackay/tessa-cli.git && cd tessa-cli
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
ln -s "$PWD/.venv/bin/tessa" /opt/homebrew/bin/tessa   # or anywhere on your PATH
```

## Usage

| Command | What it does |
|---|---|
| `tessa` | Interactive agent chat in the current project |
| `tessa ask "why is this failing?"` | One-shot question, no tools, good for scripts |
| `tessa ask "..." --yes` | Same, but with full tool access — auto-approves everything except dangerous commands, for scripts/CI with no one to answer a y/n prompt |
| `tessa analyze` | Project summary: languages, size, key files |
| `tessa models` | List installed Ollama models |
| `tessa index` | Build/refresh the semantic search index (for `search_semantic`) |
| `tessa restore list` / `apply <n>` | List/restore file backups from `.tessa/backups/` |
| `tessa init` | Create `.tessa/` project config |
| `tessa config show` | Show effective (merged) configuration |
| `tessa config set model qwen3.5:9b` | Set a config value (`--project` for per-repo) |
| `tessa memory list` / `add <fact>` / `forget <n>` | View/manage facts Tessa remembers about this project |

Inside chat: `/help`, `/model <name>`, `/models`, `/new` (fresh conversation),
`/remember <fact>`, `/memory`, `/forget <n>`, `/exit`.

### A typical session

```
Tessa > fix the bug where login accepts an empty password

› read_file(path='src/auth/login.py')
  read src/auth/login.py
› search_code(pattern='def login')
  searched for 'def login'
Found it — login() never checks that password is non-empty before
comparing the hash. Here's the fix:

› write_file(path='src/auth/login.py', content='...')
╭──────────── Update src/auth/login.py ────────────╮
│ --- a/src/auth/login.py                           │
│ +++ b/src/auth/login.py                           │
│ @@ -12,6 +12,8 @@                                 │
│  def login(username, password):                   │
│ +    if not password:                              │
│ +        raise ValueError("password required")     │
│      user = find_user(username)                   │
╰────────────────────────────────────────────────────╯
Proceed? [y/n] (y): y
  Updated src/auth/login.py

I added a check that rejects an empty password before it ever reaches the
hash comparison. Want me to run the test suite?
```

## Configuration

Layered JSON config — project overrides global:

- `~/.tessa/config.json` — global defaults
- `<project>/.tessa/config.json` — per-repository (created by `tessa init`)

| Key | Default | Meaning |
|---|---|---|
| `model` | auto | Ollama model name; auto-picks the best installed coder model if unset |
| `temperature` | `0.7` | Sampling temperature |
| `num_ctx` | `8192` | Context window size passed to Ollama |
| `ollama_host` | `http://localhost:11434` | Where the Ollama daemon is listening |
| `think` | `auto` | `auto`/`on`/`off` — reasoning for thinking models (Qwen3, DeepSeek-R1); `off` is much faster |
| `permission_mode` | `ask` | `ask`/`auto`/`deny` — whether `run_command` prompts before running safe-looking shell commands (destructive ones always prompt) |
| `keep_alive` | `30m` | How long Ollama keeps the model loaded after a request; avoids a multi-second reload on your next message. Ollama duration string, or `-1` to never unload |
| `server_url` | not set | If set, talk to a remote Tessa Server instead of a local Ollama daemon — see [Running Tessa Server](#running-tessa-server-remote-gpu-inference) |
| `api_key` | not set | Bearer token for `server_url` |

## Performance and model choice

Local models are the whole point of Tessa, but they're not free-riding on a
frontier hosted model's scale — a few things make a real difference on
consumer hardware:

- **Use a coding-specific model, not a generic chat model**, if your
  hardware allows it. `qwen2.5-coder` / `qwen3.5-coder` / `deepseek-coder`
  are trained specifically on code and noticeably outperform a generic
  model of the same size on programming tasks. `llm/models.py` already
  prefers these automatically if you have one installed — you just need to
  `ollama pull` one.
- **Match model size to your RAM.** As a rough guide on Apple Silicon: 16GB
  comfortably handles up to ~7-9B models; going bigger risks swapping, which
  is far slower than a smaller model outright. `qwen2.5-coder:7b` is a
  solid default on a 16GB machine.
- **`think: off`** if you're on a reasoning model (Qwen3, DeepSeek-R1) and
  want speed over the model showing its work — reasoning tokens can easily
  add 10-30s to a reply before the actual answer starts.
- **`keep_alive`** (above) avoids paying Ollama's model-load cost
  (multi-second) on every single message in a session.

None of this closes the gap with a large hosted model — it narrows it as
much as the "runs entirely on your machine" constraint allows.

## Running Tessa Server (remote/GPU inference)

If you have a second machine with more RAM or a real GPU — a gaming PC,
say — you can run inference there instead and keep using `tessa` normally
from a laptop. **Tool execution (file edits, git, shell commands) always
stays on whichever machine runs the CLI** — only chat/tool-call inference
and embeddings go over the network. This means `tessa "fix this bug"`
works exactly the same, from any directory, whether it's talking to a
local Ollama or a remote one.

```bash
# On the server machine (needs Ollama already running):
pip install -e . -e server/            # from the repo root, one shared venv
TESSA_SERVER_TOKEN=<a-long-random-token> tessa-server

# On the client machine:
tessa config set server_url https://<server-host>:<port>
tessa config set api_key <the-same-token>
tessa                                   # works exactly as before
```

Full server configuration (env vars), API design, and the reasoning behind
the client/server split live in [`server/README.md`](server/README.md).

## Agent tools and the safety model

Inside chat, Tessa can call tools against your project. Every tool is
classified into a risk tier that decides whether it needs your approval:

| Tool | Risk | Behavior |
|---|---|---|
| `read_file`, `list_dir`, `search_code` | safe | Runs immediately |
| `git_status`, `git_diff`, `git_add` | safe | Runs immediately |
| `write_file`, `delete_file` | confirm | Shows a diff, asks y/n, keeps a backup in `.tessa/backups/` |
| `git_commit`, `git_push` | confirm | Shows the message/target, asks y/n |
| `run_command` | policy | Safe-looking commands follow `permission_mode`; anything matching a destructive pattern always asks, regardless of mode |
| `remember` | safe | Saves a fact to `.tessa/memory.json` so it's known in future sessions |
| `search_semantic` | safe | Meaning-based search over an embedding index (`tessa index` first); falls back to literal `search_code` if not indexed |

All file paths are resolved relative to the project root and refused if they
try to escape it (`..`, absolute paths outside the project) — a confused or
adversarial model can't touch files elsewhere on your machine.

## Memory

Tessa keeps two different kinds of history, deliberately separate:

- **Session transcripts** (`.tessa/history/*.jsonl`) — a full append-only log
  of every conversation, one file per session. Useful for debugging, not fed
  back into future conversations, and git-ignored.
- **Remembered facts** (`.tessa/memory.json`) — a short, curated list of
  things worth persisting across sessions (tech stack, conventions,
  decisions), added either by you (`/remember <fact>` in chat, or `tessa
  memory add <fact>`) or by the model itself via the `remember` tool when
  you tell it something worth keeping. These are folded into the system
  prompt on every session, so Tessa actually remembers them next time you
  open the project — and unlike history, this file is meant to be committed.

## Architecture

```
tessa-cli/
├── src/tessa/
│   ├── cli/       Typer commands, the chat REPL, Rich rendering
│   ├── agent/     system prompt, tool registry, the plan→call→observe→respond loop
│   ├── tools/     pure functions: filesystem, terminal, git — no UI/agent knowledge
│   ├── llm/       ModelClient protocol + two implementations: OllamaClient
│   │               (local daemon) and RemoteClient (a Tessa Server)
│   ├── context/   repository scanner + semantic search index
│   ├── database/  SQLite storage for the semantic index
│   └── config/    layered JSON settings
│
└── server/        optional: FastAPI inference proxy for a remote/GPU
                    Ollama — see "Running Tessa Server" above. Tool
                    execution never happens here; only inference does.
```

`agent/`, `tools/`, `context/` etc. type-hint against `llm.protocol.ModelClient`,
not a concrete client class — this is what lets `tessa` talk to either a
local Ollama daemon or a remote Tessa Server with zero code changes
anywhere except `llm/factory.py::build_client`, which picks based on
whether `server_url` is configured.

See `CLAUDE.md` for the layering rules and the non-obvious integration
details (how thinking-model output and tool calls are actually shaped in
Ollama's streaming API, why `tools/` never imports `agent/` or `cli/`, etc.)
— written for an AI coding assistant picking this project back up, but
useful for a human too.

## Development

```bash
.venv/bin/pytest                                    # CLI suite (140 tests, no Ollama required)
.venv/bin/pytest tests/test_agent_loop.py            # one file
.venv/bin/pytest tests/test_agent_loop.py::test_tool_call_then_final_answer  # one test

cd server && ../.venv/bin/pytest                    # server suite (14 tests, no Ollama required)
```

All tests are hermetic — the LLM client is tested against
`httpx.MockTransport`, git/filesystem tools run against a real throwaway
repo in `tmp_path`, the server is tested against a fake `ModelClient`
double. None of them require a running Ollama daemon.

## Roadmap

Milestones 1 (core CLI), 2 (semantic retrieval), 3 (agent loop, tool
calling, git workflows), 6 (persistent project memory), and the
client/server split (`server/`, remote inference over Tailscale) are done.
See [`ROADMAP.md`](ROADMAP.md) for what's left — packaging, and the M7
plugins stretch goal, plus deferred server work (real multi-user token
storage, a task queue, non-Ollama providers) that the current design
doesn't block but doesn't need yet either.

## License

MIT — see [`LICENSE`](LICENSE).
