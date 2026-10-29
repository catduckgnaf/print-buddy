// Print Handy semantic lookup Worker: the PRINT_FUZZY_URL contract (#468).
//
// Request:  POST /<LOOKUP_SECRET>  {"query", "candidates": [{"id", "text"}], "threshold"?, "limit"?}
// Response: {"matches": [{"id", "text", "score"}], "degraded": false}
//       or  {"matches": [], "degraded": true, "reason": "..."}
//
// Stateless: candidates travel with every request and nothing is written
// anywhere. The only state is an in-isolate cache of embeddings keyed by a
// SHA-256 of the text, which lives in memory until the isolate is recycled.
// The secret is the first path segment (Print Handy sends no Authorization
// header); a wrong or missing secret answers 404.

export const EMBEDDING_MODEL = "@cf/baai/bge-small-en-v1.5";
export const DEFAULT_THRESHOLD = 0.55;
export const DEFAULT_LIMIT = 5;
export const MAX_LIMIT = 50;
// Bounds that keep a public endpoint from being used as a free embeddings
// service. Print Handy itself sends at most 1000 candidates of at most 200
// characters each (print_handy/core/fuzzy_semantic.py).
export const MAX_CANDIDATES = 1000;
export const MAX_TEXT_CHARS = 500;
export const MAX_BODY_BYTES = 512 * 1024;
// Texts per embeddings call, and the in-isolate cache size.
export const EMBED_BATCH = 100;
export const CACHE_MAX_ENTRIES = 5000;

const cache = new Map();

export function clearCache() {
  cache.clear();
}

