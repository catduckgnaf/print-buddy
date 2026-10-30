import { createFileRoute, Link } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { DEFAULT_SETTINGS, DOCTOR, loadSettings, printerTitle, type DoctorStatus, type Settings } from "@/lib/console";

export const Route = createFileRoute("/")({ component: StatusPage });

function tone(status: DoctorStatus) {
  if (status === "ok") return "bg-ok-bg text-ok";
  if (status === "warn") return "bg-warn-bg text-warn";
  if (status === "fail") return "bg-bad-bg text-bad";
  return "bg-bg text-muted";
}

function StatusPage() {
  const [settings, setSettings] = useState<Settings>(DEFAULT_SETTINGS);
  useEffect(() => setSettings(loadSettings()), []);

  const attention = DOCTOR.some((row) => row.status === "warn" || row.status === "fail");
  const facts: [string, string][] = [
    ["Version", "2.2.0"],
    ["Host", "unraid"],
    ["Printer", `${settings.printerName} (${printerTitle(settings.model)})`],
    ["Connection", "Moonraker · ZMod 1.7.5-2 · screenless"],
    ["Delivery", settings.zmodFormat === "auto" ? "auto → .gcode.3mf" : settings.zmodFormat],
    ["Bot", `${settings.platform} / ${settings.mode} — connected`],
    ["Listener", "ok — posting to the print channel"],
    ["Spoolman", `bundled ${settings.spoolmanUrl} — ok`],
    ["Timelapse", settings.timelapse === "rendered" ? "The printer records it" : settings.timelapse === "container" ? "Print Handy records it" : "Off"],
    ["Camera watch", settings.watchEnabled ? `on · sensitivity ${settings.sensitivity}` : "off"],
  ];

  return (
    <div className="flex flex-col gap-6">
      <p className="rounded-card border border-line bg-surface px-4 py-3 text-sm text-muted">
        Sample install, so this page has something to show. It is not connected to your printer.
        Settings you change stay in this browser.
      </p>

      <section className="rounded-card border border-line bg-surface p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-xs font-medium uppercase tracking-wide text-muted">Overall</p>
            <h1 className="text-2xl font-semibold tracking-tight">
              {attention ? "Attention needed" : "Ok"}
            </h1>
          </div>
          <span
            className={
              "rounded-card px-3 py-1 text-sm font-medium " +
              (attention ? "bg-warn-bg text-warn" : "bg-ok-bg text-ok")
            }
          >
            {attention ? "1 warning" : "all clear"}
          </span>
        </div>
        <div className="mt-4">
          <div className="mb-1 flex justify-between text-sm">
            <span className="font-medium">Duplo swing — plate 1 of 1</span>
            <span className="font-mono text-muted">layer 86 / 140</span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-bg">
            <div className="h-full w-[61%] bg-accent" />
          </div>
          <p className="mt-2 text-sm text-muted">
            About 48 min left · silk red + black · not started from this page.{" "}
            <Link to="/layers" className="font-medium text-accent">
              View sliced layers
            </Link>
          </p>
        </div>
      </section>

      <section className="overflow-hidden rounded-card border border-line bg-surface">
        <table className="w-full text-left text-sm">
          <tbody>
            {facts.map(([label, value]) => (
              <tr key={label} className="border-b border-line last:border-0">
                <th className="w-36 px-4 py-3 font-medium text-muted">{label}</th>
                <td className="px-4 py-3">{value}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section>
        <h2 className="mb-3 text-lg font-semibold">Doctor checks</h2>
        <ul className="flex flex-col gap-2">
          {DOCTOR.map((row) => (
            <li
              key={row.label}
              className="flex flex-wrap items-baseline justify-between gap-2 rounded-card border border-line bg-surface px-4 py-3"
            >
              <span className="font-medium">{row.label}</span>
              <span className="flex items-center gap-3 text-sm">
                <span className="text-muted">{row.detail}</span>
                <span className={"rounded-card px-2 py-0.5 text-xs font-medium " + tone(row.status)}>
                  {row.status}
                </span>
              </span>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
