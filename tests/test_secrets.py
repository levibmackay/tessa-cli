"""Tests for OS-keychain-backed secret storage."""

import keyring
import pytest

from lydia.config import secrets


@pytest.fixture(autouse=True)
def _use_fake_keyring(fake_keyring) -> None:
    pass


def test_roundtrip() -> None:
    assert secrets.get_secret("gmail_refresh_token") is None
    secrets.set_secret("gmail_refresh_token", "rt-123")
    assert secrets.get_secret("gmail_refresh_token") == "rt-123"


def test_delete_is_idempotent() -> None:
    secrets.delete_secret("canvas_token")  # never set — should not raise
    secrets.set_secret("canvas_token", "tok")
    secrets.delete_secret("canvas_token")
    assert secrets.get_secret("canvas_token") is None
    secrets.delete_secret("canvas_token")  # already gone — still should not raise


def test_backend_failure_raises_secrets_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*args: object, **kwargs: object) -> None:
        raise keyring.errors.KeyringError("no backend available")

    monkeypatch.setattr(keyring, "get_password", broken)
    with pytest.raises(secrets.SecretsError):
        secrets.get_secret("outlook_token_cache")
