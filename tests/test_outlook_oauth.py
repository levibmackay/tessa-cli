"""Tests for the Outlook OAuth device-code login/logout flow (no real browser/network)."""

import pytest

from lydia.config import secrets
from lydia.connectors.auth import outlook_oauth


@pytest.fixture(autouse=True)
def _use_fake_keyring(fake_keyring) -> None:
    pass


class _FakeApp:
    """Stands in for msal.PublicClientApplication."""

    def __init__(self, client_id: str, authority: str, token_cache, device_flow=None,
                 silent_result=None, accounts=None) -> None:
        self.client_id = client_id
        self.authority = authority
        self.token_cache = token_cache
        self._device_flow = device_flow or {"user_code": "ABC123", "message": "Go to microsoft.com/devicelogin"}
        self._silent_result = silent_result
        self._accounts = accounts if accounts is not None else [{"username": "me@school.edu"}]

    def initiate_device_flow(self, scopes):
        return self._device_flow

    def acquire_token_by_device_flow(self, flow):
        return {"access_token": "at-123"}

    def get_accounts(self):
        return self._accounts

    def acquire_token_silent(self, scopes, account):
        return self._silent_result


def test_login_success_stores_cache_and_client_id() -> None:
    messages = []
    outlook_oauth.login(
        "client-abc", on_code=messages.append,
        app_factory=lambda client_id, authority, token_cache: _FakeApp(client_id, authority, token_cache),
    )
    assert messages == ["Go to microsoft.com/devicelogin"]
    assert secrets.get_secret(secrets.OUTLOOK_CLIENT_ID) == "client-abc"
    assert outlook_oauth.is_logged_in() is True


def test_login_fails_if_device_flow_has_no_user_code() -> None:
    with pytest.raises(outlook_oauth.OutlookAuthError):
        outlook_oauth.login(
            "client-abc",
            app_factory=lambda client_id, authority, token_cache: _FakeApp(
                client_id, authority, token_cache, device_flow={"error_description": "boom"},
            ),
        )


def test_get_access_token_requires_prior_login() -> None:
    with pytest.raises(outlook_oauth.OutlookAuthError):
        outlook_oauth.get_access_token()


def test_get_access_token_uses_silent_refresh_after_login() -> None:
    outlook_oauth.login(
        "client-abc",
        app_factory=lambda client_id, authority, token_cache: _FakeApp(client_id, authority, token_cache),
    )
    token = outlook_oauth.get_access_token(
        app_factory=lambda client_id, authority, token_cache: _FakeApp(
            client_id, authority, token_cache, silent_result={"access_token": "at-refreshed"},
        ),
    )
    assert token == "at-refreshed"


def test_logout_clears_everything() -> None:
    outlook_oauth.login(
        "client-abc",
        app_factory=lambda client_id, authority, token_cache: _FakeApp(client_id, authority, token_cache),
    )
    outlook_oauth.logout()
    assert outlook_oauth.is_logged_in() is False
    with pytest.raises(outlook_oauth.OutlookAuthError):
        outlook_oauth.get_access_token()
