"""Offline tests for the Discord Activity core (issue #311, stage 3).

No network and no Discord: the OAuth transport is a fake that records
what it was handed, and the HTTP surface runs on an ephemeral loopback
port. The redaction tests prove the OAuth code and the access token
appear in no error, no result and no response.
"""
import http.client
import json
import threading
import time

import pytest

from print_buddy import live_activity as la

CODE = "oauth-code-SECRET-1"
TOKEN = "access-token-SECRET-2"
SECRET = b"session-signing-secret"
ALLOWLIST = ("42", "43")


class FakeTransport:
    """Records the code/token it saw; answers like Discord would."""

    def __init__(self, user=None, exchange_error=None, user_error=None):
        self.user = {"id": "42", "username": "operator"} if user is None else user
        self.exchange_error = exchange_error
        self.user_error = user_error
        self.codes = []
        self.tokens = []

    def exchange_code(self, code):
        self.codes.append(code)
        if self.exchange_error is not None:
            raise self.exchange_error
        return TOKEN

    def fetch_user(self, access_token):
        self.tokens.append(access_token)
        if self.user_error is not None:
            raise self.user_error
        return self.user


# --------------------------------------------------------------------- OAuth allowlist

def test_authenticate_allows_a_listed_user_and_hides_the_token():
    transport = FakeTransport()
    result = la.authenticate_code(CODE, transport=transport, allowlist=ALLOWLIST)
    assert result.user_id == "42" and result.username == "operator"
    assert transport.codes == [CODE] and transport.tokens == [TOKEN]
    assert TOKEN not in repr(result) and CODE not in repr(result)


def test_authenticate_denies_an_unlisted_user():
    transport = FakeTransport(user={"id": "999", "username": "stranger"})
    with pytest.raises(la.ActivityAuthError, match="allowlist"):
        la.authenticate_code(CODE, transport=transport, allowlist=ALLOWLIST)


def test_authenticate_denies_by_default_on_every_failure():
    cases = [
        FakeTransport(exchange_error=OSError("down")),
        FakeTransport(user_error=OSError("down")),
        FakeTransport(user={"username": "no-id"}),
    ]
    for transport in cases:
        with pytest.raises(la.ActivityAuthError):
            la.authenticate_code(CODE, transport=transport, allowlist=ALLOWLIST)
    with pytest.raises(la.ActivityAuthError):
        la.authenticate_code("", transport=FakeTransport(), allowlist=ALLOWLIST)
    with pytest.raises(la.ActivityAuthError):
        la.authenticate_code(CODE, transport=FakeTransport(), allowlist=())


def test_authenticate_errors_never_carry_the_code_or_token():
    for transport in (FakeTransport(exchange_error=RuntimeError(f"boom {CODE} {TOKEN}")),
                      FakeTransport(user_error=RuntimeError(f"boom {TOKEN}"))):
        with pytest.raises(la.ActivityAuthError) as caught:
            la.authenticate_code(CODE, transport=transport, allowlist=ALLOWLIST)
        assert CODE not in str(caught.value) and TOKEN not in str(caught.value)


def test_urllib_transport_posts_the_exchange_and_reads_the_profile():
    seen = {}

    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return json.dumps(self.payload).encode()

    def opener(request, timeout=None):
        seen[request.full_url] = request
        if request.full_url == la.TOKEN_URL:
            return FakeResponse({"access_token": TOKEN})
        return FakeResponse({"id": "42", "username": "operator"})

    transport = la.UrllibOAuthTransport("123", "client-secret", opener=opener)
    assert transport.exchange_code(CODE) == TOKEN
    body = seen[la.TOKEN_URL].data.decode()
    assert "grant_type=authorization_code" in body and f"code={CODE}" in body
    user = transport.fetch_user(TOKEN)
    assert user["id"] == "42"
    assert seen[la.USER_URL].headers["Authorization"] == f"Bearer {TOKEN}"


def test_client_secret_comes_from_the_named_environment_variable():
    assert la.client_secret({"DISCORD_CLIENT_SECRET": "s3cret"}) == "s3cret"
    assert la.client_secret({}) == ""
    assert la.session_secret({"LIVE_STREAM_SESSION_SECRET": "abc"}) == b"abc"


