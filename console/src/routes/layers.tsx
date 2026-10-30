import { createFileRoute } from "@tanstack/react-router";
import { useMemo, useRef, useState } from "react";
import {
  BAD_PLATE,
  clampLayer,
  parseGcode,
  samplePlate,
  type Role,
} from "@/lib/gcode-layers";

export const Route = createFileRoute("/layers")({ component: LayersPage });

const PLATES = [
  { id: "swing", label: "Duplo swing — plate 1" },
  { id: "bad", label: "Unreadable file" },
] as const;

const ROLE_CLASS: Record<Role, string> = {
  perimeter: "text-accent",
  infill: "text-ok",
  support: "text-warn",
  other: "text-ink",
  travel: "text-muted",
};

const ROLE_LABEL: Record<Role, string> = {
  perimeter: "Perimeter",
  infill: "Infill",
  support: "Support",
  other: "Other",
  travel: "Travel",
};

function LayersPage() {
  const [plate, setPlate] = useState<(typeof PLATES)[number]["id"]>("swing");
  const [layer, setLayer] = useState(0);
  const parsed = useMemo(() => parseGcode(plate === "swing" ? samplePlate() : BAD_PLATE), [plate]);
  const count = parsed.ok ? parsed.layers.length : 0;
  const index = clampLayer(count, layer);

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Sliced layers</h1>
        <p className="mt-1 max-w-2xl text-sm text-muted">
          Read-only view of a plate Print Handy already sliced. Extrusion is colored by role.
          Travel is faint. Nothing on this page starts, pauses, or excludes a job, and chat
          confirmation is unchanged.
        </p>
      </div>

      <div className="flex flex-wrap items-end gap-3">
        <label className="flex min-w-56 flex-1 flex-col gap-1 text-sm">
          <span className="font-medium">Plate</span>
          <select
            className="rounded-card border border-line bg-bg px-3 py-2 text-ink"
            value={plate}
            onChange={(event) => {
              setPlate(event.target.value as (typeof PLATES)[number]["id"]);
              setLayer(0);
            }}
          >
            {PLATES.map((row) => (
              <option key={row.id} value={row.id}>
                {row.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      {parsed.ok ? (
        <LayerCanvas
          parsed={parsed}
          index={index}
          onIndex={setLayer}
        />
      ) : (
        <p className="rounded-card border border-line bg-bad-bg px-4 py-3 text-sm text-bad">
          {parsed.error}. No drawing is shown for a file that is not a sliced plate.
        </p>
      )}
    </div>
  );
}

function LayerCanvas({
  parsed,
  index,
  onIndex,
}: {
  parsed: Extract<ReturnType<typeof parseGcode>, { ok: true }>;
  index: number;
  onIndex: (index: number) => void;
}) {
  const moves = parsed.layers[index].moves;
  const bounds = useMemo(() => {
    const xs = moves.flatMap((move) => [move.x1, move.x2]);
    const ys = moves.flatMap((move) => [move.y1, move.y2]);
    const minX = Math.min(...xs);
    const maxX = Math.max(...xs);
    const minY = Math.min(...ys);
    const maxY = Math.max(...ys);
    const pad = 4;
    return {
      minX: minX - pad,
      minY: -(maxY + pad),
      width: Math.max(maxX - minX, 1) + pad * 2,
      height: Math.max(maxY - minY, 1) + pad * 2,
    };
  }, [moves]);
  const drag = useRef<{ x: number; y: number; ox: number; oy: number } | null>(null);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const svgRef = useRef<SVGSVGElement>(null);
  const z = parsed.layers[index].z;

  return (
    <section className="rounded-card border border-line bg-surface p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm">
          <span className="font-medium">
            Layer {index + 1} of {parsed.layers.length}
          </span>
          {typeof z === "number" ? <span className="text-muted"> · Z {z.toFixed(1)} mm</span> : null}
        </p>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            className="rounded-card border border-line px-3 py-2 text-sm font-medium disabled:opacity-40"
            disabled={index === 0}
            onClick={() => onIndex(index - 1)}
          >
            Previous layer
          </button>
          <button
            type="button"
            className="rounded-card border border-line px-3 py-2 text-sm font-medium disabled:opacity-40"
            disabled={index + 1 >= parsed.layers.length}
            onClick={() => onIndex(index + 1)}
          >
            Next layer
          </button>
        </div>
      </div>
      <label className="mt-3 flex items-center gap-3 text-sm">
        <span className="text-muted">Step</span>
        <input
          className="h-11 min-w-0 flex-1 accent-accent"
          type="range"
          min={0}
          max={parsed.layers.length - 1}
          value={index}
          onChange={(event) => onIndex(Number(event.target.value))}
        />
      </label>
      <ul className="mt-3 flex flex-wrap gap-3 text-sm">
        {parsed.roles.map((role) => (
          <li key={role} className={"font-medium " + ROLE_CLASS[role]}>
            {ROLE_LABEL[role]}
          </li>
        ))}
      </ul>
      <svg
        ref={svgRef}
        className="mt-3 h-96 w-full touch-none rounded-card bg-bg"
        viewBox={`${bounds.minX} ${bounds.minY} ${bounds.width} ${bounds.height}`}
        role="img"
        aria-label="Sliced layer toolpath"
        onPointerDown={(event) => {
          event.currentTarget.setPointerCapture(event.pointerId);
          drag.current = { x: event.clientX, y: event.clientY, ox: pan.x, oy: pan.y };
        }}
        onPointerMove={(event) => {
          if (!drag.current || !svgRef.current) return;
          const rect = svgRef.current.getBoundingClientRect();
          const sx = rect.width ? bounds.width / rect.width : 1;
          const sy = rect.height ? bounds.height / rect.height : 1;
          setPan({
            x: drag.current.ox + (event.clientX - drag.current.x) * sx,
            y: drag.current.oy + (event.clientY - drag.current.y) * sy,
          });
        }}
        onPointerUp={() => {
          drag.current = null;
        }}
        onPointerCancel={() => {
          drag.current = null;
        }}
      >
        <g transform={`translate(${pan.x} ${pan.y})`}>
          {moves.map((move, moveIndex) => (
            <line
              key={moveIndex}
              className={ROLE_CLASS[move.role]}
              stroke="currentColor"
              strokeOpacity={move.role === "travel" ? 0.35 : 1}
              strokeWidth={move.role === "travel" ? 0.25 : 0.55}
              strokeLinecap="round"
              x1={move.x1}
              y1={-move.y1}
              x2={move.x2}
              y2={-move.y2}
            />
          ))}
        </g>
      </svg>
      <p className="mt-2 text-xs text-muted">Drag the drawing to pan. This sample is not connected to a printer.</p>
    </section>
  );
}
