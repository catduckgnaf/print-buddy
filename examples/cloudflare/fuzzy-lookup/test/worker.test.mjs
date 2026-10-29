// Offline tests for the fuzzy-lookup Worker. Run with: node --test
// No npm install, no Cloudflare account: env.AI is a mock whose fake
// embeddings are deterministic word-concept vectors.
import { test, beforeEach } from "node:test";
import assert from "node:assert/strict";

import worker, { clearCache, EMBEDDING_MODEL, MAX_CANDIDATES, MAX_TEXT_CHARS } from "../src/index.js";

const SECRET = "test-secret-123";
const BASE = `https://fuzzy.example.workers.dev/${SECRET}`;

// Each concept is one dimension; a text's vector counts the concept words
// it contains, plus a small per-text hash dimension so unrelated texts are
// not all identical.
const CONCEPTS = [
  ["stick", "adhesion", "bed", "first layer", "warp", "lift"],
  ["clog", "nozzle", "extru", "jam", "under"],
  ["string", "ooze", "hair", "retract"],
  ["ring", "ghost", "vibrat", "shaker"],
];

function fakeEmbedding(text) {
  const t = text.toLowerCase();
  const v = CONCEPTS.map((words) => words.reduce((n, w) => n + (t.includes(w) ? 1 : 0), 0));
  let h = 0;
  for (const ch of t) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  v.push(0.05 + (h % 100) / 1000);
  return v;
}

function mockAI({ fail = null, extraRow = false } = {}) {
  const ai = {
    calls: [],
    async run(model, input) {
      ai.calls.push({ model, input });
      if (fail) throw new Error(fail);
      const data = input.text.map(fakeEmbedding);
      if (extraRow) data.push(fakeEmbedding("intruder"));
      return { shape: [data.length, data[0].length], data };
    },
  };
  return ai;
}

const CANDIDATES = [
  { id: "symptom:first-layer-not-sticking", text: "First layer not sticking (bed adhesion)" },
  { id: "flow:clog", text: "Nozzle clog" },
  { id: "symptom:stringing", text: "Stringing and oozing" },
  { id: "symptom:ringing", text: "Ringing / ghosting" },
];

function post(body, { path = BASE, method = "POST" } = {}) {
  return new Request(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: method === "GET" || method === "HEAD" ? undefined : typeof body === "string" ? body : JSON.stringify(body),
  });
}

async function call(ai, body, opts) {
  const res = await worker.fetch(post(body, opts), { AI: ai, LOOKUP_SECRET: SECRET });
  const text = await res.text();
  let data = null;
  try {
    data = JSON.parse(text);
  } catch {}
  return { status: res.status, data, res };
}

beforeEach(() => clearCache());

test("ranks candidates by meaning, best first, with scores in 0..1", async () => {
  const ai = mockAI();
  const { status, data } = await call(ai, { query: "bed wont stick, corners lift", candidates: CANDIDATES, threshold: 0.3, limit: 5 });
  assert.equal(status, 200);
  assert.equal(data.degraded, false);
  assert.equal(data.matches[0].id, "symptom:first-layer-not-sticking");
  for (const m of data.matches) assert.ok(m.score >= 0 && m.score <= 1);
  const scores = data.matches.map((m) => m.score);
  assert.deepEqual(scores, [...scores].sort((a, b) => b - a));
  assert.equal(ai.calls[0].model, EMBEDDING_MODEL);
});

test("threshold drops weak matches; default threshold is 0.55", async () => {
  const ai = mockAI();
  const loose = await call(ai, { query: "nozzle jam", candidates: CANDIDATES, threshold: 0 });
  assert.ok(loose.data.matches.length > 1);
  const strict = await call(ai, { query: "nozzle jam", candidates: CANDIDATES });
  assert.deepEqual(strict.data.matches.map((m) => m.id), ["flow:clog"]);
  const none = await call(ai, { query: "nozzle jam", candidates: CANDIDATES, threshold: 1 });
  assert.deepEqual(none.data.matches, []);
});

test("exact match short-circuits with no AI call", async () => {
  const ai = mockAI();
  const byText = await call(ai, { query: "  nozzle   CLOG ", candidates: CANDIDATES });
  assert.deepEqual(byText.data, { matches: [{ id: "flow:clog", text: "Nozzle clog", score: 1 }], degraded: false });
  const byId = await call(ai, { query: "flow:clog", candidates: CANDIDATES });
  assert.equal(byId.data.matches[0].id, "flow:clog");
  assert.equal(ai.calls.length, 0);
});

test("a warm cache makes no new AI calls for repeated candidates", async () => {
  const ai = mockAI();
  await call(ai, { query: "bed wont stick", candidates: CANDIDATES });
  assert.equal(ai.calls.length, 1);
  assert.equal(ai.calls[0].input.text.length, CANDIDATES.length + 1);
  await call(ai, { query: "bed wont stick", candidates: CANDIDATES });
  assert.equal(ai.calls.length, 1, "same query and candidates: everything cached");
  await call(ai, { query: "parts warp off the plate", candidates: CANDIDATES });
  assert.equal(ai.calls.length, 2);
  assert.deepEqual(ai.calls[1].input.text, ["parts warp off the plate"], "only the new query is embedded");
});

