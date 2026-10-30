import { createFileRoute, Link } from "@tanstack/react-router";
import { useEffect, useMemo, useRef, useState } from "react";
import { CameraStep } from "@/components/install-fields";
import { PrinterPicker } from "@/components/printer-picker";
import { DEFAULT_SETTINGS, hashPassword, loadSettings, saveSettings, type Settings } from "@/lib/console";

export const Route = createFileRoute("/settings")({ component: SettingsPage });

type Field = {
  id: keyof Settings;
  label: string;
  help: string;
  kind: "text" | "number" | "toggle" | "picker";
  options?: string[];
  group: string;
};

const FIELDS: Field[] = [
  { id: "printerName", label: "Printer name", help: "Shown on the status page.", kind: "text", group: "Printer" },
  {
    id: "zmodFormat",
    label: "ZMod delivery",
    help: "auto sends .gcode.3mf once the printer reports ZMod 1.7.5 or newer.",
    kind: "picker",
    options: ["auto", "gcode", "gcode.3mf"],
    group: "Printer",
  },
  { id: "cliEnabled", label: "CLI", help: "Off by default. Turn on to show how to connect from a terminal.", kind: "toggle", group: "Chat" },
  { id: "botName", label: "Bot name", help: "The name it uses in chat. Not the printer name, and not the name in the Discord developer portal.", kind: "text", group: "Chat" },
  { id: "platform", label: "Chat platform", help: "One platform per install.", kind: "picker", options: ["discord", "matrix", "telegram"], group: "Chat" },
  { id: "mode", label: "Bot mode", help: "Standalone is the default.", kind: "picker", options: ["hermes", "standalone"], group: "Chat" },
  { id: "moonrakerUrl", label: "Printer URL", help: "The address Print Handy uses to talk to the machine. Klipper (Moonraker) or OctoPi can live on another computer, not on the printer.", kind: "text", group: "Services" },
  { id: "spoolmanUrl", label: "Spoolman URL", help: "Bundled Spoolman listens on the container loopback.", kind: "text", group: "Services" },
  { id: "logLevel", label: "Log level", help: "debug is for a session, not a permanent setting.", kind: "picker", options: ["debug", "info", "warning"], group: "Logging" },
  { id: "webuiPort", label: "Web UI port", help: "Applied after a restart. This preview does not rebind.", kind: "number", group: "Web UI" },
  { id: "webAuth", label: "Secure Auth", help: "Off by default. Turn on to require a username and password.", kind: "toggle", group: "Web UI" },
];

function SettingsPage() {
  const [saved, setSaved] = useState<Settings>(DEFAULT_SETTINGS);
  const [draft, setDraft] = useState<Settings>(DEFAULT_SETTINGS);
  const [password, setPassword] = useState("");
  const [notice, setNotice] = useState("");
  const [ready, setReady] = useState(false);
  const draftRef = useRef(draft);
  const passwordRef = useRef(password);
  const savedRef = useRef(saved);
  draftRef.current = draft;
  passwordRef.current = password;
  savedRef.current = saved;

  useEffect(() => {
    const loaded = loadSettings();
    setSaved(loaded);
    setDraft(loaded);
    setReady(true);
  }, []);

  const dirty = useMemo(() => {
    if (password.length > 0) return true;
    return (Object.keys(saved) as (keyof Settings)[]).some((key) => {
      if (key === "authPasswordHash") return false;
      return JSON.stringify(saved[key]) !== JSON.stringify(draft[key]);
    });
  }, [saved, draft, password]);

  useEffect(() => {
    if (!ready || !dirty) return;
    const handle = window.setTimeout(() => {
      const snapshot = draftRef.current;
      const snapshotPassword = passwordRef.current;
      void (async () => {
        const previous = savedRef.current;
        const username = snapshot.authUsername.trim();
        let next: Settings = { ...snapshot, authUsername: username || previous.authUsername };
        let note = "";
        if (snapshotPassword.length > 0 && snapshotPassword.length < 8) {
          next.authPasswordHash = previous.authPasswordHash;
          note = "Password needs at least 8 characters.";
        } else if (snapshotPassword.length >= 8) {
          next.authPasswordHash = await hashPassword(snapshotPassword);
        }
        if (draftRef.current !== snapshot || passwordRef.current !== snapshotPassword) return;
        const canLock = Boolean(next.authUsername) && Boolean(next.authPasswordHash);
        if (snapshot.webAuth && !canLock) {
          next.webAuth = previous.webAuth;
          note = note || (next.authUsername ? "Set a password before turning Secure Auth on." : "Set a username before turning Secure Auth on.");
        }
        if (JSON.stringify(next) === JSON.stringify(previous)) {
          if (note) setNotice(note);
          return;
        }
        saveSettings(next);
        setSaved(next);
        setDraft((current) => (current === snapshot ? { ...next, authUsername: snapshot.authUsername, webAuth: snapshot.webAuth } : current));
        if (snapshotPassword.length >= 8) setPassword("");
        setNotice(note || "Saved");
      })();
    }, 400);
    return () => window.clearTimeout(handle);
  }, [ready, dirty, draft, password]);

  function set<K extends keyof Settings>(id: K, value: Settings[K]) {
    setDraft((current) => ({ ...current, [id]: value }));
    setNotice("");
  }

  const groups = ["Printer", "Chat", "Services", "Camera", "Logging", "Web UI"];

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Settings</h1>
        <p className="mt-1 max-w-2xl text-sm text-muted">
          Changes save on their own in this browser.
        </p>
      </div>

      {!ready ? <p className="text-sm text-muted">Loading settings…</p> : null}

      {ready
        ? groups.map((group) => (
        <section key={group} className="rounded-card border border-line bg-surface p-4">
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted">{group}</h2>
          <div className="flex flex-col gap-4">
            {group === "Printer" ? (
              <PrinterPicker model={draft.model} onModel={(model) => set("model", model)} />
            ) : null}
            {group === "Camera" ? (
              <CameraStep
              framed={false}
              draft={draft}
              onChange={(partial) => {
                setDraft((current) => ({ ...current, ...partial }));
                setNotice("");
              }}
            />
            ) : null}
            {FIELDS.filter((field) => field.group === group).map((field) => (
              <div key={field.id} className="flex flex-col gap-3">
                <label className="flex flex-col gap-1 text-sm">
                  <span className="font-medium">{field.label}</span>
                  <Control field={field} value={draft[field.id]} onChange={(value) => set(field.id, value)} />
                  <span className="text-muted">{field.help}</span>
                </label>
                {group === "Chat" && field.id === "cliEnabled" && draft.cliEnabled ? <CliConnect /> : null}
                {group === "Web UI" && field.id === "webAuth" && draft.webAuth ? (
                  <SecureAuthFields
                    username={draft.authUsername}
                    password={password}
                    hasPassword={Boolean(draft.authPasswordHash)}
                    onUsername={(value) => set("authUsername", value)}
                    onPassword={(value) => {
                      setPassword(value);
                      setNotice("");
                    }}
                  />
                ) : null}
              </div>
            ))}
          </div>
        </section>
      ))
        : null}

      {notice ? <p className="text-sm text-muted">{notice}</p> : null}
    </div>
  );
}

