export type PrinterModel = { key: string; label: string };
export type PrinterBrand = { id: string; label: string; models: PrinterModel[] };

const SOVOL_KLIPPER: PrinterModel[] = [
  { key: "sovol.m1d", label: "Sovol M1D" },
  { key: "sovol.sv01", label: "Sovol SV01" },
  { key: "sovol.sv01_pro", label: "Sovol SV01 Pro" },
  { key: "sovol.sv02", label: "Sovol SV02" },
  { key: "sovol.sv03", label: "Sovol SV03" },
  { key: "sovol.sv04", label: "Sovol SV04" },
  { key: "sovol.sv05", label: "Sovol SV05" },
  { key: "sovol.sv06", label: "Sovol SV06" },
  { key: "sovol.sv06_ace", label: "Sovol SV06 ACE" },
  { key: "sovol.sv06_plus", label: "Sovol SV06 Plus" },
  { key: "sovol.sv06_plus_ace", label: "Sovol SV06 Plus ACE" },
  { key: "sovol.sv07", label: "Sovol SV07" },
  { key: "sovol.sv07_plus", label: "Sovol SV07 Plus" },
  { key: "sovol.sv08", label: "Sovol SV08" },
  { key: "sovol.sv08_max", label: "Sovol SV08 Max" },
  { key: "sovol.zero", label: "Sovol Zero" },
];

const SOVOL_MARLIN: PrinterModel[] = [
  { key: "sovol_marlin.sv01", label: "Sovol SV01" },
  { key: "sovol_marlin.sv01_pro", label: "Sovol SV01 Pro" },
  { key: "sovol_marlin.sv02", label: "Sovol SV02" },
  { key: "sovol_marlin.sv03", label: "Sovol SV03" },
  { key: "sovol_marlin.sv04", label: "Sovol SV04" },
  { key: "sovol_marlin.sv05", label: "Sovol SV05" },
  { key: "sovol_marlin.sv06", label: "Sovol SV06" },
  { key: "sovol_marlin.sv06_plus", label: "Sovol SV06 Plus" },
];

