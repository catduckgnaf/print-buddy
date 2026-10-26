"""The design §3 worked example, load-checked offline (#337 acceptance).

The config below is the MULTI-PRINTER-DESIGN.md section 3 example verbatim:
a Bambu A1 and a Flashforge AD5X in one instance, two Discord channels, one
shared Spoolman. Both entries must resolve, the channels must bind to the
right printers, Spoolman must be the same service for both, and each
printer's state must live in its own folder.
"""
from pathlib import Path

from print_buddy import settings
from print_buddy.bot import routing

DESIGN_EXAMPLE = '''\
[discord]
chat_id = "100000000000000001"        # the AD5X channel (fallback)
allowed_user_ids = "200000000000000002"

[services]
spoolman_url = "http://spoolman.home:7912"

[[printers]]
id = "garage-a1"
model = "bambulab.a1"
chat_id = "100000000000000003"
lan_host = "192.168.1.60"
lan_serial = "00M00A000000000"

[[printers]]
id = "workshop-ad5x"
model = "flashforge.ad5x"
moonraker_url = "http://192.168.1.61:7125"
'''


def test_design_section_3_example_loads_and_routes(tmp_path):
    local = tmp_path / "local.toml"
    local.write_text(DESIGN_EXAMPLE, encoding="utf-8")
    before = local.read_bytes()

    data = settings.load(local=local, environ={})

    entries = settings.printers(data)
    assert [entry["id"] for entry in entries] == ["garage-a1", "workshop-ad5x"]
    assert settings.default_printer_id(data) == "garage-a1"

    # Channels: the A1's own channel, and the AD5X on the global fallback.
    assert routing.channel_map(data, "discord") == {
        "100000000000000003": "garage-a1",
        "100000000000000001": "workshop-ad5x",
    }
    assert routing.printer_for_chat(data, "discord", "100000000000000003") == "garage-a1"
    assert routing.printer_for_chat(data, "discord", "100000000000000001") == "workshop-ad5x"
    assert routing.printer_for_chat(data, "discord", "100000000000000099") is None

    # One shared Spoolman, seen identically from both printers' views.
    for printer_id in ("garage-a1", "workshop-ad5x"):
        view = settings.view_for(printer_id, data)
        assert view["services"]["spoolman_url"] == "http://spoolman.home:7912"
    assert settings.view_for("garage-a1", data)["bambu"]["lan_host"] == "192.168.1.60"
    assert settings.view_for("workshop-ad5x", data)["services"]["moonraker_url"] == \
        "http://192.168.1.61:7125"

    # State is per printer, in distinct folders.
    a1_dir = settings.printer_state_dir("garage-a1", data)
    ad5x_dir = settings.printer_state_dir("workshop-ad5x", data)
    assert a1_dir != ad5x_dir
    assert Path(a1_dir).name == "garage-a1" and Path(ad5x_dir).name == "workshop-ad5x"

    # Loading never rewrites the operator's file.
    assert local.read_bytes() == before