function json(body, status = 200, headers = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

function notFound() {
  return new Response("Not found", { status: 404 });
}

async function sha256Hex(text) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

// Constant-time comparison: both sides are hashed first, so the loop always
// runs over 32 bytes whatever the inputs' lengths are.
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

function normalize(text) {
  return text.trim().toLowerCase().replace(/\s+/g, " ");
}

function cosine(a, b) {
  let dot = 0;
  let na = 0;
  let nb = 0;
  for (let i = 0; i < a.length; i++) {
    dot += a[i] * b[i];
    na += a[i] * a[i];
    nb += b[i] * b[i];
  }
  if (na === 0 || nb === 0) return 0;
  return dot / Math.sqrt(na * nb);
}

function clampNumber(value, fallback, lo, hi) {
  const n = Number(value);
  if (value === undefined || value === null || !Number.isFinite(n)) return fallback;
  return Math.min(hi, Math.max(lo, n));
}

// Validate the request body. Returns {error} or the cleaned request.
export function parseRequest(data) {
  if (!data || typeof data !== "object" || Array.isArray(data)) {
    return { error: "body must be a JSON object" };
  }
  const { query, candidates } = data;
  if (typeof query !== "string" || !query.trim()) {
    return { error: "query must be a non-empty string" };
  }
  if (query.length > MAX_TEXT_CHARS) {
    return { error: `query is longer than ${MAX_TEXT_CHARS} characters` };
  }
  if (!Array.isArray(candidates)) {
    return { error: "candidates must be an array" };
  }
  if (candidates.length > MAX_CANDIDATES) {
    return { error: `more than ${MAX_CANDIDATES} candidates` };
  }
  const cleaned = [];
  const seen = new Set();
  for (const c of candidates) {
    if (!c || typeof c !== "object" || (typeof c.id !== "string" && typeof c.id !== "number")) {
      return { error: "each candidate needs an id and a text" };
    }
    if (typeof c.text !== "string") {
      return { error: "each candidate needs an id and a text" };
    }
    if (c.text.length > MAX_TEXT_CHARS) {
      return { error: `a candidate text is longer than ${MAX_TEXT_CHARS} characters` };
    }
    const id = String(c.id);
    if (seen.has(id) || !c.text.trim()) continue;
    seen.add(id);
    cleaned.push({ id, text: c.text });
  }
  return {
    query: query.trim(),
    candidates: cleaned,
    threshold: clampNumber(data.threshold, DEFAULT_THRESHOLD, 0, 1),
    limit: Math.floor(clampNumber(data.limit, DEFAULT_LIMIT, 1, MAX_LIMIT)),
  };
}

function remember(key, vector) {
  if (cache.size >= CACHE_MAX_ENTRIES) {
    // Map keeps insertion order: drop the oldest entry.
    cache.delete(cache.keys().next().value);
  }
  cache.set(key, vector);
}

// Embed texts, using the cache where possible. Throws on any AI failure or
// on an answer whose shape does not match what was asked.
async function embed(ai, texts) {
  const keys = await Promise.all(texts.map((t) => sha256Hex(t)));
  const vectors = new Array(texts.length);
  const missing = [];
  keys.forEach((key, i) => {
    const hit = cache.get(key);
    if (hit) vectors[i] = hit;
    else missing.push(i);
  });
  // Texts repeated within one request are embedded once.
  const unique = [...new Map(missing.map((i) => [keys[i], i])).values()];
  for (let start = 0; start < unique.length; start += EMBED_BATCH) {
    const batch = unique.slice(start, start + EMBED_BATCH);
    const out = await ai.run(EMBEDDING_MODEL, { text: batch.map((i) => texts[i]) });
    const data = out && out.data;
    if (!Array.isArray(data) || data.length !== batch.length) {
      throw new Error("embeddings answer did not match the request");
    }
    batch.forEach((i, j) => {
      if (!Array.isArray(data[j]) || data[j].length === 0) {
        throw new Error("embeddings answer did not match the request");
      }
      remember(keys[i], data[j]);
    });
  }
  keys.forEach((key, i) => {
    if (!vectors[i]) vectors[i] = cache.get(key);
  });
  if (vectors.some((v) => !v)) throw new Error("embedding missing after the model call");
  return vectors;
}

export async function lookup(env, request) {
  const { query, candidates, threshold, limit } = request;
  if (candidates.length === 0) return { matches: [], degraded: false };

  // Exact match (case and whitespace insensitive, on text or id): answer
  // without spending an AI call.
  const wanted = normalize(query);
  const exact = candidates.filter((c) => normalize(c.text) === wanted || normalize(c.id) === wanted);
  if (exact.length) {
    return { matches: exact.slice(0, limit).map((c) => ({ id: c.id, text: c.text, score: 1 })), degraded: false };
  }

  if (!env.AI || typeof env.AI.run !== "function") {
    return { matches: [], degraded: true, reason: "the AI binding is not configured" };
  }
  let vectors;
  try {
    vectors = await embed(env.AI, [query, ...candidates.map((c) => c.text)]);
  } catch (err) {
    const message = String((err && err.message) || err).slice(0, 200);
    return { matches: [], degraded: true, reason: `embeddings unavailable: ${message}` };
  }
  const [queryVector, ...candidateVectors] = vectors;
  const matches = candidates
    .map((c, i) => ({ id: c.id, text: c.text, score: Math.max(0, Math.min(1, cosine(queryVector, candidateVectors[i]))) }))
    .filter((m) => m.score >= threshold)
    .sort((a, b) => b.score - a.score)
    .slice(0, limit)
    .map((m) => ({ ...m, score: Math.round(m.score * 10000) / 10000 }));
  return { matches, degraded: false };
}

export default {
  async fetch(req, env) {
    if (!(await secretMatches(firstSegment(req.url), env.LOOKUP_SECRET))) {
      return notFound();
    }
    if (req.method !== "POST") {
      return json({ error: "use POST" }, 405, { Allow: "POST" });
    }
    const declared = Number(req.headers.get("Content-Length") || 0);
    if (declared > MAX_BODY_BYTES) {
      return json({ error: "request body too large" }, 413);
    }
    const raw = await req.text();
    if (raw.length > MAX_BODY_BYTES) {
      return json({ error: "request body too large" }, 413);
    }
    let data;
    try {
      data = JSON.parse(raw);
    } catch {
      return json({ error: "body is not valid JSON" }, 400);
    }
    const parsed = parseRequest(data);
    if (parsed.error) return json({ error: parsed.error }, 400);
    return json(await lookup(env, parsed));
  },
};
