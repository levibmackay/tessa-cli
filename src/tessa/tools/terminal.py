"""Command execution with a dangerous-command classifier.

This module only classifies and runs commands — it has no opinion on
*whether* to ask the user first. That policy (permission_mode: auto / ask /
deny) lives in the agent loop, which is the single place that decides
whether to prompt, using `classify_command` as input.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

DEFAULT_TIMEOUT = 120

# Patterns for commands that can cause irreversible damage: wiping the
# filesystem, force-pushing over shared history, rewriting permissions
# recursively, piping remote scripts into a shell, etc. Matched
# case-insensitively against the whole command string.
_DANGEROUS_PATTERNS = [
    r"\bgit\s+push\b.*(--force|-f)\b",
    r"\bgit\s+reset\s+--hard\b",
    r"\bgit\s+clean\s+.*-[a-z]*f",
    r"\bsudo\b",
    r"\bmkfs\b",
    r"\bdd\s+.*of=",
    r">\s*/dev/(sd|nvme|disk)",
    r"\bchmod\s+-R\s+777\b",
    r"\bchown\s+-R\b",
    r"curl[^|]*\|\s*(sh|bash|zsh)\b",
    r"wget[^|]*\|\s*(sh|bash|zsh)\b",
    r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}",  # fork bomb
    r"\b(shutdown|reboot|halt)\b",
    r"\bkill\s+-9\s+1\b",
    r"\bnpm\s+publish\b",
    r"\bdrop\s+(table|database)\b",
]
_DANGEROUS_RE = re.compile("|".join(_DANGEROUS_PATTERNS), re.IGNORECASE)

# Matches any `rm` invocation whose flags include both recursive and force,
# in any combination/order: -rf, -fr, -Rf, -r -f, --recursive --force, ...
_RM_TOKEN_RE = re.compile(r"\brm\s+([^|;&\n]*)")
_RECURSIVE_FLAG_RE = re.compile(r"(^|\s)(-[a-zA-Z]*[rR][a-zA-Z]*|--recursive)(\s|$)")
_FORCE_FLAG_RE = re.compile(r"(^|\s)(-[a-zA-Z]*f[a-zA-Z]*|--force)(\s|$)")


def _has_dangerous_rm(command: str) -> bool:
    for args in _RM_TOKEN_RE.findall(command):
        if _RECURSIVE_FLAG_RE.search(args) and _FORCE_FLAG_RE.search(args):
            return True
    return False


@dataclass
class CommandResult:
    command: str
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False

    @property
    def success(self) -> bool:
        return self.returncode == 0 and not self.timed_out


def classify_command(command: str) -> str:
    """Return 'dangerous' or 'safe'."""
    if _has_dangerous_rm(command):
        return "dangerous"
    return "dangerous" if _DANGEROUS_RE.search(command) else "safe"


def run_command(command: str, cwd: Path, timeout: int = DEFAULT_TIMEOUT) -> CommandResult:
    try:
        completed = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        return CommandResult(
            command=command,
            returncode=-1,
            stdout=(exc.stdout or ""),
            stderr=(exc.stderr or "") + f"\n[timed out after {timeout}s]",
            timed_out=True,
        )
    return CommandResult(
        command=command,
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )
