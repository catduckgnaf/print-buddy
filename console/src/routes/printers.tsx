import { createFileRoute } from "@tanstack/react-router";
import { PRINTERS } from "@/lib/console";

export const Route = createFileRoute("/printers")({ component: PrintersPage });

function PrintersPage() {
  return (
    <div className="flex flex-col gap-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Printers</h1>
        <p className="mt-1 max-w-2xl text-sm text-muted">
          Read-only roster. Per-printer edits stay in the settings file or guided setup.
          A shared channel asks which printer before a job starts.
        </p>
      </div>
      <ul className="grid gap-3 sm:grid-cols-2">
        {PRINTERS.map((printer) => (
          <li key={printer.id} className="rounded-card border border-line bg-surface p-4">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h2 className="font-semibold">{printer.name}</h2>
                <p className="font-mono text-xs text-muted">{printer.model}</p>
              </div>
              <span
                className={
                  "rounded-card px-2 py-0.5 text-xs font-medium " +
                  (printer.state === "printing" ? "bg-accent text-accent-ink" : "bg-ok-bg text-ok")
                }
              >
                {printer.state}
              </span>
            </div>
            <dl className="mt-4 grid grid-cols-2 gap-2 text-sm">
              <div>
                <dt className="text-muted">Connection</dt>
                <dd>{printer.connection}</dd>
              </div>
              <div>
                <dt className="text-muted">Channel</dt>
                <dd>{printer.channel}</dd>
              </div>
              <div className="col-span-2">
                <dt className="text-muted">Endpoint</dt>
                <dd className="font-mono">{printer.endpoint}</dd>
              </div>
            </dl>
            {printer.default ? (
              <p className="mt-3 text-xs font-medium text-muted">Default printer</p>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  );
}
