"""Model-site credentials (#462, #464): where each one lives and how to connect it.

Every model site that needs a credential is listed in ``LOGIN_SITES``:
MakerWorld, Thingiverse and Cults3D use a token or key the operator creates
on the site; Creality Cloud, Thangs and Nexprint use the login token the
operator's signed-in browser already holds (a cookie value); MyMiniFactory
uses its documented OAuth sign-in. None of these can be logged in to from a
script (login pages sit behind robot checks, and Print Handy never stores a
password or solves a captcha), so "connecting an account" always means the
operator saves the value in a token file on the Print Handy machine, or in
the site's environment variable. The value is never collected in chat: the
chat flow (see prepared_intake) walks the operator through the steps, links
the docs section, and then retries once they reply that it is saved.

``SiteLoginNeeded`` is what every provider raises when a request needs the
credential and it is missing, empty, expired or refused; the intake turns it
into the "Connect account" (or "Renew login") offer instead of a dead end.
``source_report`` is the ``/print-source`` answer: every site, what it
needs, and whether that is in place, without ever showing a credential.
"""
from __future__ import annotations

import base64
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

DOCS = "https://github.com/catduckgnaf/print-handy/blob/main/docs/PROJECT-REFERENCE.md"


@dataclass(frozen=True)
class LoginSite:
    site: str
    label: str
    folder: str
    sign_in_url: str
    where: str
    doc_section: str
    token_file: str = "token"
    env: str = ""
    # Site-specific walkthrough steps; empty means the browser-cookie steps.
    steps: tuple[str, ...] = ()
    intro: str = ""

    @property
    def env_name(self):
        """The environment variable that can hold the credential instead of the file."""
        return self.env or f"{self.folder.upper()}_TOKEN"

    @property
    def docs_url(self):
        anchor = "".join(c for c in self.doc_section.lower().replace(" ", "-")
                         if c.isalnum() or c == "-")
        return f"{DOCS}#{anchor}"


MMF_AUTHORIZE = ("https://auth.myminifactory.com/web/authorize?client_id={client}"
                 "&redirect_uri={redirect}&response_type=token&state=print-handy")

