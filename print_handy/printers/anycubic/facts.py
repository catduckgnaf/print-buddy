"""Sourced facts for the Anycubic models: the Klipper-based Kobra 2 family only. Bed size
and height are OrcaSlicer's printable_area / printable_height for the model (the registry
convention), never the marketed build volume. The vendor writes bed_exclude_area three
ways across the family — a missing key on the Kobra 2, a ["0x0"] list on the Kobra 2 Neo
and an empty list on the rest — and all three mean no exclusion, so every model here
records an empty tuple. Identities pin the machine, process and checked PLA filament
profiles a generated template folder must hash to, read from the pinned OrcaSlicer
installs (2.4.2 vendor profiles 02.04.00.02; 2.5.0-alpha 02.04.00.09). One 2.5 change to
know: upstream renamed the base Kobra 2's checked filament from `Anycubic Generic PLA`
to the generic form (`Generic PLA @Anycubic`), so the recorded name is the 2.5.0-alpha
one — the same rename the Prusa and Creality packs record. The recorded 2.4.2 identity
was computed with the 2.4.2-era filament name, so a folder generated from 2.4.2 keeps
verifying against its own stored copies. Upstream ships only 0.4 mm nozzle machine
profiles for the whole family, so nozzle_sizes_mm is (0.4,) throughout. Three upstream
quirks are recorded so they are not "fixed" later: the Kobra 2's machine profile
declares gcode_flavor "marlin" and the Kobra 2 Neo's declares "marlin2" even though
both are Klipper-line machines (the route follows the hardware; the dialect stays
upstream's), the base Kobra 2's profile leaves nozzle_type undeclared ("undefine") —
its stock nozzle below is Anycubic's published fitting, recorded unverified — and the
family's start sequences are fully inline: no start macro anywhere, which is why the
guard treats both macro families as foreign. Temperature ceilings and materials are
Anycubic's published store specifications (nozzle 260 C throughout; bed 110 C on the
220 mm models, 90 C on the Plus and Max), recorded unverified like the other packs';
they feed only the post-slice foreign-file guard."""
from dataclasses import dataclass

ORCA = "OrcaSlicer bundled Anycubic profile (pinned install)"
ANYCUBIC = "Anycubic published specification (unverified)"


@dataclass(frozen=True)
class Fact:
    value: object
    source: str
    verified: bool


def _identities(machine, process, filament):
    """Checked upstream identities for one model, in a fixed order: OrcaSlicer 2.4.2
    (resources tree), OrcaSlicer 2.5.0-alpha (resources tree), then the same 2.5.0-alpha
    content from an installed OrcaSlicer's packed preset cache. The packed form hashes
    differently from the tree (payloads are re-serialised into the cache container and
    every profile carries an extra preset-identity field), so the packaging is part of
    the identity — the Prusa pack's precedent. Generating templates takes a 2.5.0-alpha
    installation for the base Kobra 2 (the rename note in the module docstring); a folder
    generated from 2.4.2 keeps verifying against its stored copies."""
    labels = (
        "OrcaSlicer 2.4.2 (Anycubic vendor profiles 02.04.00.02)",
        "OrcaSlicer 2.5.0-alpha (Anycubic vendor profiles 02.04.00.09)",
        "OrcaSlicer 2.5.0-alpha (Anycubic vendor profiles 02.04.00.09, packed cache)",
    )
    return tuple(
        {"label": label, "vendor_version": version, "sha256": hashes}
        for label, version, hashes in zip(labels, ('02.04.00.02', '02.04.00.09', '02.04.00.09'), (machine, process, filament)))


def _model(*, printer_model, names, hashes, bed, height, exclusion, marketed,
           nozzle_type, hotend, bed_temp, materials, enclosed):
    width, depth = bed
    return {
        "printer_model": Fact(printer_model, ORCA, True),
        "orca_profiles": Fact(names, ORCA, True),
        "orca_identity": Fact(_identities(*hashes), ORCA, True),
        "bed_mm": Fact((float(width), float(depth)), ORCA, True),
        "max_print_height_mm": Fact(float(height), ORCA, True),
        "bed_exclude_area": Fact(exclusion, ORCA, True),
        "motion_envelope_mm": Fact((0.0, 0.0, float(width), float(depth)), "DERIVED from the Orca printable area", True),
        "travel_z_headroom_mm": Fact(1.0, "DERIVED: printable height plus Z-hop headroom", True),
        "stock_nozzle": Fact((0.4, nozzle_type), ORCA, True),
        "nozzle_sizes_mm": Fact((0.4,), ORCA, True),
        "max_hotend_c": Fact(hotend, ANYCUBIC, False),
        "max_bed_c": Fact(bed_temp, ANYCUBIC, False),
        "ideal_materials": Fact(materials, ANYCUBIC, False),
        "tools": Fact(1, ANYCUBIC, False),
        "enclosed": Fact(enclosed, ANYCUBIC, False),
        "marketed_bed_mm": Fact((float(marketed[0]), float(marketed[1])), ANYCUBIC, False),
    }


MODELS = {
    "kobra2": _model(
        printer_model='Anycubic Kobra 2',
        names={"machine": 'Anycubic Kobra 2 0.4 nozzle', "process": '0.20mm Standard @Anycubic Kobra2', "filament": 'Generic PLA @Anycubic'},
        hashes=({'machine': '459bcd86e34d08c86876699925a1c77594ab41671885faf36afeb41af98dbe81', 'process': '6478cf72b42d7b525c7a4d6dce709efda7a064aca6703fe03e2ab5b8e44d3ae3', 'filament': '8496f805d62a1328afee136fe7d9643c74ac5ef9fd3e617ba675d3ce915182a0'}, {'machine': '8d0b03bbe03e638ea686313399211c1994b42abaa6fb46cf8e0d3522c23a99f8', 'process': '323f5d30a972a90744d030fc676cdddf1908090a09373c852910ccd0fac34ee1', 'filament': '4090862840d016eaf4e240aef99bdf7b777b81e2d41335958791f50047ec00f2'}, {'machine': '492a09d2f36eae9081cc9d82f5e04ce15c2258bd4eb4d21196b95e06d76cacdb', 'process': '0e153ef2691de6f8bf05861d46e9cb3f214f04c2ac50b0cae06f0e2e651a9aca', 'filament': '9249391b9698aa0fcda7fca2d14130e3c1bd05772fec886618d6d1f9d043bad5'}),
        bed=(220, 220), height=250, exclusion=(), marketed=(220, 220),
        nozzle_type='brass', hotend=260, bed_temp=110,
        materials=('PLA', 'ABS', 'PETG', 'TPU'), enclosed=False,
    ),
    "kobra2neo": _model(
        printer_model='Anycubic Kobra 2 Neo',
        names={"machine": 'Anycubic Kobra 2 Neo 0.4 nozzle', "process": '0.20mm Standard @Anycubic Kobra 2 Neo 0.4 nozzle', "filament": 'Anycubic PLA @Anycubic Kobra 2 Neo 0.4 nozzle'},
        hashes=({'machine': 'f582a538e9049ad98a7dbaa6564ebd12bb5a0dce7ac641193376b70070d61a55', 'process': 'e86029411dbd4b4f79573e886bc13485abdbed1adf6fd725580937c670ccc622', 'filament': '3e71630aa2fded92063cc6598f62d57abed282e5a60adcfabdbd6681ce98770d'}, {'machine': 'a8840f139bb2c745e15988c0b4349b5307d59253bf6f468e352a4b4ef2202714', 'process': 'ca44e877b1c121c06ab1f435951c035c9f858f8d2146bff1bf410910a9cb2c17', 'filament': 'fa89c136d9d42258a64ef65f025fa5bb3d4452703b118a35205ae8cbb2ca6571'}, {'machine': '82db5069957b26b34863740677793a1836ff4fe8033a3106e63b4370fa3d4b0e', 'process': '8f9895b655b58132283e4856144d36eb548dd041db54ef32642a3511c2b9a071', 'filament': '639aae1db1b526da2620395c5358c2a7c29296990640c1204ecddb4cc8e7900d'}),
        bed=(220, 220), height=250, exclusion=(), marketed=(220, 220),
        nozzle_type='brass', hotend=260, bed_temp=110,
        materials=('PLA', 'ABS', 'PETG', 'TPU'), enclosed=False,
    ),
    "kobra2pro": _model(
        printer_model='Anycubic Kobra 2 Pro',
        names={"machine": 'Anycubic Kobra 2 Pro 0.4 nozzle', "process": '0.16mm Optimal @Anycubic Kobra 2 Pro 0.4 nozzle', "filament": 'Anycubic PLA @Anycubic Kobra 2 Pro 0.4 nozzle'},
        hashes=({'machine': '80364c81d53b3ddb2290d8de0f7dabe1a9af44d17657818e2684402efcce74a3', 'process': '308a01c7ccabbad6fdf9f11de1b5287e4df67f5308fc5a881af16832e09a7451', 'filament': 'f0f6297a26891336e23c66c0340168ad3751d8d29f37bb4b447cd29935636f76'}, {'machine': '13f3f86a75190906841c0261b747afaf15e6fa27c71c75f6577695e4b286f3ac', 'process': '0364a0f38923485b1d98b10441f2ba31d6ced4b2a2587bd9b18986d4fc59e71a', 'filament': '30946b4d707cf93cd9d29beb68c628d64d87a3eba6828cbf14e00aa635cfe320'}, {'machine': '00f039fa6daf642086f4d571bacf3cf601d7bde8db900b18704d3abdb8df1c81', 'process': 'cd02d3d34da6833d8a86de74a5c03faaeea7ae2a4a8e721d03f43b9f626f7862', 'filament': '9a2589fb72ce6ebbc25827f883209d7933848732a5ab6ed39b699073bc1f26fd'}),
        bed=(220, 220), height=250, exclusion=(), marketed=(220, 220),
        nozzle_type='brass', hotend=260, bed_temp=110,
        materials=('PLA', 'ABS', 'PETG', 'TPU'), enclosed=False,
    ),
    "kobra2plus": _model(
        printer_model='Anycubic Kobra 2 Plus',
        names={"machine": 'Anycubic Kobra 2 Plus 0.4 nozzle', "process": '0.20mm Standard @Anycubic Kobra 2 Plus 0.4 nozzle', "filament": 'Anycubic PLA @Anycubic Kobra 2 Plus 0.4 nozzle'},
        hashes=({'machine': '5ba4f05cd172e331c47a53e58b1538926dc5b276dc2e855ca03d7fd443467cee', 'process': '9ae7e875d25e58bcea85eb198b61e53017f9414f843a6126d06e43ca7846e404', 'filament': '9e1f1f384aa3b068ec135232e418df86e2f74c682e393c1a464ee0190c71ab5b'}, {'machine': '2ba5fdc16d4a4711f930a3498675d1006637dd43b3ada25ab64f95e547016394', 'process': '41856f43233b0185fb512c6c2b92809f458a2c070820b6bcfa7ba8960468a3d7', 'filament': '6c202f4a4298acdab9ad68520c6582f28960a0e56c142f95ab640cc5a84e48dc'}, {'machine': 'be16874aecf09ba0b37c0cac28442814591eda6f0a4797bf9f485e1575baf41d', 'process': '850488a9eba11538e8baaf5f0a69d84cf9681cbe68b4cab75cb35434cf3f4bef', 'filament': '33d4f67159cd271cea75d2ac8037e46a0633021ca931e4c61960b842a1b319b4'}),
        bed=(320, 320), height=400, exclusion=(), marketed=(320, 320),
        nozzle_type='brass', hotend=260, bed_temp=90,
        materials=('PLA', 'ABS', 'PETG', 'TPU'), enclosed=False,
    ),
    "kobra2max": _model(
        printer_model='Anycubic Kobra 2 Max',
        names={"machine": 'Anycubic Kobra 2 Max 0.4 nozzle', "process": '0.20mm Standard @Anycubic Kobra 2 Max 0.4 nozzle', "filament": 'Anycubic PLA @Anycubic Kobra 2 Max 0.4 nozzle'},
        hashes=({'machine': 'd6f9a40c9c6a36de6b60eed0ba870ed156e0b6abbb4f8b5627988c0bc8a43446', 'process': 'f5ed3c15b6fed2785750b5b5295e3a63ebb0a6d6ffcb5af0ee2ffa1bc3f20353', 'filament': '214bed17fa67d0ef2574b409f3a369b8cfd2a79560f7adc24d6e61f4ec11fe76'}, {'machine': '8ea219ae508a533ce23e777401bfa0cf58f3d149fa1d7902bf05072148f2cdd9', 'process': '636581e1d86ac2499e242ac10d5afab40d31d72f4bb3448db69362bb60163c8f', 'filament': 'c446c7a5098cec0877da080b1ed27003a2c3dabd460f4e1e7778d978abdff825'}, {'machine': 'a1aa6b87cef19644f243ba5701bf874e1461aee27675061c26a707762be8b174', 'process': '0b6e4485af72cf7909516a51edbaf3963d740d523b5a43e339eab844930dc16d', 'filament': 'd973c805dc8f996990e40f6d790cac65b064fac4a867abe89b9049c53796142c'}),
        bed=(420, 420), height=500, exclusion=(), marketed=(420, 420),
        nozzle_type='brass', hotend=260, bed_temp=90,
        materials=('PLA', 'ABS', 'PETG', 'TPU'), enclosed=False,
    ),
}

# The base Kobra 2's Orca profile leaves nozzle_type undeclared ("undefine"), so its
# stock nozzle is not an Orca fact: brass is Anycubic's stock fitting for the model,
# recorded unverified like the manufacturer's other figures.
MODELS["kobra2"] = {**MODELS["kobra2"],
                    "stock_nozzle": Fact((0.4, "brass"), ANYCUBIC, False)}

KOBRA2 = MODELS["kobra2"]
KOBRA2NEO = MODELS["kobra2neo"]
KOBRA2PRO = MODELS["kobra2pro"]
KOBRA2PLUS = MODELS["kobra2plus"]
KOBRA2MAX = MODELS["kobra2max"]
