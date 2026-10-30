import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { CameraStep, ChatStep, PrinterStep, ProviderList } from "@/components/install-fields";
import { DEFAULT_SETTINGS, loadSettings, saveSettings, type Settings } from "@/lib/console";
import { isZmod, modelLabel } from "@/lib/printers";

export const Route = createFileRoute("/setup")({ component: SetupPage });

const STEPS = [
  {
    label: "Printer",
    lead: "Pick the machine this install prints on. Brand, then the model. You can change this later.",
  },
  {
    label: "Chat",
    lead: "One chat per install. Standalone answers links, files, and buttons with no AI key. Add an OpenAI-compatible key only if you want free-text replies, design, or roasts. The name in chat is separate from the printer name.",
  },
  {
    label: "Camera",
    lead: "A camera lets Print Handy watch the print and keep a timelapse. The watch offers a pause. It does not stop the printer. No camera is a valid answer.",
  },
  {
    label: "Providers",
    lead: "Skip this if you want. MakerWorld and the other sites can be connected later. The first time someone drops a link the bot cannot download, it asks for that token. Printables needs no account.",
  },
  {
    label: "Review",
    lead: "Nothing is written to the printer from this page. Finish stores the choices in this browser.",
  },
] as const;

function SetupPage() {
  const navigate = useNavigate();
  const [step, setStep] = useState(0);
  const [draft, setDraft] = useState<Settings>(DEFAULT_SETTINGS);

  useEffect(() => {
    setDraft({ ...loadSettings(), setupDone: false });
  }, []);

  function patch(partial: Partial<Settings>) {
    setDraft((current) => ({ ...current, ...partial }));
  }

  function finish() {
    saveSettings({ ...draft, setupDone: true });
    navigate({ to: "/" });
  }

  const current = STEPS[step];

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-6">
      <div>
        <p className="text-xs font-medium uppercase tracking-wide text-muted">First boot</p>
        <h1 className="text-2xl font-semibold tracking-tight">{current.label}</h1>
        <p className="mt-2 text-sm text-muted">{current.lead}</p>
      </div>
      <ol className="flex flex-wrap gap-2 text-sm">
        {STEPS.map((item, index) => (
          <li key={item.label}>
            <button
              type="button"
              className={
                "rounded-card px-3 py-1 " +
                (index === step ? "bg-ink text-bg" : index < step ? "bg-ok-bg text-ok" : "bg-surface text-muted")
              }
              onClick={() => setStep(index)}
            >
              {index + 1}. {item.label}
            </button>
          </li>
        ))}
      </ol>

      {step === 0 ? <PrinterStep draft={draft} onChange={patch} /> : null}
      {step === 1 ? <ChatStep draft={draft} onChange={patch} /> : null}
      {step === 2 ? <CameraStep draft={draft} onChange={patch} /> : null}
      {step === 3 ? <ProviderList draft={draft} onChange={patch} /> : null}
      {step === 4 ? <Review draft={draft} /> : null}

      <div className="flex flex-wrap gap-2">
        {step > 0 ? (
          <button type="button" className="rounded-card border border-line bg-surface px-4 py-2 text-sm" onClick={() => setStep(step - 1)}>
            Back
          </button>
        ) : (
          <button
            type="button"
            className="rounded-card border border-line bg-surface px-4 py-2 text-sm"
            onClick={() => {
              saveSettings({ ...loadSettings(), setupDone: true });
              navigate({ to: "/" });
            }}
          >
            Skip
          </button>
        )}
        {step < STEPS.length - 1 ? (
          <button type="button" className="rounded-card bg-ink px-4 py-2 text-sm font-medium text-bg" onClick={() => setStep(step + 1)}>
            Continue
          </button>
        ) : (
          <button type="button" className="rounded-card bg-accent px-4 py-2 text-sm font-medium text-accent-ink" onClick={finish}>
            Finish setup
          </button>
        )}
      </div>
    </div>
  );
}

function cameraSummary(draft: Settings) {
  if (draft.hasCamera === "no") return "No";
  if (draft.camera === "go2rtc") return draft.streamUrl ? `RTSP stream · ${draft.streamUrl}` : "RTSP stream · URL not set";
  const source =
    draft.camera === "moonraker"
      ? "Moonraker webcam"
      : draft.camera === "bambu"
        ? "Bambu camera"
        : draft.camera === "none"
          ? "No snapshot URL"
          : "Follow the printer";
  return (draft.hasCamera === "yes" ? "Yes" : "Not sure") + " · " + source;
}

function Review({ draft }: { draft: Settings }) {
  const rows: [string, string][] = [
    ["Printer", `${draft.printerName} · ${modelLabel(draft.model)}`],
    ["Printer URL", draft.moonrakerUrl || "Not set"],
    ...(isZmod(draft.model)
      ? ([
          ["Panel", draft.panel === "helix" ? "HelixScreen" : draft.panel === "guppy" ? "GuppyScreen" : draft.panel === "stock" ? "Stock screen" : "No panel"],
          ["Delivery", draft.zmodFormat],
        ] as [string, string][])
      : []),
    ["Chat", `${draft.botName} on ${draft.platform}, ${draft.mode}`],
    ["OpenAI-compatible key", draft.llmKeySet ? "Set" : "Not set"],
    ["Camera", cameraSummary(draft)],
    ...(draft.platform === "discord"
      ? ([[
          "Discord live view",
          draft.liveView ? (draft.voiceChannel ? `Voice channel ${draft.voiceChannel}` : "Activity, channel not set") : "Off",
        ]] as [string, string][])
      : []),
    ["Timelapse", draft.timelapse === "rendered" ? "The printer records it" : draft.timelapse === "container" ? "Print Handy records it" : "Off"],
    ["Sites", String(Object.values(draft.providers).filter(Boolean).length) + " connected"],
  ];
  return (
    <section className="rounded-card border border-line bg-surface p-4 text-sm">
      <dl className="grid gap-2">
        {rows.map(([label, value]) => (
          <div key={label} className="flex justify-between gap-4">
            <dt className="text-muted">{label}</dt>
            <dd className="text-right">{value}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
