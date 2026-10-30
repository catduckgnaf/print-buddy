import { createFileRoute, Link } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { fieldClass } from "@/components/install-fields";
import { searchCatalog, type CatalogItem } from "@/lib/catalog";
import { useSharedJob } from "@/lib/job-store";
import { MATERIALS, STAGE_LABEL } from "@/lib/walkthrough";

export const Route = createFileRoute("/search")({ component: SearchPage });

function SearchPage() {
  const job = useSharedJob();
  const [query, setQuery] = useState("");
  const [openId, setOpenId] = useState<string | null>(null);
  const hits = useMemo(() => searchCatalog(query), [query]);
  const expanded = query.trim() === "" || hits.length > 1;

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Search</h1>
        <p className="mt-1 text-sm text-muted">
          Same job as <Link to="/chat" className="underline">Chat</Link>. A shorter query expands the list. Picking a model
          continues the same walkthrough.
        </p>
      </div>
      <section className="flex flex-col gap-3 rounded-card border border-line bg-surface p-4">
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium">Models</span>
          <input
            className={fieldClass}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="benchy, cube, clip, spool"
            autoCapitalize="off"
            autoCorrect="off"
            spellCheck={false}
          />
        </label>
        <p className="text-xs text-muted">
          {hits.length} {hits.length === 1 ? "match" : "matches"}
          {expanded ? " · list expanded" : ""}
          {" · "}
          {STAGE_LABEL[job.job.stage]}
          {job.job.name ? ` · ${job.job.name}` : ""}
          {job.job.material ? ` · ${job.job.material}` : ""}
        </p>
        <ul className="flex flex-col gap-2">
          {hits.map(({ item }) => (
            <Result
              key={item.id}
              item={item}
              open={openId === item.id}
              active={job.job.name === item.file}
              busy={job.busy}
              onToggle={() => setOpenId((current) => (current === item.id ? null : item.id))}
              onUse={() => {
                setOpenId(item.id);
                void job.send(item.title);
              }}
            />
          ))}
          {hits.length === 0 ? <li className="text-sm text-muted">No match. Try a shorter name.</li> : null}
        </ul>
        <Walkthrough job={job} />
        <p className="text-xs text-muted">Sample catalog. Nothing is downloaded, and nothing is sent to a printer.</p>
      </section>
    </div>
  );
}

function Result({
  item,
  open,
  active,
  busy,
  onToggle,
  onUse,
}: {
  item: CatalogItem;
  open: boolean;
  active: boolean;
  busy: boolean;
  onToggle: () => void;
  onUse: () => void;
}) {
  return (
    <li className={"rounded-card border px-3 py-2 " + (active ? "border-accent bg-bg" : "border-line bg-bg")}>
      <button type="button" className="flex w-full items-center justify-between gap-3 py-1 text-left" onClick={onToggle}>
        <span>
          <span className="block text-sm font-medium">{item.title}</span>
          <span className="block font-mono text-xs text-muted">{item.file}</span>
        </span>
        <span className="text-xs text-muted">{open ? "Hide" : "Expand"}</span>
      </button>
      {open ? (
        <div className="mt-2 flex flex-col gap-2 border-t border-line pt-2">
          <p className="text-xs text-muted">{item.tags.join(", ")}</p>
          <button
            type="button"
            disabled={busy}
            className="self-start rounded-card bg-ink px-3 py-2 text-sm font-medium text-bg disabled:opacity-40"
            onClick={onUse}
          >
            {active ? "Use again" : "Use this model"}
          </button>
        </div>
      ) : null}
    </li>
  );
}

function Walkthrough({ job }: { job: ReturnType<typeof useSharedJob> }) {
  const recent = job.lines.slice(-4);
  return (
    <div className="flex flex-col gap-2 border-t border-line pt-3">
      {recent.map((line, index) => (
        <p key={`${index}-${line.text}`} className="text-sm text-muted">
          {line.role === "you" ? "You: " : "Bot: "}
          {line.text}
        </p>
      ))}
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
      {job.job.stage === "queued" ? (
        <button
          type="button"
          disabled={job.busy}
          className="self-start rounded-card border border-line px-3 py-2 text-sm"
          onClick={() => job.send("reset")}
        >
          Reset
        </button>
      ) : null}
      {job.apiNote ? <p className="text-xs text-muted">{job.apiNote}</p> : null}
    </div>
  );
}
