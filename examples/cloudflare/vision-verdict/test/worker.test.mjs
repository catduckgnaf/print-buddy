// Offline tests for the vision-verdict Worker. Run with: node --test
// No npm install, no Cloudflare account: env.AI is a mock that returns
// canned model text.
import { test } from "node:test";
import assert from "node:assert/strict";

import worker, { DEFAULT_MODEL, INSTRUCTIONS, MAX_IMAGE_BYTES, toVerdict } from "../src/index.js";

const SECRET = "vision-secret-456";
const BASE = `https://vision.example.workers.dev/${SECRET}`;
const FRAME = Buffer.from([0xff, 0xd8, 0xff, 0xe0, 1, 2, 3, 4, 0xff, 0xd9]).toString("base64");
const PROMPT = "Is there plastic on the bed under the nozzle, or is there spaghetti/detachment?";

function mockAI(answer, { fail = null } = {}) {
  const ai = {
    calls: [],
    async run(model, input) {
      ai.calls.push({ model, input });
      if (fail) throw new Error(fail);
      return { response: answer };
    },
  };
  return ai;
}

async function call(ai, body, { path = BASE, method = "POST", env = {} } = {}) {
  const req = new Request(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: method === "GET" ? undefined : typeof body === "string" ? body : JSON.stringify(body),
  });
  const res = await worker.fetch(req, { AI: ai, VISION_SECRET: SECRET, ...env });
  const text = await res.text();
  let data = null;
  try {
    data = JSON.parse(text);
  } catch {}
  return { status: res.status, data, res };
}

test("a JSON answer becomes the verdict and reason", async () => {
  const ai = mockAI('{"verdict": "Spaghetti", "reason": "Loose strands around the nozzle."}');
  const { status, data } = await call(ai, { image: FRAME, prompt: PROMPT });
  assert.equal(status, 200);
  assert.deepEqual(data, { verdict: "spaghetti", reason: "Loose strands around the nozzle." });
  assert.equal(ai.calls.length, 1);
  const { model, input } = ai.calls[0];
  assert.equal(model, DEFAULT_MODEL);
  assert.ok(input.prompt.startsWith(INSTRUCTIONS) && input.prompt.endsWith(PROMPT));
  assert.deepEqual(input.image, [...Buffer.from(FRAME, "base64")]);
});

test("every verdict in the vocabulary passes through", async () => {
  for (const verdict of ["ok", "air", "spaghetti", "detached", "empty_idle", "uncertain"]) {
    const { data } = await call(mockAI(`Sure! {"verdict":"${verdict}","reason":"r"} Hope that helps.`), { image: FRAME, prompt: PROMPT });
    assert.equal(data.verdict, verdict);
  }
});

test("a loose 'verdict: x' answer is still read", async () => {
  assert.equal(toVerdict("verdict: detached, the part fell over").verdict, "detached");
});

test("unparseable or unknown answers become uncertain", () => {
  for (const text of ["", "The print looks great!", '{"verdict": "fine"}', '{"verdict": ', null, undefined]) {
    const out = toVerdict(text);
    assert.equal(out.verdict, "uncertain", String(text));
    assert.ok(out.reason.length > 0);
  }
});

test("reason is capped at 300 characters", () => {
  const out = toVerdict(JSON.stringify({ verdict: "ok", reason: "x".repeat(1000) }));
  assert.equal(out.reason.length, 300);
});

test("a model error answers uncertain, never ok", async () => {
  const { status, data } = await call(mockAI("", { fail: "5006: model agreement required" }), { image: FRAME, prompt: PROMPT });
  assert.equal(status, 200);
  assert.equal(data.verdict, "uncertain");
  assert.match(data.reason, /agreement required/);
});

test("a missing AI binding answers uncertain", async () => {
  const { data } = await call(undefined, { image: FRAME, prompt: PROMPT });
  assert.equal(data.verdict, "uncertain");
});

test("VISION_MODEL overrides the model", async () => {
  const ai = mockAI('{"verdict":"ok","reason":"fine"}');
  await call(ai, { image: FRAME, prompt: PROMPT }, { env: { VISION_MODEL: "@cf/example/other-vision" } });
  assert.equal(ai.calls[0].model, "@cf/example/other-vision");
});

test("a wrong or missing secret answers 404", async () => {
  const ai = mockAI('{"verdict":"ok"}');
  for (const path of ["https://vision.example.workers.dev/nope", "https://vision.example.workers.dev/"]) {
    assert.equal((await call(ai, { image: FRAME, prompt: PROMPT }, { path })).status, 404);
  }
  assert.equal((await call(ai, { image: FRAME, prompt: PROMPT }, { env: { VISION_SECRET: undefined } })).status, 404);
  assert.equal(ai.calls.length, 0);
});

test("non-POST answers 405", async () => {
  const { status } = await call(mockAI("x"), null, { method: "GET" });
  assert.equal(status, 405);
});

test("malformed bodies answer 400 without a model call", async () => {
  const ai = mockAI('{"verdict":"ok"}');
  for (const body of ["nope", "[]", { prompt: PROMPT }, { image: FRAME }, { image: "data:image/jpeg;base64,AAAA", prompt: PROMPT },
    { image: "!!!", prompt: PROMPT }, { image: FRAME, prompt: "  " }, { image: 42, prompt: PROMPT }]) {
    assert.equal((await call(ai, body)).status, 400, JSON.stringify(body));
  }
  assert.equal(ai.calls.length, 0);
});

test("an oversized image is refused", async () => {
  const big = Buffer.alloc(MAX_IMAGE_BYTES + 1).toString("base64");
  const ai = mockAI('{"verdict":"ok"}');
  assert.equal((await call(ai, { image: big, prompt: PROMPT })).status, 413);
  assert.equal(ai.calls.length, 0);
});
