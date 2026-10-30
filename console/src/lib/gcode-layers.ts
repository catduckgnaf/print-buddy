export type Role = "perimeter" | "infill" | "support" | "other" | "travel";

export type Move = {
  role: Role;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
};

export type Layer = { z: number | null; moves: Move[] };

export type Parsed =
  | { ok: true; layers: Layer[]; roles: Role[] }
  | { ok: false; error: string };

const ROLES: Role[] = ["perimeter", "infill", "support", "other", "travel"];

export function classifyType(label: string): Role {
  const text = label.trim().toLowerCase();
  if (text.includes("support") || text.includes("raft")) return "support";
  if (text.includes("infill") || text.includes("gap fill")) return "infill";
  if (text.includes("wall") || text.includes("perimeter") || text.includes("skin")) return "perimeter";
  return "other";
}

export function clampLayer(count: number, requested: number): number {
  if (count <= 0) return 0;
  if (!Number.isFinite(requested)) return 0;
  const index = Math.trunc(requested);
  if (index < 0) return 0;
  if (index >= count) return count - 1;
  return index;
}

function words(parts: string[]): Record<string, number> {
  const found: Record<string, number> = {};
  for (const part of parts.slice(1)) {
    if (part.length < 2) continue;
    const letter = part[0].toUpperCase();
    if (letter < "A" || letter > "Z") continue;
    const value = Number(part.slice(1));
    if (Number.isFinite(value)) found[letter] = value;
  }
  return found;
}

export function parseGcode(text: string): Parsed {
  if (text.includes("\u0000")) return { ok: false, error: "this file is not G-code" };
  let role: Role = "other";
  let x: number | null = null;
  let y: number | null = null;
  let z: number | null = null;
  let e: number | null = null;
  let relXyz = false;
  let relE = false;
  let wantBreak = false;
  const layers: Layer[] = [];
  let sawMotion = false;

  const ensure = () => {
    if (wantBreak || layers.length === 0) {
      layers.push({ z, moves: [] });
      wantBreak = false;
    }
    return layers[layers.length - 1];
  };

  for (const rawLine of text.split(/\r?\n/)) {
    const raw = rawLine.trim();
    if (!raw) continue;
    if (raw.startsWith(";")) {
      const upper = raw.toUpperCase();
      if (upper.startsWith(";TYPE:")) role = classifyType(raw.split(":").slice(1).join(":"));
      else if (upper.startsWith(";LAYER_CHANGE") || upper.startsWith(";LAYER:")) {
        if (layers.length && layers[layers.length - 1].moves.length) wantBreak = true;
      }
      continue;
    }
    const code = raw.split(";", 1)[0].trim();
    if (!code) continue;
    const parts = code.split(/\s+/);
    const cmd = parts[0].toUpperCase();
    if (cmd === "M82") {
      relE = false;
      continue;
    }
    if (cmd === "M83") {
      relE = true;
      continue;
    }
    if (cmd === "G90") {
      relXyz = false;
      continue;
    }
    if (cmd === "G91") {
      relXyz = true;
      continue;
    }
    if (cmd === "G92") {
      const set = words(parts);
      if ("X" in set) x = set.X;
      if ("Y" in set) y = set.Y;
      if ("Z" in set) z = set.Z;
      if ("E" in set) e = set.E;
      continue;
    }
    if (cmd !== "G0" && cmd !== "G00" && cmd !== "G1" && cmd !== "G01") continue;
    sawMotion = true;
    const set = words(parts);
    let nx = x;
    let ny = y;
    let nz = z;
    let ne = e;
    if ("X" in set) nx = relXyz ? (x ?? 0) + set.X : set.X;
    if ("Y" in set) ny = relXyz ? (y ?? 0) + set.Y : set.Y;
    if ("Z" in set) nz = relXyz ? (z ?? 0) + set.Z : set.Z;
    let extruding = false;
    if ("E" in set) {
      if (relE) {
        extruding = set.E > 0;
        ne = (e ?? 0) + set.E;
      } else {
        extruding = e !== null && set.E > e;
        ne = set.E;
        if (e === null && set.E > 0) extruding = true;
      }
    }
    if (x !== null && y !== null && nx !== null && ny !== null && (nx !== x || ny !== y)) {
      const kind: Role = extruding ? role : "travel";
      const layer = ensure();
      if (layer.z === null) layer.z = nz;
      layer.moves.push({ role: kind, x1: x, y1: y, x2: nx, y2: ny });
    }
    x = nx;
    y = ny;
    z = nz;
    e = ne;
  }

  while (layers.length && layers[layers.length - 1].moves.length === 0) layers.pop();
  const extruded = layers.some((layer) => layer.moves.some((move) => move.role !== "travel"));
  if (!sawMotion || !extruded) {
    return { ok: false, error: "this G-code has no extrusion to draw" };
  }
  const present = new Set(layers.flatMap((layer) => layer.moves.map((move) => move.role)));
  return { ok: true, layers, roles: ROLES.filter((roleName) => present.has(roleName)) };
}

/** A small sliced plate so the sample install has a layer to open. */
export function samplePlate(): string {
  const lines = ["G90", "M83", "G0 X18 Y18 Z0.2"];
  for (let layer = 0; layer < 8; layer += 1) {
    const z = (0.2 * (layer + 1)).toFixed(1);
    const inset = layer >= 6 ? 3 : 0;
    const x0 = 18 + inset;
    const y0 = 18 + inset;
    const x1 = 78 - inset;
    const y1 = 62 - inset;
    lines.push(";LAYER_CHANGE");
    lines.push(";TYPE:Outer wall");
    lines.push(`G1 X${x0} Y${y0} Z${z}`);
    lines.push(`G1 X${x1} Y${y0} E0.04`);
    lines.push(`G1 X${x1} Y${y1} E0.04`);
    lines.push(`G1 X${x0} Y${y1} E0.04`);
    lines.push(`G1 X${x0} Y${y0} E0.04`);
    lines.push(";TYPE:Inner wall");
    const ix0 = x0 + 1.2;
    const iy0 = y0 + 1.2;
    const ix1 = x1 - 1.2;
    const iy1 = y1 - 1.2;
    lines.push(`G1 X${ix0} Y${iy0} E0.03`);
    lines.push(`G1 X${ix1} Y${iy0} E0.03`);
    lines.push(`G1 X${ix1} Y${iy1} E0.03`);
    lines.push(`G1 X${ix0} Y${iy1} E0.03`);
    lines.push(`G1 X${ix0} Y${iy0} E0.03`);
    lines.push(layer >= 6 ? ";TYPE:Internal solid infill" : ";TYPE:Sparse infill");
    for (let step = 0; step < 5; step += 1) {
      const y = iy0 + 2 + step * ((iy1 - iy0 - 4) / 4);
      lines.push(`G1 X${ix0 + 1} Y${y.toFixed(2)}`);
      lines.push(`G1 X${ix1 - 1} Y${y.toFixed(2)} E0.03`);
    }
    if (layer < 4) {
      lines.push(";TYPE:Support");
      lines.push("G1 X86 Y22");
      lines.push("G1 X96 Y22 E0.03");
      lines.push("G1 X96 Y34 E0.03");
      lines.push("G1 X86 Y34 E0.03");
      lines.push("G1 X86 Y22 E0.03");
    }
    lines.push("G0 X12 Y12");
  }
  return lines.join("\n");
}

export const BAD_PLATE = "this file is a note, not a sliced plate\n";
