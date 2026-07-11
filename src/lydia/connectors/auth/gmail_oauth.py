"""Gmail OAuth (installed-app flow).

One-time manual setup Levi needs to do before `login()` can work — this
can't be automated:

1. Google Cloud Console -> create/select a project -> enable the Gmail API.
2. APIs & Services -> OAuth consent screen -> configure it (External,
   Testing mode is fine for a personal account).
3. APIs & Services -> Credentials -> Create Credentials -> OAuth client ID
   -> Application type "Desktop app".
4. Download the resulting JSON and save it to DEFAULT_CLIENT_SECRET_PATH
   (or pass a different path to `login()`).
"""

from __future__ import annotations

from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

from lydia.config import secrets
from lydia.config.settings import GLOBAL_DIR
from lydia.connectors.email_gmail import SCOPES

DEFAULT_CLIENT_SECRET_PATH = GLOBAL_DIR / "gmail_client_secret.json"


class GmailAuthError(Exception):
    """Could not complete the Gmail OAuth flow."""


def login(client_secret_path: Path = DEFAULT_CLIENT_SECRET_PATH) -> None:
    """Run the installed-app OAuth flow (opens a browser tab) and store the credential."""
    if not client_secret_path.is_file():
        raise GmailAuthError(
            f"No Google OAuth client file at {client_secret_path}. Download one from Google "
            "Cloud Console (APIs & Services > Credentials > Create Desktop app OAuth client) "
            "and save it there first — see this module's docstring for the full setup."
        )
    flow = InstalledAppFlow.from_client_secrets_file(str(client_secret_path), scopes=list(SCOPES))
    credentials = flow.run_local_server(port=0)
    secrets.set_secret(secrets.GMAIL_REFRESH_TOKEN, credentials.to_json())


def logout() -> None:
    secrets.delete_secret(secrets.GMAIL_REFRESH_TOKEN)


def is_logged_in() -> bool:
    return secrets.get_secret(secrets.GMAIL_REFRESH_TOKEN) is not None
