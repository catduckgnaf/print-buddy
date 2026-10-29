// Print Handy camera verdict Worker: the PRINT_VISION_URL contract.
//
// Request:  POST /<VISION_SECRET>  {"image": "<base64 JPEG>", "prompt": "<question>"}
// Response: {"verdict": "ok|air|spaghetti|detached|empty_idle|uncertain", "reason": "..."}
//
// The frame is sent to a Workers AI vision model and the model's answer is
// mapped onto Print Handy's verdict vocabulary. Anything that cannot be
// parsed, and any model failure, answers "uncertain" (which Print Handy
// alerts on), never "ok". Nothing is stored. The secret is the first path
// segment (Print Handy sends no Authorization header); a wrong or missing
// secret answers 404.

export const DEFAULT_MODEL = "@cf/meta/llama-3.2-11b-vision-instruct";
export const VERDICTS = ["ok", "air", "spaghetti", "detached", "empty_idle", "uncertain"];
export const MAX_IMAGE_BYTES = 4 * 1024 * 1024;
export const MAX_PROMPT_CHARS = 4000;
export const MAX_REASON_CHARS = 300;
const MAX_BODY_CHARS = Math.ceil((MAX_IMAGE_BYTES * 4) / 3) + MAX_PROMPT_CHARS + 1024;

// Prepended to Print Handy's question: the contract leaves the format to
// the endpoint.
export const INSTRUCTIONS = `You are checking one camera frame from a 3D printer.
Answer with one JSON object and nothing else: {"verdict": "<verdict>", "reason": "<one short sentence>"}.
Use exactly one of these verdicts:
- ok: a print is in progress and looks normal.
- air: the nozzle is printing in mid-air; nothing is building up under it.
- spaghetti: tangled loose strands of plastic instead of a solid part.
- detached: the part has come loose from the bed or been knocked over.
- empty_idle: the printer is idle and the bed is empty.
- uncertain: you cannot tell (dark, blurry, blocked view, or anything else).
Question from the operator:`;

function json(body, status = 200, headers = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

// Constant-time comparison over SHA-256 digests (always 32 bytes).
export async function secretMatches(given, expected) {
  if (typeof expected !== "string" || expected.length === 0 || typeof given !== "string") {
    return false;
  }
  const enc = new TextEncoder();
  const a = new Uint8Array(await crypto.subtle.digest("SHA-256", enc.encode(given)));
  const b = new Uint8Array(await crypto.subtle.digest("SHA-256", enc.encode(expected)));
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a[i] ^ b[i];
  return diff === 0;
}

function firstSegment(url) {
  const segment = new URL(url).pathname.split("/").filter(Boolean)[0] || "";
  try {
    return decodeURIComponent(segment);
  } catch {
    return segment;
  }
}

function decodeBase64(text) {
  const clean = text.replace(/\s+/g, "");
  if (!clean || clean.length % 4 === 1 || !/^[A-Za-z0-9+/]*={0,2}$/.test(clean)) return null;
  try {
    const binary = atob(clean);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
    return bytes;
  } catch {
    return null;
  }
}

function uncertain(reason) {
  return { verdict: "uncertain", reason: String(reason).slice(0, MAX_REASON_CHARS) };
}

// Map the model's free text onto the verdict vocabulary.
export function toVerdict(text) {
  if (typeof text !== "string" || !text.trim()) {
    return uncertain("the vision model gave no answer");
  }
  const objectText = text.match(/\{[\s\S]*\}/);
  if (objectText) {
    try {
      const parsed = JSON.parse(objectText[0]);
      const verdict = String(parsed.verdict || "").trim().toLowerCase();
      if (VERDICTS.includes(verdict)) {
        return { verdict, reason: String(parsed.reason || "").slice(0, MAX_REASON_CHARS) };
      }
    } catch {
      // fall through to the looser match below
    }
  }
  const loose = text.match(/verdict["'\s]*[:=]\s*["']?([a-z_]+)/i);
  if (loose && VERDICTS.includes(loose[1].toLowerCase())) {
    return { verdict: loose[1].toLowerCase(), reason: "" };
  }
  return uncertain("the vision model's answer could not be read as a verdict");
}

export default {
  async fetch(req, env) {
    if (!(await secretMatches(firstSegment(req.url), env.VISION_SECRET))) {
      return new Response("Not found", { status: 404 });
    }
    if (req.method !== "POST") {
      return json({ error: "use POST" }, 405, { Allow: "POST" });
    }
    if (Number(req.headers.get("Content-Length") || 0) > MAX_BODY_CHARS) {
      return json({ error: "request body too large" }, 413);
    }
    const raw = await req.text();
    if (raw.length > MAX_BODY_CHARS) {
      return json({ error: "request body too large" }, 413);
    }
    let data;
    try {
      data = JSON.parse(raw);
    } catch {
      return json({ error: "body is not valid JSON" }, 400);
    }
    if (!data || typeof data !== "object" || Array.isArray(data)) {
      return json({ error: "body must be a JSON object" }, 400);
    }
    if (typeof data.prompt !== "string" || !data.prompt.trim() || data.prompt.length > MAX_PROMPT_CHARS) {
      return json({ error: `prompt must be a non-empty string of at most ${MAX_PROMPT_CHARS} characters` }, 400);
    }
    const image = typeof data.image === "string" ? decodeBase64(data.image) : null;
    if (!image || image.length === 0) {
      return json({ error: "image must be standard base64 with no data: prefix" }, 400);
    }
    if (image.length > MAX_IMAGE_BYTES) {
      return json({ error: "image too large" }, 413);
    }
    if (!env.AI || typeof env.AI.run !== "function") {
      return json(uncertain("the vision check could not run: the AI binding is not configured"));
    }
    let out;
    try {
      out = await env.AI.run(env.VISION_MODEL || DEFAULT_MODEL, {
        prompt: `${INSTRUCTIONS}\n${data.prompt.trim()}`,
        image: [...image],
        max_tokens: 120,
        temperature: 0,
      });
    } catch (err) {
      return json(uncertain(`the vision model could not be reached: ${String((err && err.message) || err).slice(0, 200)}`));
    }
    return json(toVerdict(out && out.response));
  },
};
