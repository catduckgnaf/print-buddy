"""Bambu Lab LAN transport: MQTT over TLS on port 8883, read-only in this stage.

Protocol facts are from docs/BAMBU-CONNECTIVITY.md (#187), verified against the maintained
integrations at pinned commits: subscribe to ``device/<serial>/report``, publish to
``device/<serial>/request``, user ``bblp`` with the printer's LAN access code as password.
A1/P1 printers report deltas, so a snapshot is only complete after a ``pushall`` request
answers with a full ``push_status`` (``msg == 0``); ``get_version`` identifies the machine.

This module never publishes a print command: the only requests it sends are
``get_version``, ``pushall`` and the ``pushing`` start that resumes the status stream.
Starting, pausing or controlling a print is a later, separately gated stage.

TLS: the peer certificate chain is verified against Bambu Lab's own CA bundle
(``bambu_ca.pem`` beside this file: the public BBL CA certificates, carried via the
MIT-licensed ha-bambulab repository at commit 0e027ff135a6d9265cb756d3e246747954c76722;
root subject ``CN = BBL CA2 RSA``, SHA-256 fingerprint
E9:8F:19:57:8B:3F:12:4A:CE:6B:8A:24:7F:FE:DA:52:DC:99:C8:9F:D4:E7:D2:0C:82:82:99:77:B7:F3:35:02).
Hostname checking is off because the certificate CN is the printer serial, not its IP
address — the same posture as pybambu. There is deliberately no CERT_NONE mode.
TLS is capped at 1.2: some Bambu firmware never answers a TLS 1.3 ClientHello.

The MQTT client is injectable (``mqtt_factory``) so tests run fully offline with a fake,
following the OctoPrint client's injectable-opener pattern. Error messages never include
the access code or a payload body.
"""
from __future__ import annotations

import copy
import json
import ssl
import time
from pathlib import Path

MQTT_PORT = 8883
MQTT_USER = "bblp"
CA_FILE = Path(__file__).with_name("bambu_ca.pem")

GET_VERSION = {"info": {"sequence_id": "0", "command": "get_version"}}
PUSHALL = {"pushing": {"sequence_id": "0", "command": "pushall"}}
START_PUSH = {"pushing": {"sequence_id": "0", "command": "start"}}

# print.fun bit: the firmware requires signed MQTT commands (Developer Mode is off),
# so every write is blocked even though reads keep working. See docs/BAMBU-CONNECTIVITY.md.
MQTT_SIGNATURE_REQUIRED = 0x20000000


class BambuLanError(RuntimeError):
    """A LAN telemetry failure, with no credential or payload detail attached."""


def signature_required(print_payload) -> bool:
    """True when the telemetry payload's `fun` bitfield says writes need signed commands."""
    fun = (print_payload or {}).get("fun")
    if not isinstance(fun, str):
        return False
    try:
        return bool(int(fun, 16) & MQTT_SIGNATURE_REQUIRED)
    except ValueError:
        return False