test("large candidate lists are embedded in batches", async () => {
  const ai = mockAI();
  const many = Array.from({ length: 250 }, (_, i) => ({ id: `c${i}`, text: `candidate number ${i}` }));
  const { data } = await call(ai, { query: "anything", candidates: many });
  assert.equal(data.degraded, false);
  assert.equal(ai.calls.length, 3);
  assert.ok(ai.calls.every((c) => c.input.text.length <= 100));
});

test("an AI error (quota, outage) degrades instead of failing", async () => {
  const ai = mockAI({ fail: "4006: you have used up your daily free allocation" });
  const { status, data } = await call(ai, { query: "bed wont stick", candidates: CANDIDATES });
  assert.equal(status, 200);
  assert.deepEqual(data.matches, []);
  assert.equal(data.degraded, true);
  assert.match(data.reason, /daily free allocation/);
});

test("a missing AI binding degrades", async () => {
  const res = await worker.fetch(post({ query: "bed wont stick", candidates: CANDIDATES }), { LOOKUP_SECRET: SECRET });
  const data = await res.json();
  assert.equal(data.degraded, true);
  assert.match(data.reason, /AI binding/);
});

test("a malformed embeddings answer degrades and never invents ids", async () => {
  const ai = mockAI({ extraRow: true });
  const { data } = await call(ai, { query: "bed wont stick", candidates: CANDIDATES });
  assert.equal(data.degraded, true);
  assert.deepEqual(data.matches, []);
});

test("only ids from the sent candidates are returned", async () => {
  const ai = mockAI();
  const sent = new Set(CANDIDATES.map((c) => c.id));
  for (const query of ["bed wont stick", "stringy hairs", "ghost lines", "symptom:unknown", "flow:clog"]) {
    const { data } = await call(ai, { query, candidates: CANDIDATES, threshold: 0 });
    for (const m of data.matches) assert.ok(sent.has(m.id), `${m.id} was not sent`);
  }
});

test("limit is respected", async () => {
  const ai = mockAI();
  const { data } = await call(ai, { query: "bed nozzle string ring", candidates: CANDIDATES, threshold: 0, limit: 2 });
  assert.equal(data.matches.length, 2);
  const capped = await call(ai, { query: "bed nozzle string ring", candidates: CANDIDATES, threshold: 0, limit: 9999 });
  assert.equal(capped.data.matches.length, CANDIDATES.length);
});

test("a wrong or missing secret answers 404", async () => {
  const ai = mockAI();
  for (const path of ["https://fuzzy.example.workers.dev/wrong", "https://fuzzy.example.workers.dev/",
    `https://fuzzy.example.workers.dev/x/${SECRET}`]) {
    const { status } = await call(ai, { query: "x", candidates: CANDIDATES }, { path });
    assert.equal(status, 404, path);
  }
  const res = await worker.fetch(post({ query: "x", candidates: CANDIDATES }), { AI: ai });
  assert.equal(res.status, 404, "no LOOKUP_SECRET configured: refuse everything");
  assert.equal(ai.calls.length, 0);
});

test("extra path segments after the secret are accepted", async () => {
  const { status } = await call(mockAI(), { query: "Nozzle clog", candidates: CANDIDATES }, { path: `${BASE}/fuzzy` });
  assert.equal(status, 200);
});

test("non-POST answers 405", async () => {
  const { status, res } = await call(mockAI(), null, { method: "GET" });
  assert.equal(status, 405);
  assert.equal(res.headers.get("Allow"), "POST");
});

test("malformed bodies answer 400", async () => {
  const ai = mockAI();
  const bad = [
    "not json",
    "[]",
    { candidates: CANDIDATES },
    { query: "   ", candidates: CANDIDATES },
    { query: "x" },
    { query: "x", candidates: "nope" },
    { query: "x", candidates: [{ id: "a" }] },
    { query: "x", candidates: [{ text: "a" }] },
    { query: "x", candidates: [null] },
  ];
  for (const body of bad) {
    const { status } = await call(ai, body);
    assert.equal(status, 400, JSON.stringify(body));
  }
  assert.equal(ai.calls.length, 0);
});

test("size caps: candidate count and text length", async () => {
  const ai = mockAI();
  const tooMany = Array.from({ length: MAX_CANDIDATES + 1 }, (_, i) => ({ id: `c${i}`, text: `t${i}` }));
  assert.equal((await call(ai, { query: "x", candidates: tooMany })).status, 400);
  const longText = "a".repeat(MAX_TEXT_CHARS + 1);
  assert.equal((await call(ai, { query: longText, candidates: CANDIDATES })).status, 400);
  assert.equal((await call(ai, { query: "x", candidates: [{ id: "a", text: longText }] })).status, 400);
  const huge = JSON.stringify({ query: "x", candidates: CANDIDATES, pad: "p".repeat(600 * 1024) });
  assert.equal((await call(ai, huge)).status, 413);
  assert.equal(ai.calls.length, 0);
  const atCap = Array.from({ length: MAX_CANDIDATES }, (_, i) => ({ id: `c${i}`, text: `t${i}` }));
  assert.equal((await call(ai, { query: "x", candidates: atCap })).status, 200);
});

test("empty candidate list answers no matches without an AI call", async () => {
  const ai = mockAI();
  const { status, data } = await call(ai, { query: "x", candidates: [] });
  assert.equal(status, 200);
  assert.deepEqual(data, { matches: [], degraded: false });
  assert.equal(ai.calls.length, 0);
});
