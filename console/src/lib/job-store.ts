import { useEffect, useState } from "react";
import { chatTurn } from "@/lib/chat-turn";
import { loadSettings } from "@/lib/console";
import { emptyJob, reply, type Job } from "@/lib/walkthrough";

export type Line = { role: "you" | "bot"; text: string };

type Stored = { job: Job; lines: Line[] };

const KEY = "print-handy-console-job";
const SYNC = "ph-job-sync";

const greeting: Line = {
  role: "bot",
  text: "Paste a link, drop a file, or name a model. Search uses the same list. Nothing starts until you say start.",
};

function load(): Stored {
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return { job: emptyJob(), lines: [greeting] };
    const parsed = JSON.parse(raw) as Stored;
    if (!parsed?.job || !Array.isArray(parsed.lines)) return { job: emptyJob(), lines: [greeting] };
    return parsed;
  } catch {
    return { job: emptyJob(), lines: [greeting] };
  }
}

function save(state: Stored) {
  window.localStorage.setItem(KEY, JSON.stringify(state));
  window.dispatchEvent(new Event(SYNC));
}

export function useSharedJob() {
  const [state, setState] = useState<Stored>({ job: emptyJob(), lines: [greeting] });
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [apiNote, setApiNote] = useState("");

  useEffect(() => {
    setState(load());
    setReady(true);
    function onStorage(event: StorageEvent) {
      if (event.key === KEY) setState(load());
    }
    function onSync() {
      setState(load());
    }
    window.addEventListener("storage", onStorage);
    window.addEventListener(SYNC, onSync);
    return () => {
      window.removeEventListener("storage", onStorage);
      window.removeEventListener(SYNC, onSync);
    };
  }, []);

  async function send(input: string) {
    const text = input.trim();
    if (!text || busy) return;
    const printerName = loadSettings().printerName;
    const current = load();
    setBusy(true);
    let result;
    try {
      result = await chatTurn({ data: { input: text, job: current.job, printerName } });
      setApiNote("API accepted that turn.");
    } catch {
      result = reply(current.job, text, printerName);
      setApiNote("Saved on this device. The API did not take that turn.");
    }
    const next: Stored = {
      job: result.job,
      lines: [...current.lines, { role: "you", text }, ...result.lines.map((line) => ({ role: "bot" as const, text: line }))],
    };
    save(next);
    setState(next);
    setBusy(false);
  }

  function reset() {
    void send("reset");
  }

  return { ...state, ready, busy, apiNote, send, reset };
}
