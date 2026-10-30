import { createFileRoute, Link } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";
import { fieldClass } from "@/components/install-fields";
import { useSharedJob } from "@/lib/job-store";
import { MATERIALS, STAGE_LABEL } from "@/lib/walkthrough";

export const Route = createFileRoute("/chat")({ component: ChatPage });

function ChatPage() {
  const job = useSharedJob();
  const [text, setText] = useState("");
  const end = useRef<HTMLDivElement>(null);

  useEffect(() => {
    end.current?.scrollIntoView({ block: "end" });
  }, [job.lines]);

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Chat</h1>
        <p className="mt-1 text-sm text-muted">
          Same job as <Link to="/search" className="underline">Search</Link>. A link, a file, or a model name, then a material, then start.
        </p>
      </div>
      <section className="flex min-h-[50vh] flex-col gap-3 rounded-card border border-line bg-surface p-4">
        <p className="text-xs text-muted">
          {STAGE_LABEL[job.job.stage]}
          {job.job.name ? ` · ${job.job.name}` : ""}
          {job.job.material ? ` · ${job.job.material}` : ""}
        </p>
        <div className="flex flex-1 flex-col gap-2">
          {job.lines.map((line, index) => (
            <p
              key={`${index}-${line.text}`}
              className={
                "max-w-[85%] rounded-card px-3 py-2 text-sm " +
                (line.role === "you" ? "self-end bg-ink text-bg" : "self-start bg-bg text-ink")
              }
            >
              {line.text}
            </p>
          ))}
          <div ref={end} />
        </div>
        {job.job.stage === "need-material" ? (
          <div className="flex flex-wrap gap-2">
            {MATERIALS.map((material) => (
              <button
                key={material}
                type="button"
                disabled={job.busy}
                className="rounded-card border border-line bg-bg px-3 py-2 text-sm uppercase"
                onClick={() => job.send(material)}
              >
                {material}
              </button>
            ))}
          </div>
        ) : null}
        {job.job.stage === "need-confirm" ? (
          <button
            type="button"
            disabled={job.busy}
            className="self-start rounded-card bg-accent px-4 py-2 text-sm font-medium text-accent-ink"
            onClick={() => job.send("start")}
          >
            Start
          </button>
        ) : null}
        <form
          className="flex flex-col gap-2 sm:flex-row"
          onSubmit={(event) => {
            event.preventDefault();
            void job.send(text);
            setText("");
          }}
        >
          <input
            className={fieldClass}
            value={text}
            onChange={(event) => setText(event.target.value)}
            placeholder="Paste a link, or type a material"
            disabled={job.busy}
          />
          <label className="rounded-card border border-line bg-bg px-4 py-2 text-center text-sm">
            File
            <input
              className="sr-only"
              type="file"
              accept=".stl,.3mf,.gcode,.bgcode"
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) void job.send(file.name);
                event.target.value = "";
              }}
            />
          </label>
          <button
            type="submit"
            disabled={job.busy || !text.trim()}
            className="rounded-card bg-ink px-4 py-2 text-sm font-medium text-bg disabled:opacity-40"
          >
            Send
          </button>
        </form>
        {job.apiNote ? <p className="text-xs text-muted">{job.apiNote}</p> : null}
      </section>
    </div>
  );
}