function SecureAuthFields({
  username,
  password,
  hasPassword,
  onUsername,
  onPassword,
}: {
  username: string;
  password: string;
  hasPassword: boolean;
  onUsername: (value: string) => void;
  onPassword: (value: string) => void;
}) {
  const className = "w-full rounded-card border border-line bg-bg px-3 py-2 text-ink";
  return (
    <div className="flex flex-col gap-3">
      <label className="flex flex-col gap-1 text-sm">
        <span className="font-medium">Username</span>
        <input className={className} autoComplete="username" value={username} onChange={(event) => onUsername(event.target.value)} />
      </label>
      <label className="flex flex-col gap-1 text-sm">
        <span className="font-medium">Password</span>
        <input
          className={className}
          type="password"
          autoComplete="new-password"
          value={password}
          onChange={(event) => onPassword(event.target.value)}
        />
        <span className="text-muted">
          {hasPassword ? "Leave blank to keep the current password." : "At least 8 characters. Stored as a hash in this browser."}
        </span>
      </label>
    </div>
  );
}

function CliConnect() {
  return (
    <div className="rounded-card border border-line bg-bg p-3 text-sm">
      <p className="font-medium">How to connect</p>
      <p className="mt-1 text-muted">
        On the machine that runs Print Handy, from the install directory. The wizard asks the same questions as this console. Chat and that session share one job.
      </p>
      <pre className="mt-3 overflow-x-auto font-mono text-xs leading-6 text-ink">{`python3 -m print_handy.setup_wizard
python3 -m print_handy.bot check
python3 -m print_handy.doctor`}</pre>
      <p className="mt-3 text-muted">
        This preview does not open a shell. The sample terminal is at{" "}
        <Link to="/cli" className="underline">
          /cli
        </Link>
        .
      </p>
    </div>
  );
}

function Control({
  field,
  value,
  onChange,
}: {
  field: Field;
  value: Settings[keyof Settings];
  onChange: (value: Settings[keyof Settings]) => void;
}) {
  const className = "w-full rounded-card border border-line bg-bg px-3 py-2 text-ink";
  if (field.kind === "toggle") {
    return (
      <input
        type="checkbox"
        className="size-5 accent-accent"
        checked={Boolean(value)}
        onChange={(event) => onChange(event.target.checked)}
      />
    );
  }
  if (field.kind === "picker" && field.options) {
    return (
      <select className={className} value={String(value)} onChange={(event) => onChange(event.target.value as Settings[keyof Settings])}>
        {field.options.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
    );
  }
  if (field.kind === "number") {
    return (
      <input
        type="number"
        className={className}
        value={Number(value)}
        min={field.id === "sensitivity" ? 1 : 1}
        max={field.id === "sensitivity" ? 5 : 65535}
        onChange={(event) => onChange(Number(event.target.value))}
      />
    );
  }
  return (
    <input className={className} value={String(value)} onChange={(event) => onChange(event.target.value)} />
  );
}