export const BRANDS: PrinterBrand[] = [
  {
    id: "anycubic",
    label: "Anycubic (Klipper)",
    models: [
      { key: "anycubic.kobra2", label: "Anycubic Kobra 2" },
      { key: "anycubic.kobra2max", label: "Anycubic Kobra 2 Max" },
      { key: "anycubic.kobra2neo", label: "Anycubic Kobra 2 Neo" },
      { key: "anycubic.kobra2plus", label: "Anycubic Kobra 2 Plus" },
      { key: "anycubic.kobra2pro", label: "Anycubic Kobra 2 Pro" },
    ],
  },
  {
    id: "anycubic_marlin",
    label: "Anycubic (Marlin/OctoPrint)",
    models: [
      { key: "octoprint.maxpro2", label: "Anycubic 4Max Pro 2" },
      { key: "octoprint.chiron", label: "Anycubic Chiron" },
      { key: "octoprint.i3megas", label: "Anycubic i3 Mega S" },
      { key: "octoprint.kobra", label: "Anycubic Kobra" },
      { key: "octoprint.kobramax", label: "Anycubic Kobra Max" },
      { key: "octoprint.kobraneo", label: "Anycubic Kobra Neo" },
      { key: "octoprint.kobraplus", label: "Anycubic Kobra Plus" },
      { key: "octoprint.vyper", label: "Anycubic Vyper" },
    ],
  },
  {
    id: "bambulab",
    label: "Bambu Lab",
    models: [
      { key: "bambulab.a1", label: "Bambu Lab A1" },
      { key: "bambulab.a1mini", label: "Bambu Lab A1 mini" },
      { key: "bambulab.a2l", label: "Bambu Lab A2L" },
      { key: "bambulab.h2c", label: "Bambu Lab H2C" },
      { key: "bambulab.h2d", label: "Bambu Lab H2D" },
      { key: "bambulab.h2dpro", label: "Bambu Lab H2D Pro" },
      { key: "bambulab.h2s", label: "Bambu Lab H2S" },
      { key: "bambulab.p1p", label: "Bambu Lab P1P" },
      { key: "bambulab.p1s", label: "Bambu Lab P1S" },
      { key: "bambulab.p2s", label: "Bambu Lab P2S" },
      { key: "bambulab.x1", label: "Bambu Lab X1" },
      { key: "bambulab.x1c", label: "Bambu Lab X1 Carbon" },
      { key: "bambulab.x1e", label: "Bambu Lab X1E" },
      { key: "bambulab.x2d", label: "Bambu Lab X2D" },
    ],
  },
  {
    id: "creality",
    label: "Creality (Klipper)",
    models: [
      { key: "creality.ender3v3", label: "Creality Ender-3 V3" },
      { key: "creality.ender3v3ke", label: "Creality Ender-3 V3 KE" },
      { key: "creality.ender3v3plus", label: "Creality Ender-3 V3 Plus" },
      { key: "creality.k1", label: "Creality K1" },
      { key: "creality.k1c", label: "Creality K1C" },
      { key: "creality.k1max", label: "Creality K1 Max" },
    ],
  },
  {
    id: "creality_marlin",
    label: "Creality (Marlin/OctoPrint)",
    models: [
      { key: "octoprint.ender3", label: "Creality Ender-3" },
      { key: "octoprint.ender3pro", label: "Creality Ender-3 Pro" },
      { key: "octoprint.ender3v2", label: "Creality Ender-3 V2" },
      { key: "octoprint.ender3v3se", label: "Creality Ender-3 V3 SE" },
    ],
  },
  {
    id: "elegoo",
    label: "Elegoo",
    models: [
      { key: "elegoo.neptune4", label: "Elegoo Neptune 4" },
      { key: "elegoo.neptune4max", label: "Elegoo Neptune 4 Max" },
      { key: "elegoo.neptune4plus", label: "Elegoo Neptune 4 Plus" },
      { key: "elegoo.neptune4pro", label: "Elegoo Neptune 4 Pro" },
    ],
  },
  {
    id: "elegoo_sdcp",
    label: "Elegoo (SDCP)",
    models: [{ key: "elegoo_sdcp.centauricarbon", label: "Elegoo Centauri Carbon" }],
  },
  {
    id: "flashforge_stock",
    label: "Flashforge (stock)",
    models: [{ key: "flashforge_stock.ad5x", label: "Flashforge Adventurer 5X (stock)" }],
  },
  {
    id: "flashforge",
    label: "Flashforge (ZMod)",
    models: [
      { key: "flashforge.ad5m", label: "Flashforge AD5M (ZMod)" },
      { key: "flashforge.ad5m_pro", label: "Flashforge AD5M Pro (ZMod)" },
      { key: "flashforge.ad5x", label: "Flashforge AD5X (ZMod)" },
      { key: "flashforge.creator5", label: "Flashforge Creator 5 (ZMod)" },
      { key: "flashforge.creator5_pro", label: "Flashforge Creator 5 Pro (ZMod)" },
    ],
  },
  {
    id: "other",
    label: "Other / generic",
    models: [
      { key: "klipper.generic", label: "Generic Klipper" },
      { key: "octoprint.marlin", label: "Generic OctoPrint" },
    ],
  },
  {
    id: "prusa",
    label: "Prusa",
    models: [
      { key: "prusa.coreone", label: "Prusa CORE One" },
      { key: "prusa.miniplus", label: "Prusa MINI+" },
      { key: "prusa.mk4s", label: "Prusa MK4S" },
      { key: "prusa.xl", label: "Prusa XL (5-tool)" },
    ],
  },
  {
    id: "qidi",
    label: "Qidi",
    models: [
      { key: "qidi.q1pro", label: "Qidi Q1 Pro" },
      { key: "qidi.xmax3", label: "Qidi X-Max 3" },
      { key: "qidi.xplus3", label: "Qidi X-Plus 3" },
      { key: "qidi.xplus4", label: "Qidi X-Plus 4" },
      { key: "qidi.xsmart3", label: "Qidi X-Smart 3" },
    ],
  },
  {
    id: "snapmaker",
    label: "Snapmaker",
    models: [{ key: "snapmaker.u1", label: "Snapmaker U1" }],
  },
  { id: "sovol", label: "Sovol (Klipper)", models: SOVOL_KLIPPER },
  { id: "sovol_marlin", label: "Sovol (Marlin/OctoPrint)", models: SOVOL_MARLIN },
];

const ALL = BRANDS.flatMap((brand) => brand.models.map((model) => ({ ...model, brand: brand.id })));

export function brandIdFor(modelKey: string): string {
  return ALL.find((model) => model.key === modelKey)?.brand ?? "other";
}

export function modelsFor(brandId: string): PrinterModel[] {
  return BRANDS.find((brand) => brand.id === brandId)?.models ?? BRANDS.find((brand) => brand.id === "other")!.models;
}

export function isZmod(model: string) {
  return model.startsWith("flashforge.") && !model.startsWith("flashforge_stock.");
}

export function modelLabel(modelKey: string): string {
  return ALL.find((model) => model.key === modelKey)?.label ?? modelKey;
}

export function usesMoonraker(model: string) {
  return (
    isZmod(model) ||
    model.startsWith("klipper.") ||
    model.startsWith("sovol.") ||
    model.startsWith("anycubic.") ||
    model.startsWith("creality.") ||
    model.startsWith("elegoo.") ||
    model.startsWith("qidi.")
  );
}
