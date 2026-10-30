import { catalogByFile, searchCatalog } from "@/lib/catalog";
import { fuzzyScore, normalize } from "@/lib/fuzzy";

export type Stage = "need-source" | "need-material" | "need-confirm" | "queued";

export type Job = {
  stage: Stage;
  source: "link" | "file" | null;
  name: string;
  material: string | null;
};

export type TurnResult = { job: Job; lines: string[] };

export const MATERIALS = ["abs", "asa", "nylon", "petg", "pla", "tpu"] as const;

export const STAGE_LABEL: Record<Stage, string> = {
  "need-source": "waiting for a model",
  "need-material": "pick a material",
  "need-confirm": "ready to queue",
  queued: "queued",
};

const HELP = [
  "Paste a link, name a file (.stl, .3mf, .gcode, .bgcode), or a model such as benchy.",
  "Search uses the same list. A shorter query shows more matches.",
  "Then name a material: pla, petg, abs, asa, tpu, or nylon. Close spellings count.",
  "start queues it. status checks the job. reset clears it.",
  "Chat, the CLI, and Search share this job. This preview does not start the printer.",
];

const COMMANDS = ["help", "status", "reset", "start"] as const;
type Command = (typeof COMMANDS)[number];

export function emptyJob(): Job {
  return { stage: "need-source", source: null, name: "", material: null };
}

export function reply(job: Job, raw: string, printerName: string): TurnResult {
  const input = raw.trim().slice(0, 2000);
  const printer = printerName.trim().slice(0, 80) || "the printer";
  if (!input) return { job, lines: HELP };

  const command = matchCommand(input);
  if (command === "help") return { job, lines: HELP };
  if (command === "status") return { job, lines: [describe(job, printer)] };
  if (command === "reset") return { job: emptyJob(), lines: ["Cleared. Paste a link, name a file, or search for a model."] };

  const link = input.match(/https?:\/\/\S+/i)?.[0];
  const file = fileName(input);
  if (link || file) return gotSource(link ? "link" : "file", (link ?? file ?? "").slice(0, 500), printer);

  const material = matchMaterial(input);
  if (material) {
    if (!job.name) return { job, lines: ["Paste a link, name a file, or pick a model from Search first."] };
    const next: Job = { ...job, material, stage: "need-confirm" };
    return {
      job: next,
      lines: [
        `${material.toUpperCase()} on ${printer}.`,
        "Say start to queue it. This preview does not start the printer.",
      ],
    };
  }

  const picked = pickCatalog(input);
  if (picked.kind === "one") return gotSource("file", picked.file, printer, picked.title);
  if (picked.kind === "many") {
    return { job, lines: [`A few matches: ${picked.titles}. Say one name, or open Search.`] };
  }

  if (command === "start") {
    if (job.stage !== "need-confirm" || !job.material || !job.name) return { job, lines: [promptFor(job)] };
    return {
      job: { ...job, stage: "queued" },
      lines: [
        `Queued ${job.name} in ${job.material.toUpperCase()} for ${printer}.`,
        "A real install would slice, then wait on the start button. Nothing was sent to a printer.",
      ],
    };
  }

  if (job.stage === "queued") return { job, lines: ["That job is already queued. Say reset to start another."] };
  return { job, lines: ["I didn't catch that. Try a model name, a file, or help."] };
}

function gotSource(source: "link" | "file", name: string, printer: string, title?: string): TurnResult {
  const known = source === "file" ? catalogByFile(name) : undefined;
  const label = title ?? known?.title;
  const next: Job = { stage: "need-material", source, name, material: null };
  return {
    job: next,
    lines: [
      label && label.toLowerCase() !== name.toLowerCase() ? `Got ${label} (${name}).` : `Got ${name}.`,
      `I'll slice it for ${printer}. Which material? pla, petg, abs, asa, tpu, or nylon.`,
    ],
  };
}

function pickCatalog(input: string): { kind: "one"; file: string; title: string } | { kind: "many"; titles: string } | { kind: "none" } {
  const hits = searchCatalog(input);
  const top = hits[0];
  if (!top || top.score < 420) return { kind: "none" };
  const close = hits.filter((hit) => top.score - hit.score < 80);
  if (close.length > 1) {
    return { kind: "many", titles: close.slice(0, 4).map((hit) => hit.item.title).join(", ") };
  }
  return { kind: "one", file: top.item.file, title: top.item.title };
}

function matchMaterial(input: string): (typeof MATERIALS)[number] | null {
  return bestFuzzy(normalize(input), MATERIALS, 500);
}

function matchCommand(input: string): Command | null {
  const token = normalize(input.split(/\s+/)[0] ?? "");
  if (token === "cancel" || token === "clear") return "reset";
  if (token === "yes" || token === "go") return "start";
  return bestFuzzy(token, COMMANDS, 500);
}

function bestFuzzy<T extends string>(needle: string, options: readonly T[], floor: number): T | null {
  if (!needle) return null;
  let best: { value: T; score: number } | null = null;
  let second = 0;
  for (const value of options) {
    const score = fuzzyScore(needle, value);
    if (!best || score > best.score) {
      second = best?.score ?? 0;
      best = { value, score };
    } else if (score > second) {
      second = score;
    }
  }
  if (!best || best.score < floor) return null;
  if (second >= floor && best.score - second < 40) return null;
  return best.value;
}

export function describe(job: Job, printerName: string): string {
  const printer = printerName.trim().slice(0, 80) || "the printer";
  const where = STAGE_LABEL[job.stage];
  if (!job.name) return `${where}. Nothing attached yet. Printer is ${printer}.`;
  const material = job.material ? ` in ${job.material.toUpperCase()}` : "";
  return `${where}. ${job.name}${material} for ${printer}.`;
}

function promptFor(job: Job): string {
  if (job.stage === "need-material") return "Which material? pla, petg, abs, asa, tpu, or nylon.";
  if (job.stage === "need-confirm") return "Say start to queue it, or name a different material.";
  if (job.stage === "queued") return "Queued. Say reset to start another.";
  return "Paste a link, name a file, or say a model such as benchy.";
}

function fileName(input: string): string | null {
  const match = input.match(/[\w .()-]+\.(?:stl|3mf|gcode|bgcode)/i);
  return match ? match[0].trim() : null;
}

export function normalizeJob(value: unknown): Job {
  const job = emptyJob();
  if (!value || typeof value !== "object") return job;
  const record = value as Partial<Job>;
  const stages: Stage[] = ["need-source", "need-material", "need-confirm", "queued"];
  if (record.stage && stages.includes(record.stage)) job.stage = record.stage;
  if (record.source === "link" || record.source === "file") job.source = record.source;
  if (typeof record.name === "string") job.name = record.name.slice(0, 500);
  if (typeof record.material === "string" && MATERIALS.includes(record.material as (typeof MATERIALS)[number])) {
    job.material = record.material;
  }
  return job;
}
