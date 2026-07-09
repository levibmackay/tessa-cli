"""Configuration management for Tessa.

Two layers of configuration, merged in order (later wins):

1. Global:  ~/.tessa/config.json         — user-wide defaults
2. Project: <project>/.tessa/config.json — per-repository overrides

Both are plain JSON so they are easy to inspect and edit by hand.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

GLOBAL_DIR = Path.home() / ".tessa"
PROJECT_DIR_NAME = ".tessa"
CONFIG_FILE_NAME = "config.json"


@dataclass
class TessaConfig:
    """All tunable settings for Tessa."""

    model: str | None = None  # None = auto-detect best installed model
    temperature: float = 0.7
    num_ctx: int = 8192
    ollama_host: str = "http://localhost:11434"
    # Reasoning for thinking-capable models (qwen3, deepseek-r1):
    # auto = model default, on/off = force. "off" gives much faster replies.
    think: str = "auto"
    # Permission mode for run_command: ask | auto | deny (see tools/terminal.py)
    permission_mode: str = "ask"
    # How long Ollama keeps the model loaded in memory after a request, so a
    # session doesn't pay the multi-second reload cost on every message.
    # Ollama duration string ("30m", "1h") or "-1" to never unload.
    keep_alive: str = "30m"
    # If set, talk to a remote Tessa Server at this URL instead of a local
    # Ollama daemon (see llm/factory.py::build_client). None = local-only,
    # today's behavior, unchanged.
    server_url: str | None = None
    api_key: str | None = None  # bearer token for server_url, if set

    @property
    def think_flag(self) -> bool | None:
        return {"on": True, "off": False}.get(self.think)

    def merged_with(self, overrides: dict[str, Any]) -> "TessaConfig":
        """Return a new config with known keys from *overrides* applied."""
        known = {f.name for f in fields(self)}
        data = asdict(self)
        for key, value in overrides.items():
            if key in known:
                data[key] = value
            else:
                logger.warning("Ignoring unknown config key: %s", key)
        return TessaConfig(**data)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Could not read config %s: %s", path, exc)
        return {}


def find_project_root(start: Path | None = None) -> Path | None:
    """Walk upward from *start* looking for a .tessa/ or .git/ directory."""
    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if (candidate / PROJECT_DIR_NAME).is_dir() or (candidate / ".git").is_dir():
            return candidate
    return None


def global_config_path() -> Path:
    return GLOBAL_DIR / CONFIG_FILE_NAME


def project_config_path(project_root: Path) -> Path:
    return project_root / PROJECT_DIR_NAME / CONFIG_FILE_NAME


def load_config(project_root: Path | None = None) -> TessaConfig:
    """Load defaults, then apply global config, then project config."""
    config = TessaConfig()
    config = config.merged_with(_read_json(global_config_path()))
    root = project_root if project_root is not None else find_project_root()
    if root is not None:
        config = config.merged_with(_read_json(project_config_path(root)))
    return config


def save_config_value(key: str, value: Any, path: Path) -> None:
    """Set a single key in the JSON config file at *path*, creating it if needed."""
    known = {f.name for f in fields(TessaConfig)}
    if key not in known:
        raise KeyError(f"Unknown config key '{key}'. Valid keys: {', '.join(sorted(known))}")
    data = _read_json(path)
    data[key] = value
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def coerce_value(key: str, raw: str) -> Any:
    """Convert a CLI string like '0.3' into the right type for *key*."""
    for f in fields(TessaConfig):
        if f.name != key:
            continue
        if f.type in ("float", float):
            return float(raw)
        if f.type in ("int", int):
            return int(raw)
        return raw
    return raw
