"""Login-token model sites (#464): where each token lives and how to connect it.

Creality Cloud, Thangs, Nexprint and MakerOnline download through the web
app's own API with the operator's login token — a value the signed-in
browser keeps in a cookie or local storage. None of these sites can be
logged in to from a script (their login pages put a captcha in front, and
Print Handy never stores a password or solves a captcha), so "connecting an
account" means the operator copies that value from their own browser into a
token file. The token is never collected in chat: the chat flow (see
prepared_intake) walks the operator through these steps and then retries
the download once they reply that the file is saved.

``SiteLoginNeeded`` is what every provider raises when a download needs the
login and the token is missing, empty, expired or refused; the intake turns
it into the "Connect account" offer instead of a dead-end failure.
"""
from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LoginSite:
    site: str
    label: str
    folder: str
    sign_in_url: str
    where: str
    doc_section: str


LOGIN_SITES = {
    "crealitycloud": LoginSite(
        "crealitycloud", "Creality Cloud", "crealitycloud", "https://www.crealitycloud.com",
        "Cookies for https://www.crealitycloud.com, the cookie named `model_token`",
        "Creality Cloud login token"),
    "thangs": LoginSite(
        "thangs", "Thangs", "thangs", "https://thangs.com",
        "Cookies for https://thangs.com, the cookie named `accessToken`",
        "Thangs login token"),
    "nexprint": LoginSite(
        "nexprint", "Nexprint", "nexprint", "https://www.nexprint.com",
        "Cookies for https://www.nexprint.com, the cookie named `auth_token` "
        "(or Local Storage, `ACCOUNT_INFO`, its `access_token` value)",
        "Nexprint login token"),
    "makeronline": LoginSite(
        "makeronline", "MakerOnline", "makeronline", "https://makeronline.com",
        "Cookies for https://makeronline.com, the cookie named `mo_access_token`",
        "MakerOnline login token"),
}


class SiteLoginNeeded(RuntimeError):
    """A download needs the operator's login token for ``site``.

    ``reason`` is ``missing``, ``empty``, ``expired`` or ``refused``. The
    message is the plain, complete remedy, so callers that do not offer the
    chat flow (design, the CLI) can show it unchanged.
    """

    def __init__(self, site, reason, message):
        super().__init__(message)
        self.site = site
        self.reason = reason


def token_path(site) -> Path:
    return Path.home()/".config"/LOGIN_SITES[site].folder/"token"


def _jwt_expiry(token):
    """The ``exp`` claim of a JWT-shaped token, or None when it has none."""
    parts = token.split(".")
    if len(parts) != 3:
        return None
    try:
        padded = parts[1] + "=" * (-len(parts[1]) % 4)
        claims = json.loads(base64.urlsafe_b64decode(padded))
    except (ValueError, TypeError):
        return None
    exp = claims.get("exp") if isinstance(claims, dict) else None
    return exp if isinstance(exp, (int, float)) else None


def refused(site, detail=""):
    """The SiteLoginNeeded for a token the site turned down."""
    acc = LOGIN_SITES[site]
    lead = f"{acc.label} refused the login token{detail}"
    return SiteLoginNeeded(site, "refused", (
        f"{lead}, which usually means the token in {token_path(site)} is "
        f"invalid or expired. Sign in at {acc.sign_in_url} again and replace the "
        f"file (see docs/PROJECT-REFERENCE.md, {acc.doc_section}), then send the link again."))


def _normalize(raw):
    """The bare token from what an operator is likely to paste.

    Accepts the cookie value as-is, wrapped in quotes, with a leading
    ``Bearer ``, or (Nexprint) the whole ``ACCOUNT_INFO`` JSON object from
    local storage, whose ``access_token`` is the token.
    """
    token = raw.strip()
    if token.startswith("{"):
        try:
            info = json.loads(token)
        except ValueError:
            info = None
        if isinstance(info, dict):
            token = str(info.get("access_token") or info.get("accessToken") or "").strip()
    token = token.strip("\"'")
    if token[:7].casefold() == "bearer ":
        token = token[7:].strip()
    return token


def read_token(site, *, now=None):
    """The stripped login token for ``site``; SiteLoginNeeded when unusable.

    A JWT whose ``exp`` has passed is refused here, before any request, so
    the operator hears "expired" rather than a generic site refusal.
    """
    acc = LOGIN_SITES[site]
    path = token_path(site)
    try:
        token = _normalize(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SiteLoginNeeded(site, "missing", (
            f"{acc.label} downloads need your login token in {path}; sign in at "
            f"{acc.sign_in_url} in a browser, open the developer tools, copy the "
            f"value from {acc.where}, and store it as the only content of that "
            f"file; see docs/PROJECT-REFERENCE.md ({acc.doc_section})")) from None
    if not token:
        raise SiteLoginNeeded(site, "empty", f"{acc.label} token empty: {path} has no token in it")
    exp = _jwt_expiry(token)
    if exp is not None and exp <= (time.time() if now is None else now):
        raise SiteLoginNeeded(site, "expired", (
            f"The {acc.label} login token in {path} has expired. Sign in at "
            f"{acc.sign_in_url} again and replace the file with the new value "
            f"(see docs/PROJECT-REFERENCE.md, {acc.doc_section})."))
    return token


def connect_steps(site):
    """The chat walkthrough for connecting ``site``. Never asks for the token itself."""
    acc = LOGIN_SITES[site]
    path = token_path(site)
    folder = path.parent
    return (
        f"**Connect your {acc.label} account**\n"
        f"Print Handy can't sign in for you ({acc.label}'s login page has a robot check, and "
        "passwords are never stored), so it uses the login token your browser already has. "
        "**Don't paste the token here** — chat is not a safe place for it.\n"
        f"1. Sign in at {acc.sign_in_url} in a browser.\n"
        "2. Open the developer tools (F12), then Application (Chrome/Edge) or Storage (Firefox).\n"
        f"3. Copy the value from {acc.where}.\n"
        "4. On the machine running Print Handy, save it as the only content of "
        f"`{path}`:\n"
        f"```\nmkdir -p {folder} && chmod 700 {folder}\n"
        f"(umask 077 && cat > {path})   # paste, press Enter, then Ctrl-D\n```\n"
        "In Docker, write it to the host folder mounted at `/data/.config` "
        f"(`dot-config/{acc.folder}/token`, owned by 1000:1000), or run the commands above "
        "inside the container.\n"
        "Then press **Saved — try again** and I'll retry the download. Tokens expire; "
        "when that happens I'll ask again.")
