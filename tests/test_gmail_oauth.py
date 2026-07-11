"""Tests for the Gmail OAuth login/logout flow (no real browser/network)."""

from pathlib import Path

import pytest

from lydia.connectors.auth import gmail_oauth


@pytest.fixture(autouse=True)
def _use_fake_keyring(fake_keyring) -> None:
    pass


def test_login_errors_without_client_secret_file(tmp_path: Path) -> None:
    missing = tmp_path / "does_not_exist.json"
    with pytest.raises(gmail_oauth.GmailAuthError):
        gmail_oauth.login(client_secret_path=missing)


def test_is_logged_in_reflects_stored_credential() -> None:
    assert gmail_oauth.is_logged_in() is False
    from lydia.config import secrets
    secrets.set_secret(secrets.GMAIL_REFRESH_TOKEN, '{"refresh_token": "rt"}')
    assert gmail_oauth.is_logged_in() is True


def test_logout_clears_stored_credential() -> None:
    from lydia.config import secrets
    secrets.set_secret(secrets.GMAIL_REFRESH_TOKEN, '{"refresh_token": "rt"}')
    gmail_oauth.logout()
    assert gmail_oauth.is_logged_in() is False