# --------------------------------------------------------------------- session markers

def test_session_token_round_trips_and_expires():
    marker = la.make_session_token("42", secret=SECRET, now=1000.0, ttl_s=60)
    assert la.verify_session_token(marker, secret=SECRET, now=1000.0) == "42"
    assert la.verify_session_token(marker, secret=SECRET, now=1059.0) == "42"
    assert la.verify_session_token(marker, secret=SECRET, now=1060.0) is None


def test_session_token_rejects_tampering_wrong_secret_and_garbage():
    marker = la.make_session_token("42", secret=SECRET, now=1000.0)
    user_id, expiry, signature = marker.split(".")
    assert la.verify_session_token(f"43.{expiry}.{signature}", secret=SECRET, now=1000.0) is None
    assert la.verify_session_token(marker, secret=b"other", now=1000.0) is None
    assert la.verify_session_token("garbage", secret=SECRET, now=1000.0) is None
    assert la.verify_session_token("", secret=SECRET, now=1000.0) is None
    assert la.verify_session_token(marker, secret=b"", now=1000.0) is None
    with pytest.raises(la.ActivityAuthError):
        la.make_session_token("42", secret=b"", now=1000.0)


# --------------------------------------------------------------------- the page

def test_page_is_self_contained_and_speaks_go2rtc_mse():
    page = la.ACTIVITY_PAGE
    assert "http://" not in page and "https://" not in page
    assert "/api/ws?src=" in page and '"mse"' in page
    assert 'id="status"' in page and "camera feed" in page.lower()
    assert la.DEFAULT_STREAM_NAME in page


# --------------------------------------------------------------------- the HTTP surface

@pytest.fixture()
def server():
    transport = FakeTransport()
    instance = la.make_server("127.0.0.1", 0, transport=transport,
                              allowlist=ALLOWLIST, secret=SECRET)
    thread = threading.Thread(target=instance.serve_forever, daemon=True)
    thread.start()
    yield instance, transport
    instance.shutdown()
    instance.server_close()


def _request(server, method, path, body=None, headers=None):
    connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
    connection.request(method, path, body=body, headers=headers or {})
    response = connection.getresponse()
    payload = response.read()
    result = (response.status, dict(response.getheaders()), payload)
    connection.close()
    return result


def test_health_is_open_and_reveals_nothing(server):
    instance, _ = server
    status, _, payload = _request(instance, "GET", "/health")
    assert status == 200 and json.loads(payload) == {"ok": True, "service": "print-buddy-live"}


def test_page_requires_a_session_and_the_exchange_sets_one(server):
    instance, _ = server
    status, _, _ = _request(instance, "GET", "/")
    assert status == 403
    status, headers, payload = _request(
        instance, "POST", "/api/token", body=json.dumps({"code": CODE}),
        headers={"Content-Type": "application/json"})
    assert status == 200 and json.loads(payload)["user_id"] == "42"
    cookie = headers["Set-Cookie"]
    assert cookie.startswith(f"{la.SESSION_COOKIE}=") and "HttpOnly" in cookie
    marker = cookie.split(";", 1)[0].split("=", 1)[1]
    assert la.verify_session_token(marker, secret=SECRET, now=time.time()) == "42"
    status, headers, payload = _request(
        instance, "GET", "/", headers={"Cookie": f"{la.SESSION_COOKIE}={marker}"})
    assert status == 200 and payload.decode() == la.ACTIVITY_PAGE
    assert "Content-Security-Policy" in headers


def test_exchange_refusals_are_403_and_never_echo_secrets(server):
    instance, _ = server
    status, _, payload = _request(
        instance, "POST", "/api/token", body=json.dumps({"code": ""}),
        headers={"Content-Type": "application/json"})
    assert status == 403
    assert CODE.encode() not in payload and TOKEN.encode() not in payload


def test_unknown_paths_and_methods(server):
    instance, _ = server
    assert _request(instance, "GET", "/nope")[0] == 404
    assert _request(instance, "POST", "/nope", body="{}")[0] == 404
    assert _request(instance, "PUT", "/")[0] == 405
