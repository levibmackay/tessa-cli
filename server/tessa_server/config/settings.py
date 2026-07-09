"""Server-side configuration, sourced entirely from environment variables.

No config file — this runs as a long-lived service, and env vars are the
standard way to configure that (systemd/Task Scheduler unit, docker, or
just a launch script) without a secrets-bearing file to accidentally
commit.

Token storage today is a flat env-var-sourced mapping (see `_load_tokens`).
That's deliberately the *only* thing that would need to change to support
real multi-user accounts later — nothing in `auth/bearer.py` or the API
routes needs to change, since they only ever call `settings.tokens.get(...)`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache


def _load_tokens() -> dict[str, str]:
    """token -> user_id.

    `TESSA_SERVER_TOKEN=<token>` for a quick single-user setup, or
    `TESSA_SERVER_TOKENS="token1:alice,token2:bob"` for more than one.
    Both may be set at once.
    """
    tokens: dict[str, str] = {}
    single = os.environ.get("TESSA_SERVER_TOKEN")
    if single:
        tokens[single] = "default"
    multi = os.environ.get("TESSA_SERVER_TOKENS", "")
    for pair in filter(None, (p.strip() for p in multi.split(","))):
        token, _, user_id = pair.partition(":")
        if token:
            tokens[token] = user_id or token
    return tokens


@dataclass
class ServerSettings:
    # Bind address: default localhost-only. Set to a Tailscale interface
    # IP explicitly to accept connections over the tailnet — never "0.0.0.0"
    # (that would also listen on the raw LAN / any public interface).
    host: str = field(default_factory=lambda: os.environ.get("TESSA_SERVER_HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: int(os.environ.get("TESSA_SERVER_PORT", "8000")))
    ollama_host: str = field(
        default_factory=lambda: os.environ.get("TESSA_SERVER_OLLAMA_HOST", "http://localhost:11434")
    )
    tokens: dict[str, str] = field(default_factory=_load_tokens)
    # Optional TLS — point these at a `tailscale cert`-issued key/cert pair
    # to serve HTTPS directly; unset runs plain HTTP (fine for local dev,
    # or if TLS is terminated by something in front of this process).
    ssl_keyfile: str | None = field(default_factory=lambda: os.environ.get("TESSA_SERVER_SSL_KEYFILE"))
    ssl_certfile: str | None = field(default_factory=lambda: os.environ.get("TESSA_SERVER_SSL_CERTFILE"))


@lru_cache
def get_settings() -> ServerSettings:
    return ServerSettings()
