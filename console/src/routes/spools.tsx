import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { DEFAULT_SETTINGS, SPOOLS, loadSettings } from "@/lib/console";

export const Route = createFileRoute("/spools")({ component: SpoolsPage });

function SpoolsPage() {
  const [url, setUrl] = useState(DEFAULT_SETTINGS.spoolmanUrl);
  useEffect(() => setUrl(loadSettings().spoolmanUrl), []);

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Spools</h1>
        <p className="mt-1 max-w-2xl text-sm text-muted">
          Bundled Spoolman at <span className="font-mono">{url}</span>. Sample inventory, not your cupboard.
          The API has no login. Do not publish it past the LAN.
        </p>
      </div>
      <ul className="grid gap-3 sm:grid-cols-2">
        {SPOOLS.map((spool) => {
          const pct = Math.round((spool.left / spool.total) * 100);
          return (
            <li key={spool.name + spool.slot} className="rounded-card border border-line bg-surface p-4">
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-center gap-3">
                  <span
                    aria-hidden
                    className="size-8 rounded-full border border-line"
                    style={{ background: spool.swatch }}
                  />
                  <div>
                    <h2 className="font-semibold">{spool.name}</h2>
                    <p className="text-sm text-muted">
                      {spool.material} · {spool.color}
                    </p>
                  </div>
                </div>
                <span className="rounded-card bg-bg px-2 py-0.5 text-xs font-medium">{spool.slot}</span>
              </div>
              <div className="mt-4 h-2 overflow-hidden rounded-full bg-bg">
                <div className="h-full bg-accent" style={{ width: `${pct}%` }} />
              </div>
              <p className="mt-2 text-sm text-muted">
                {spool.left} g left of {spool.total} g
              </p>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
