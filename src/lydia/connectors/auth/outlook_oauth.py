"""Outlook / Microsoft 365 OAuth (device-code flow), via MSAL.

One-time manual setup Levi needs to do before `login()` can work — this
can't be automated:

1. Azure Portal (Entra ID) -> App registrations -> New registration.
   Supported account types: whichever matches the school account (if
   unsure, "Accounts in any organizational directory and personal
   Microsoft accounts"). No redirect URI is needed for the device-code flow.
2. Note the "Application (client) ID" shown after creation.
3. API permissions -> Add a permission -> Microsoft Graph -> Delegated
   permissions -> Mail.Read -> Add. Grant admin consent if the school
   tenant requires it (usually not needed for this scope).
4. Authentication -> Advanced settings -> enable "Allow public client
   flows" (required for the device-code flow, which uses no client secret).
"""

from __future__ import annotations

from collections.abc import Callable

import msal

from lydia.config import secrets
from lydia.connectors.email_outlook import GRAPH_BASE_URL  # noqa: F401 (re-exported for convenience)

SCOPES = ("Mail.Read",)
DEFAULT_AUTHORITY = "https://login.microsoftonline.com/common"


class OutlookAuthError(Exception):
    """Could not complete the Outlook OAuth flow, or the stored session is stale."""


def login(
    client_id: str,
    authority: str = DEFAULT_AUTHORITY,
    on_code: Callable[[str], None] = print,
    app_factory: Callable[..., msal.PublicClientApplication] = msal.PublicClientApplication,
) -> None:
    """Run the device-code flow: shows a URL + code, blocks until the user completes sign-in."""
    cache = msal.SerializableTokenCache()
    app = app_factory(client_id, authority=authority, token_cache=cache)
    flow = app.initiate_device_flow(scopes=list(SCOPES))
    if "user_code" not in flow:
        raise OutlookAuthError(f"Could not start device flow: {flow.get('error_description', flow)}")
    on_code(flow["message"])
    result = app.acquire_token_by_device_flow(flow)
    if "access_token" not in result:
        raise OutlookAuthError(f"Sign-in failed: {result.get('error_description', result)}")
    secrets.set_secret(secrets.OUTLOOK_TOKEN_CACHE, cache.serialize())
    secrets.set_secret(secrets.OUTLOOK_CLIENT_ID, client_id)
    secrets.set_secret(secrets.OUTLOOK_AUTHORITY, authority)


def logout() -> None:
    secrets.delete_secret(secrets.OUTLOOK_TOKEN_CACHE)
    secrets.delete_secret(secrets.OUTLOOK_CLIENT_ID)
    secrets.delete_secret(secrets.OUTLOOK_AUTHORITY)


def is_logged_in() -> bool:
    return secrets.get_secret(secrets.OUTLOOK_TOKEN_CACHE) is not None


def get_access_token(
    app_factory: Callable[..., msal.PublicClientApplication] = msal.PublicClientApplication,
) -> str:
    """Silently refresh (or reuse) a Graph access token from the stored MSAL cache."""
    client_id = secrets.get_secret(secrets.OUTLOOK_CLIENT_ID)
    if not client_id:
        raise OutlookAuthError("Not logged in to Outlook. Run `lydia auth login outlook` first.")
    authority = secrets.get_secret(secrets.OUTLOOK_AUTHORITY) or DEFAULT_AUTHORITY

    cache = msal.SerializableTokenCache()
    cached = secrets.get_secret(secrets.OUTLOOK_TOKEN_CACHE)
    if cached:
        cache.deserialize(cached)

    app = app_factory(client_id, authority=authority, token_cache=cache)
    accounts = app.get_accounts()
    if not accounts:
        raise OutlookAuthError("No cached Outlook account. Run `lydia auth login outlook` again.")

    result = app.acquire_token_silent(list(SCOPES), account=accounts[0])
    if not result or "access_token" not in result:
        raise OutlookAuthError("Outlook session expired. Run `lydia auth login outlook` again.")
    if cache.has_state_changed:
        secrets.set_secret(secrets.OUTLOOK_TOKEN_CACHE, cache.serialize())
    return result["access_token"]
