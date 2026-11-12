# Copyright 2024
# Directory: yt-rag/app/core/admin_session.py

"""
Stateless signed session for the admin pages.

The session value is "v1.<issued_at>.<signature>": `issued_at` is a Unix time in
whole seconds and `signature` is the hex HMAC-SHA256 of "admin-session:v1:<issued_at>"
keyed with the admin token (SEED_TOKEN). Nothing is stored on the server, the value
never contains the token, and changing the token ends every session.
"""

import hashlib
import hmac
import re

COOKIE_NAME = "admin_session"
SESSION_SECONDS = 8 * 60 * 60

# Exactly "v1.<issued_at>.<64 lowercase hex digits>", with issued_at written as int()
# writes it (no leading zeros or "+"). Its length is bounded so int() never fails.
_VALUE = re.compile(r"v1\.(0|-?[1-9][0-9]{0,19})\.([0-9a-f]{64})")


def _signature(token: str, issued_at: int) -> str:
    """The hex HMAC-SHA256 of the session message, keyed with the token (UTF-8)."""
    message = f"admin-session:v1:{issued_at}".encode("ascii")
    return hmac.new(token.encode("utf-8"), message, hashlib.sha256).hexdigest()


def issue(token: str, now: float) -> str:
    """A session value issued at `now` for `token`."""
    issued_at = int(now)
    return f"v1.{issued_at}.{_signature(token, issued_at)}"


def is_valid(value: str | None, token: str, now: float) -> bool:
    """Whether `value` is a session issued for `token` less than SESSION_SECONDS ago."""
    if not isinstance(value, str) or not isinstance(token, str):
        return False
    match = _VALUE.fullmatch(value)
    if match is None:
        return False
    issued_at = int(match.group(1))
    try:
        expected = _signature(token, issued_at)
    except UnicodeEncodeError:  # a token that isn't valid text signs no session
        return False
    if not hmac.compare_digest(match.group(2), expected):
        return False
    return 0 <= now - issued_at < SESSION_SECONDS
