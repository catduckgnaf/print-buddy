import { createFileRoute, Link } from "@tanstack/react-router";
import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { useSharedJob } from "@/lib/job-store";
import { loadSettings } from "@/lib/console";
import { MATERIALS, STAGE_LABEL } from "@/lib/walkthrough";

export const Route = createFileRoute("/cli")({ component: CliPage });

function hintsFor(stage: string): string[] {
  if (stage === "need-material") return [...MATERIALS];
  if (stage === "need-confirm") return ["start", "status", "reset"];
  if (stage === "queued") return ["status", "reset"];
  return ["help", "status"];
}

function CliPage() {
  const job = useSharedJob();
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [text, setText] = useState("");
  const history = useRef<string[]>([]);
  const cursor = useRef(-1);
  const draft = useRef("");
  const end = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setEnabled(loadSettings().cliEnabled);
  }, []);

  useEffect(() => {
    end.current?.scrollIntoView({ block: "end" });
  }, [job.lines]);

  function submit(value: string) {
    const next = value.trim();
    if (!next || job.busy) return;
    history.current.push(next);
    cursor.current = -1;
    draft.current = "";
    setText("");
    void job.send(next);
    inputRef.current?.focus();
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key !== "ArrowUp" && event.key !== "ArrowDown") return;
    event.preventDefault();
    const items = history.current;
    if (items.length === 0) return;
    if (cursor.current === -1) draft.current = text;
    if (event.key === "ArrowUp") {
      const next = cursor.current < 0 ? items.length - 1 : Math.max(0, cursor.current - 1);
      cursor.current = next;
      setText(items[next] ?? "");
      return;
    }
    if (cursor.current < 0) return;
    if (cursor.current >= items.length - 1) {
      cursor.current = -1;
      setText(draft.current);
      return;
    }
    cursor.current += 1;
    setText(items[cursor.current] ?? "");
  }

  const label = STAGE_LABEL[job.job.stage];

  if (enabled === null) return <div className="min-h-[40vh]" />;
  if (!enabled) {
    return (
      <div className="mx-auto flex max-w-2xl flex-col gap-3">
        <h1 className="text-2xl font-semibold tracking-tight">CLI</h1>
        <p className="text-sm text-muted">CLI is off. Turn it on under Settings to see how to connect.</p>
        <Link to="/settings" className="text-sm font-medium text-accent">
          Open settings
        </Link>
      </div>
    );
  }

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">CLI</h1>
        <p className="mt-1 text-sm text-muted">
          Same job as <Link to="/chat" className="underline">Chat</Link> and{" "}
          <Link to="/search" className="underline">Search</Link>. A link, a file, or a model name, then a material, then start.
        </p>
      </div>
      <section className="flex min-h-[50vh] flex-col rounded-card border border-line bg-bg p-4 font-mono text-sm">
        <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-line pb-2 text-xs text-muted">
          <p>print-handy</p>
          <p>
            {label}
            {job.job.name ? ` · ${job.job.name}` : ""}
            {job.job.material ? ` · ${job.job.material}` : ""}
          </p>
        </div>
        <div className="mt-3 flex flex-1 flex-col gap-1">
          {job.lines.map((line, index) => (
            <p key={`${index}-${line.text}`}>
              <span className="text-muted">{line.role === "you" ? "you › " : "bot › "}</span>
              {line.text}
            </p>
          ))}
          <div ref={end} />
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          {hintsFor(job.job.stage).map((hint) => (
            <button
              key={hint}
              type="button"
              disabled={job.busy}
              className="rounded-card border border-line px-2 py-1 text-xs uppercase text-muted"
              onClick={() => submit(hint)}
            >
              {hint}
            </button>
          ))}
        </div>
        <form
          className="mt-3 flex gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            submit(text);
          }}
        >
          <span className="text-muted">›</span>
          <input
            ref={inputRef}
            className="min-w-0 flex-1 bg-transparent text-ink outline-none"
            value={text}
            onChange={(event) => {
              cursor.current = -1;
              setText(event.target.value);
            }}
            onKeyDown={onKeyDown}
            placeholder="link, file, material, start, status, reset"
            disabled={job.busy}
            autoCapitalize="off"
            autoCorrect="off"
            spellCheck={false}
          />
        </form>
        {job.apiNote ? <p className="mt-2 text-xs text-muted">{job.apiNote}</p> : null}
        <label className="mt-3 inline-block self-start rounded-card border border-line px-3 py-2 text-xs">
          Upload a file
          <input
            className="sr-only"
            type="file"
            accept=".stl,.3mf,.gcode,.bgcode"
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) submit(file.name);
              event.target.value = "";
            }}
          />
        </label>
      </section>
    </div>
  );
}