LOGIN_SITES = {
    "makerworld": LoginSite(
        "makerworld", "MakerWorld", "bambu", "https://makerworld.com",
        "Cookies for https://makerworld.com, the cookie named `token`",
        "MakerWorld account token", env="MAKERWORLD_TOKEN"),
    "thingiverse": LoginSite(
        "thingiverse", "Thingiverse", "thingiverse", "https://www.thingiverse.com",
        "the App Token on your Thingiverse app's page",
        "Thingiverse App Token", env="THINGIVERSE_TOKEN",
        intro="Thingiverse links use Thingiverse's official API with a free App Token from "
              "your own account.",
        steps=("Sign in at https://www.thingiverse.com, then open "
               "https://www.thingiverse.com/developers and choose **Create an App**, then **Web App**.",
               "Fill in the form: App Name `Print Handy`; any description; App URL and Callback "
               "URL `https://github.com/catduckgnaf/print-handy`. Agree and create it (it can stay "
               "private and unpublished).",
               "On the app's page, copy the **App Token** (32 letters and digits). Not the Client "
               "Secret.")),
    "cults3d": LoginSite(
        "cults3d", "Cults3D", "cults3d", "https://cults3d.com",
        "your Cults API key page", "Cults3D API key", env="CULTS3D_TOKEN",
        intro="Cults3D links use Cults' official API with an API key from your own account. "
              "(Cults' API shows a model's listing only, never its files.)",
        steps=("Sign in at https://cults3d.com and open https://cults3d.com/en/api/keys.",
               "Create a key and copy it.",
               "Write it as `nickname:key`: your Cults nickname exactly as on your profile, "
               "capitals included, a colon, then the key.")),
    "crealitycloud": LoginSite(
        "crealitycloud", "Creality Cloud", "crealitycloud", "https://www.crealitycloud.com",
        "Cookies for https://www.crealitycloud.com, TWO cookies: `model_user_id` (a number) and "
        "`model_token`. Save them together as `model_user_id:model_token`, for example "
        "`1234567890:4f2a…`",
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
    # MyMiniFactory's documented OAuth sign-in (#464): the operator registers
    # their own app once and signs in through MyMiniFactory's own page; the
    # access token it returns in the redirect URL is the saved login. Its
    # folder already holds the inventory API key as `token`, so the sign-in
    # lives beside it as `oauth_token`.
    "myminifactory": LoginSite(
        "myminifactory", "MyMiniFactory", "myminifactory", "https://www.myminifactory.com",
        "the address bar after signing in (the `access_token=` value, or paste the whole URL)",
        "MyMiniFactory sign-in", token_file="oauth_token", env="MYMINIFACTORY_OAUTH_TOKEN",
        intro="MyMiniFactory downloads go through its own sign-in (OAuth).",
        steps=("One time only: sign in at https://www.myminifactory.com, open Account Settings, "
               "then **Developers**, and register an app: Name `Print Handy`; Client key any unique "
               "slug, for example `print_handy`; Url and Redirect uri any page you control, for "
               "example `https://github.com/catduckgnaf/print-handy`. Save.",
               "Open this link in that browser, with your client key and redirect uri filled in "
               "(the redirect uri URL-encoded):\n"
               f"`{MMF_AUTHORIZE.format(client='<client key>', redirect='<redirect uri>')}`",
               "Approve. The browser lands on your redirect page; copy the **whole address** from "
               "the address bar (it holds `#access_token=...`). The sign-in lasts about a week; "
               "renewing it repeats only this step and the one before.")),
}


class SiteLoginNeeded(RuntimeError):
    """A request needs the operator's credential for ``site``.

    ``reason`` is ``missing``, ``empty``, ``expired`` or ``refused``. The
    message is the plain, complete remedy, so callers that do not offer the
    chat flow (design, the CLI) can show it unchanged.
    """

    def __init__(self, site, reason, message):
        super().__init__(message)
        self.site = site
        self.reason = reason


def token_path(site) -> Path:
    acc = LOGIN_SITES[site]
    return Path.home()/".config"/acc.folder/acc.token_file


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
    """The SiteLoginNeeded for a credential the site turned down."""
    acc = LOGIN_SITES[site]
    lead = f"{acc.label} refused the login token{detail}"
    return SiteLoginNeeded(site, "refused", (
        f"{lead}, which usually means the saved token ({token_path(site)} or the "
        f"{acc.env_name} environment variable) is invalid or expired. Sign in at "
        f"{acc.sign_in_url} again and save the new value in that file (see "
        f"docs/PROJECT-REFERENCE.md, {acc.doc_section}), then send the link again."))


def _normalize(raw):
    """The bare token from what an operator is likely to paste.

    Accepts the cookie value as-is, wrapped in quotes, with a leading
    ``Bearer ``, a MyMiniFactory sign-in address (``#access_token=...``), or
    (Nexprint) the whole ``ACCOUNT_INFO`` JSON object from local storage.
    """
    token = raw.strip()
    if "access_token=" in token and not token.startswith("{"):
        from urllib.parse import parse_qs, urlsplit
        part = urlsplit(token).fragment or urlsplit(token).query or token
        found = parse_qs(part).get("access_token")
        if found:
            token = found[0]
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


def stored(site, *, environ=None):
    """(value, where) for ``site``'s saved credential, or (None, None) when none is saved.

    The file wins when it exists (the chat connect flow writes it, so a
    freshly saved value always takes effect); otherwise the environment
    variable. ``value`` is normalized and may be empty (an empty file).
    """
    acc = LOGIN_SITES[site]
    path = token_path(site)
    try:
        return _normalize(path.read_text(encoding="utf-8")), str(path)
    except FileNotFoundError:
        env = os.environ if environ is None else environ
        value = _normalize(env.get(acc.env_name) or "")
        return (value, f"the {acc.env_name} environment variable") if value else (None, None)


def read_token(site, *, now=None, environ=None):
    """The login token for ``site``; SiteLoginNeeded when unusable.

    A JWT whose ``exp`` has passed is refused here, before any request, so
    the operator hears "expired" rather than a site refusal.
    """
    acc = LOGIN_SITES[site]
    path = token_path(site)
    token, where = stored(site, environ=environ)
    if token is None:
        raise SiteLoginNeeded(site, "missing", (
            f"{acc.label} downloads need a login token in {path} (or the "
            f"{acc.env_name} environment variable); sign in at "
            f"{acc.sign_in_url} in a browser, open the developer tools, copy the "
            f"value from {acc.where}, and store it as the only content of that "
            f"file; see docs/PROJECT-REFERENCE.md ({acc.doc_section})"))
    if not token:
        raise SiteLoginNeeded(site, "empty", f"{acc.label} token empty: {path} has no token in it")
    exp = _jwt_expiry(token)
    if exp is not None and exp <= (time.time() if now is None else now):
        raise SiteLoginNeeded(site, "expired", (
            f"The {acc.label} login token in {where} has expired. Sign in at "
            f"{acc.sign_in_url} again and save the new value in {path} "
            f"(see docs/PROJECT-REFERENCE.md, {acc.doc_section})."))
    return token


def connect_steps(site, *, renew=False):
    """The chat walkthrough for connecting ``site``. Never asks for the value itself."""
    acc = LOGIN_SITES[site]
    path = token_path(site)
    folder = path.parent
    verb = "Renew your" if renew else "Connect your"
    intro = acc.intro or (
        f"Print Handy can't sign in for you ({acc.label}'s login page has a robot check, and "
        "passwords are never stored), so it uses the login token your browser already has.")
    steps = list(acc.steps) or [
        f"Sign in at {acc.sign_in_url} in a browser.",
        "Open the developer tools (F12), then Application (Chrome/Edge) or Storage (Firefox).",
        f"Copy the value from {acc.where}."]
    lines = [f"**{verb} {acc.label} account**",
             f"{intro} **Don't paste it here** — chat is not a safe place for it."]
    lines += [f"{n}. {text}" for n, text in enumerate(steps, 1)]
    lines.append(f"{len(steps) + 1}. On the machine running Print Handy, save it as the only "
                 f"content of `{path}`:\n"
                 f"```\nmkdir -p {folder} && chmod 700 {folder}\n"
                 f"(umask 077 && cat > {path})   # paste, press Enter, then Ctrl-D\n```")
    lines.append("In Docker, write it to the host folder mounted at `/data/.config` "
                 f"(`dot-config/{acc.folder}/{acc.token_file}`, owned by 1000:1000), or put it in "
                 f"your `.env` as `{acc.env_name}=<value>` and restart (a saved file wins over the "
                 "variable).")
    lines.append(f"Full instructions: {acc.docs_url}")
    lines.append("Then press **Saved — try again** and I'll carry on from here.")
    return "\n".join(lines)


# /print-source: every site Print Handy knows, in the order people meet them.
# kind: "login" (needs a LOGIN_SITES credential to download), "open" (no
# credential), "listing" (listing only; credential named when one is used),
# "none" (not supported).
SOURCES = (
    ("makerworld", "MakerWorld", "login", ""),
    ("printables", "Printables", "open", "no login needed"),
    ("thingiverse", "Thingiverse", "login", ""),
    ("myminifactory", "MyMiniFactory", "login", ""),
    ("crealitycloud", "Creality Cloud", "login", ""),
    ("thangs", "Thangs", "login", ""),
    ("nexprint", "Nexprint", "login", ""),
    ("cults3d", "Cults3D", "listing", "listing only — Cults' API never shares a model's files"),
    ("makeronline", "MakerOnline", "listing",
     "listing only — its downloads need a browser security check Print Handy won't fake"),
    ("grabcad", "GrabCAD", "none", "not supported — its firewall blocks apps and its terms forbid them"),
)


def credential_state(site, *, now=None, environ=None):
    """'ready', 'missing', 'empty' or 'expired' for ``site``'s saved credential."""
    value, _ = stored(site, environ=environ)
    if value is None:
        return "missing"
    if not value:
        return "empty"
    exp = _jwt_expiry(value)
    if exp is not None and exp <= (time.time() if now is None else now):
        return "expired"
    return "ready"


def source_report(*, now=None, environ=None):
    """The /print-source answer: one line per site. Never shows a credential."""
    lines = ["**Model sources** — post a link from any of these:"]
    for site, label, kind, note in SOURCES:
        if kind == "open":
            lines.append(f"- ✅ **{label}**: ready ({note})")
            continue
        if kind == "none":
            lines.append(f"- ⛔ **{label}**: {note}")
            continue
        if site not in LOGIN_SITES:
            lines.append(f"- ℹ️ **{label}**: {note}")
            continue
        state = credential_state(site, now=now, environ=environ)
        acc = LOGIN_SITES[site]
        if kind == "listing":
            have = "key saved" if state == "ready" else "needs your API key"
            lines.append(f"- ℹ️ **{label}**: {note} ({have})")
        elif state == "ready":
            _, where = stored(site, environ=environ)
            source = "variable" if where and where.startswith("the ") else "token file"
            lines.append(f"- ✅ **{label}**: connected ({source})")
        elif state == "expired":
            lines.append(f"- ⚠️ **{label}**: login expired — post a {label} link and press "
                         f"**Renew {label} login**")
        else:
            lines.append(f"- ❌ **{label}**: not connected — post a {label} link and press "
                         f"**Connect {label} account**, or see {acc.docs_url}")
    return "\n".join(lines)
