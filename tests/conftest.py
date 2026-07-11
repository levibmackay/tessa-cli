"""Shared test fixtures."""

from __future__ import annotations

import keyring
import pytest


class InMemoryKeyring:
    """Stands in for the real OS Keychain backend in tests."""

    def __init__(self) -> None:
        self._store: dict[tuple[str, str], str] = {}

    def set_password(self, service: str, key: str, value: str) -> None:
        self._store[(service, key)] = value

    def get_password(self, service: str, key: str) -> str | None:
        return self._store.get((service, key))

    def delete_password(self, service: str, key: str) -> None:
        try:
            del self._store[(service, key)]
        except KeyError:
            raise keyring.errors.PasswordDeleteError from None


@pytest.fixture
def fake_keyring(monkeypatch: pytest.MonkeyPatch) -> InMemoryKeyring:
    """Request this explicitly in any test that touches lydia.config.secrets."""
    backend = InMemoryKeyring()
    monkeypatch.setattr(keyring, "set_password", backend.set_password)
    monkeypatch.setattr(keyring, "get_password", backend.get_password)
    monkeypatch.setattr(keyring, "delete_password", backend.delete_password)
    return backend