def merge_print(accumulated: dict, update: dict) -> dict:
    """Merge one (possibly delta) `print` payload into the accumulated snapshot state."""
    out = copy.deepcopy(accumulated)
    for key, value in (update or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = merge_print(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def lan_ssl_context() -> ssl.SSLContext:
    """The verified TLS context for a printer connection (see module docstring)."""
    context = ssl.create_default_context(cafile=str(CA_FILE))
    if hasattr(ssl, "VERIFY_X509_STRICT"):
        context.verify_flags &= ~ssl.VERIFY_X509_STRICT
    context.maximum_version = ssl.TLSVersion.TLSv1_2
    context.check_hostname = False  # the certificate CN is the serial, never the IP
    return context


def _paho_factory(host, serial, access_code):
    """Build the real Paho client. Imported lazily: paho-mqtt is only needed with LAN on."""
    try:
        import paho.mqtt.client as mqtt
    except ImportError as exc:
        raise BambuLanError("paho-mqtt is not installed; Bambu Lab LAN telemetry needs it "
                            "(pip install paho-mqtt, or use the full requirements.txt)") from exc
    try:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv311,
                             client_id=f"print-buddy-{serial.lower()}", clean_session=True)
    except (AttributeError, TypeError):  # paho < 2 has no CallbackAPIVersion
        client = mqtt.Client(protocol=mqtt.MQTTv311, client_id=f"print-buddy-{serial.lower()}",
                             clean_session=True)
    client.username_pw_set(MQTT_USER, password=access_code)
    client.tls_set_context(lan_ssl_context())
    client.tls_insecure_set(True)  # hostname only; the chain is still verified (module docstring)
    client.reconnect_delay_set(min_delay=1, max_delay=30)
    return client


class BambuLanClient:
    """One-shot LAN telemetry: connect, take a complete snapshot, disconnect."""

    def __init__(self, host, serial, access_code, *, mqtt_factory=None, timeout_s=15.0):
        if not host or "://" in host or "/" in host or ":" in host or any(c.isspace() for c in host):
            raise BambuLanError("Bambu Lab LAN host must be a plain IP address or hostname, without scheme or port")
        if not serial or not str(serial).strip():
            raise BambuLanError("Bambu Lab LAN serial number is required (printer Settings; upper case is applied)")
        if not access_code:
            raise BambuLanError("Bambu Lab LAN access code is not set; put it in the environment variable named "
                                "by [bambu] lan_access_code_env (default BAMBU_LAN_PASSWORD), never in config files")
        if isinstance(timeout_s, bool) or not isinstance(timeout_s, (int, float)) or not 0 < timeout_s <= 120:
            raise BambuLanError("Bambu Lab LAN timeout must be a number of seconds up to 120")
        self.host = host
        self.serial = str(serial).strip().upper()
        self._access_code = access_code
        self.timeout_s = float(timeout_s)
        self._mqtt_factory = mqtt_factory or _paho_factory

    @property
    def report_topic(self):
        return f"device/{self.serial}/report"

    @property
    def request_topic(self):
        return f"device/{self.serial}/request"

    def _publish(self, client, payload):
        result = client.publish(self.request_topic, json.dumps(payload))
        rc = getattr(result, "rc", 0)
        if rc != 0:
            raise BambuLanError(f"Bambu Lab LAN request was not accepted by the MQTT client (rc={rc}); nothing was sent")

    def snapshot(self):
        """Return {"print": {...}, "info": {...} | None, "online": True} from a complete pushall.

        Raises BambuLanError when the printer cannot be reached, rejects the access code,
        or does not answer with a complete snapshot before the timeout. Error text carries
        no access code and no payload content.
        """
        client = self._mqtt_factory(self.host, self.serial, self._access_code)
        state = {"print": {}, "info": None, "complete": False, "denied": False, "failed": None}

        def on_connect(mqtt_client, _userdata, _flags, reason_code, *_rest):
            rc = getattr(reason_code, "value", reason_code)
            if rc == 5:
                state["denied"] = True
                return
            if rc != 0:
                state["failed"] = f"MQTT connection refused (rc={rc})"
                return
            mqtt_client.subscribe(self.report_topic)
            self._publish(mqtt_client, GET_VERSION)
            self._publish(mqtt_client, PUSHALL)

        def on_message(_client, _userdata, message):
            try:
                payload = json.loads(message.payload)
            except (ValueError, TypeError, AttributeError):
                return
            if not isinstance(payload, dict):
                return
            if isinstance(payload.get("print"), dict):
                update = payload["print"]
                if update.get("command") == "push_status" and update.get("msg") == 0:
                    state["complete"] = True
                state["print"] = merge_print(state["print"], update)
            if isinstance(payload.get("info"), dict) and payload["info"].get("command") == "get_version":
                state["info"] = payload["info"]

        client.on_connect = on_connect
        client.on_message = on_message
        try:
            try:
                client.connect(self.host, MQTT_PORT, keepalive=30)
            except Exception as exc:
                raise BambuLanError(f"Bambu Lab printer at {self.host} could not be reached "
                                    f"({type(exc).__name__}); check the printer is on, in LAN Mode, and on this network") from exc
            deadline = time.monotonic() + self.timeout_s
            while time.monotonic() < deadline:
                if state["denied"]:
                    raise BambuLanError("the printer rejected the LAN access code (MQTT access denied); "
                                        "re-read the current code on the printer (Settings > WLAN) — it changes "
                                        "after a factory reset — and update the secret, not the config")
                if state["failed"]:
                    raise BambuLanError(f"Bambu Lab LAN connection failed: {state['failed']}")
                if state["complete"] and state["info"] is not None:
                    break
                client.loop(timeout=0.5)
            if state["denied"]:
                raise BambuLanError("the printer rejected the LAN access code (MQTT access denied)")
            if not state["complete"]:
                raise BambuLanError(f"no complete status snapshot from the Bambu Lab printer at {self.host} within "
                                    f"{self.timeout_s:g}s; it may be busy, asleep, or another client (Bambu Studio / "
                                    "Handy) may hold its single MQTT session")
            return {"print": state["print"], "info": state["info"], "online": True}
        finally:
            try:
                client.disconnect()
            except Exception:
                pass
