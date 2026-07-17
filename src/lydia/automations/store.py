"""Load/save automation recipes and their runtime state under ~/.lydia/automations/.

Follows agent/facts.py's persisted-JSON pattern. Every path is derived from
AUTOMATIONS_DIR inside each function so tests patch exactly one attribute.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Callable

from lydia.automations.model import Automation, AutomationError, _NAME_RE, validate
from lydia.config.settings import GLOBAL_DIR

logger = logging.getLogger(__name__)

AUTOMATIONS_DIR = GLOBAL_DIR / "automations"
MAX_RUNS = 200
MAX_SEEN_IDS = 500
LOCK_STALE_SECONDS = 600

_RESERVED = {"state", "runs"}  # state.json / runs.json live next to recipes


def recipe_path(name: str) -> Path:
    if not _NAME_RE.match(name or ""):
        raise AutomationError(f"Invalid automation name '{name}'.")
    return AUTOMATIONS_DIR / f"{name}.json"


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Could not read %s: %s", path, exc)
        return default


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def save_automation(auto: Automation) -> Path:
    errors = validate(auto)
    if errors:
        raise AutomationError("; ".join(errors))
    if auto.name in _RESERVED:
        raise AutomationError(f"'{auto.name}' is a reserved name")
    path = recipe_path(auto.name)
    _write_json(path, auto.to_dict())
    return path


def load_automation(name: str) -> Automation:
    path = recipe_path(name)
    if not path.is_file():
        raise AutomationError(f"No automation named '{name}'")
    data = _read_json(path, None)
    if data is None:
        raise AutomationError(f"Could not read {path}")
    return Automation.from_dict(data)


def list_automations() -> list[Automation]:
    if not AUTOMATIONS_DIR.is_dir():
        return []
    autos: list[Automation] = []
    for path in sorted(AUTOMATIONS_DIR.glob("*.json")):
        if path.stem in _RESERVED:
            continue
        data = _read_json(path, None)
        if data is None:
            continue
        try:
            autos.append(Automation.from_dict(data))
        except AutomationError as exc:
            logger.warning("Skipping %s: %s", path, exc)
    return sorted(autos, key=lambda a: a.name)


def delete_automation(name: str) -> bool:
    path = recipe_path(name)
    if not path.is_file():
        return False
    path.unlink()
    return True


def load_state() -> dict:
    return _read_json(AUTOMATIONS_DIR / "state.json", {})


def save_state(state: dict) -> None:
    _write_json(AUTOMATIONS_DIR / "state.json", state)


def load_runs() -> list[dict]:
    return _read_json(AUTOMATIONS_DIR / "runs.json", [])


def append_run(record: dict) -> None:
    runs = load_runs()
    runs.append(record)
    _write_json(AUTOMATIONS_DIR / "runs.json", runs[-MAX_RUNS:])


def try_acquire_lock(now_fn: Callable[[], float] = time.time) -> bool:
    """One tick at a time. A lock older than LOCK_STALE_SECONDS is presumed
    dead (crashed tick) and broken."""
    lock = AUTOMATIONS_DIR / "tick.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    now = now_fn()
    if lock.is_file():
        stamp = _read_json(lock, {"at": 0})
        if now - float(stamp.get("at", 0)) < LOCK_STALE_SECONDS:
            return False
    _write_json(lock, {"at": now})
    return True


def release_lock() -> None:
    (AUTOMATIONS_DIR / "tick.lock").unlink(missing_ok=True)
