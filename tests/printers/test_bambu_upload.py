"""Bambu Lab FTPS upload (#187 stage c): offline tests only — a fake FTPS client, never a socket.

The fake implements the small ftplib-shaped surface client.upload uses (storbinary / size /
quit). The real transport's firmware quirks (implicit TLS, data-connection session reuse) are
wiring in client._ImplicitFTPS and can only be exercised against a printer; what is pinned
here is everything Print Buddy controls: names, verification, and failure behaviour.
"""
import ssl

import pytest

from print_buddy import printers, settings
from print_buddy.printers.bambulab.client import (BambuLanClient, BambuLanError, _ImplicitFTPS,
                                                  lan_ssl_context)

SERIAL = "00M00A000000000"
CODE = "12345678"
PAYLOAD = b"PK\x03\x04 fake gcode.3mf package bytes"


class FakeFTP:
    def __init__(self, size_delta=0, fail_store=False, fail_size=False):
        self.stored = {}
        self.commands = []
        self.size_delta = size_delta
        self.fail_store = fail_store
        self.fail_size = fail_size
        self.quit_called = False

    def storbinary(self, cmd, fp):
        self.commands.append(cmd)
        if self.fail_store:
            raise OSError("connection reset by printer")
        self.stored[cmd.split(" ", 1)[1]] = fp.read()
        return "226 Transfer complete"

    def size(self, name):
        if self.fail_size:
            raise OSError("SIZE not answered")
        data = self.stored.get(name)
        return None if data is None else len(data) + self.size_delta

    def quit(self):
        self.quit_called = True


def make_client(fake, **kw):
    return BambuLanClient("192.168.1.50", SERIAL, CODE, ftp_factory=lambda host, code: fake,
                          timeout_s=5, **kw)


@pytest.fixture
def package(tmp_path):
    path = tmp_path / "benchy.gcode.3mf"
    path.write_bytes(PAYLOAD)
    return path


def test_upload_stores_at_the_root_and_verifies_the_remote_size(package):
    fake = FakeFTP()
    name = make_client(fake).upload(package)
    assert name == "benchy.gcode.3mf"
    assert fake.commands == ["STOR benchy.gcode.3mf"]
    assert fake.stored["benchy.gcode.3mf"] == PAYLOAD
    assert fake.quit_called


def test_upload_accepts_an_explicit_remote_name(package):
    fake = FakeFTP()
    assert make_client(fake).upload(package, "renamed.gcode.3mf") == "renamed.gcode.3mf"
    assert fake.stored["renamed.gcode.3mf"] == PAYLOAD


def test_upload_refuses_a_size_mismatch_and_says_do_not_start_it(package):
    fake = FakeFTP(size_delta=-3)  # the printer ends up with a truncated file
    with pytest.raises(BambuLanError, match="could not be verified.*do not start"):
        make_client(fake).upload(package)
    assert fake.quit_called


def test_upload_refuses_when_the_printer_cannot_report_a_size(package):
    fake = FakeFTP(fail_size=True)
    with pytest.raises(BambuLanError, match="may be incomplete"):
        make_client(fake).upload(package)


def test_upload_failure_is_plain_and_never_leaks_the_access_code(package):
    fake = FakeFTP(fail_store=True)
    with pytest.raises(BambuLanError) as err:
        make_client(fake).upload(package)
    assert "may be incomplete" in str(err.value) and CODE not in str(err.value)
    assert fake.quit_called


@pytest.mark.parametrize("bad", ["folder/benchy.gcode.3mf", "benchy.gcode", "my benchy.gcode.3mf", "", "benchy.3mf"])
def test_upload_refuses_bad_remote_names_before_connecting(package, bad):
    calls = []
    client = BambuLanClient("192.168.1.50", SERIAL, CODE,
                            ftp_factory=lambda host, code: calls.append(host) or FakeFTP(), timeout_s=5)
    with pytest.raises(BambuLanError, match="invalid Bambu Lab remote file name"):
        client.upload(package, bad)
    assert calls == []  # refused before any connection was opened


def test_upload_refuses_a_missing_local_file(tmp_path):
    with pytest.raises(BambuLanError, match="nothing was uploaded"):
        make_client(FakeFTP()).upload(tmp_path / "nope.gcode.3mf")


def test_implicit_ftps_uses_the_verified_bambu_context():
    context = lan_ssl_context()
    ftp = _ImplicitFTPS(context=context)
    assert ftp.context is context
    assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname is False


# --------------------------------------------------------------------- adapter

def lan_config(**environ):
    env = {"PRINT_BUDDY__PRINTER__MODEL": "bambulab.a1",
           "PRINT_BUDDY__BAMBU__LAN_HOST": "192.168.1.50", "PRINT_BUDDY__BAMBU__LAN_SERIAL": SERIAL,
           **environ}
    return settings.load(local=False, environ=env)


def test_adapter_upload_requires_the_package_format_and_a_configured_lan(monkeypatch, package, tmp_path):
    monkeypatch.setenv("BAMBU_LAN_PASSWORD", CODE)
    adapter = printers.get("bambulab.a1", lan_config())
    raw = tmp_path / "plate_1.gcode"
    raw.write_text("G1 X1\n")
    with pytest.raises(BambuLanError, match="only a packaged .gcode.3mf"):
        adapter.upload(raw)
    plain = printers.get("bambulab.a1", settings.load(local=False, environ={"PRINT_BUDDY__PRINTER__MODEL": "bambulab.a1"}))
    with pytest.raises(BambuLanError, match="not configured"):
        plain.upload(package)
