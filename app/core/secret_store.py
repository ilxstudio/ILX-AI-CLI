from __future__ import annotations
import logging

import keyring
import keyring.errors

_log = logging.getLogger("ilx_cli.secret_store")

SERVICE = "ilx-cli"
ACCOUNT = "api_key"
ACCOUNT_LAST_USERNAME = "last_username"


def _password_account(username: str) -> str:
    return f"password:{username}"


def keychain_available() -> bool:
    try:
        backend = keyring.get_keyring()
    except Exception as exc:
        _log.debug("keychain_available: get_keyring() failed: %s", exc)
        return False
    # "Keyring" (or "fail.Keyring") is the generic no-op fallback — not a real backend
    name = backend.__class__.__name__
    return "Keyring" not in name


def _api_key_account(provider: str = "") -> str:
    """Return the keychain account name for a given provider's API key."""
    if provider:
        return f"api_key:{provider}"
    return ACCOUNT


def get_api_key(provider: str = "") -> str:
    """Return the stored API key for *provider* (or the legacy default key)."""
    account = _api_key_account(provider)
    try:
        value = keyring.get_password(SERVICE, account)
    except keyring.errors.NoKeyringError:
        return ""
    except Exception as exc:
        _log.debug("get_api_key(%s): %s", provider, exc)
        return ""
    return value or ""


def set_api_key(key: str, provider: str = "") -> bool:
    """Store *key* in the OS keychain for *provider* (or the legacy slot)."""
    account = _api_key_account(provider)
    if not key:
        delete_api_key(provider)
        return True
    try:
        keyring.set_password(SERVICE, account, key)
        return True
    except Exception as exc:
        _log.warning("set_api_key(%s) failed: %s", provider, exc)
    return False


def delete_api_key(provider: str = "") -> None:
    account = _api_key_account(provider)
    try:
        keyring.delete_password(SERVICE, account)
    except Exception as exc:
        _log.debug("delete_api_key(%s): %s", provider, exc)


def set_credentials(username: str, password: str) -> None:
    username = (username or "").strip()
    if not username:
        return
    if not password:
        delete_credentials(username)
        return
    try:
        keyring.set_password(SERVICE, _password_account(username), password)
        keyring.set_password(SERVICE, ACCOUNT_LAST_USERNAME, username)
    except Exception as exc:
        _log.debug("set_credentials: %s", exc)


def get_last_username() -> str:
    try:
        return keyring.get_password(SERVICE, ACCOUNT_LAST_USERNAME) or ""
    except Exception:
        return ""


def get_credentials(username: str = "") -> tuple[str, str]:
    user = (username or "").strip() or get_last_username()
    if not user:
        return ("", "")
    try:
        pw = keyring.get_password(SERVICE, _password_account(user)) or ""
    except Exception:
        return ("", "")
    return (user, pw)


def delete_credentials(username: str = "") -> None:
    user = (username or "").strip()
    targets: list[str] = []
    if user:
        targets.append(_password_account(user))
    else:
        last = get_last_username()
        if last:
            targets.append(_password_account(last))
        targets.append(ACCOUNT_LAST_USERNAME)
    for acct in targets:
        try:
            keyring.delete_password(SERVICE, acct)
        except Exception:
            pass
