# Semantic lookup Worker (PRINT_FUZZY_URL)

A small Cloudflare Worker that answers Print Handy's `PRINT_FUZZY_URL` contract ([docs/SETTINGS.md](../../../docs/SETTINGS.md#semantic-lookup-endpoint-print_fuzzy_url)). When `/print-lookup` finds nothing locally, Print Handy sends the query and its public registry entries here; the Worker embeds them with Workers AI's [`@cf/baai/bge-small-en-v1.5`](https://developers.cloudflare.com/workers-ai/models/bge-small-en-v1.5/) model and returns the closest entries by cosine similarity.

The operator guide for all of Print Handy's Cloudflare options is [docs/CLOUDFLARE.md](../../../docs/CLOUDFLARE.md).

## What it does

- **Stateless.** Candidates arrive with every request. Nothing is written to KV, D1, Vectorize or logs by this code. The only state is an in-memory cache of embeddings, keyed by a SHA-256 of each text, that lives until Cloudflare recycles the isolate. A warm cache means a repeated lookup embeds only the new query.
- **Exact match short circuit.** A query equal to a candidate's text or id (ignoring case and extra spaces) answers with score 1 and no AI call.
- **Threshold and limit come from the request** (Print Handy sends `0.55` and `5`); the defaults are the same. The limit is capped at 50.
- **Only ids that were sent come back.** The Worker ranks the candidates it was given and nothing else.
- **Failures degrade.** A quota or model error, a missing AI binding or a malformed model answer returns `{"matches": [], "degraded": true, "reason": "..."}` with HTTP 200, and Print Handy keeps its local answer.
- **Secret in the path.** The first path segment must equal the `LOOKUP_SECRET` secret (compared in constant time); anything else answers 404. Print Handy sends no `Authorization` header, so the secret lives in the URL.
- **Abuse limits for a public URL.** At most 1000 candidates, 500 characters per text or query, and a 512 KB body. Anything bigger answers 400 or 413 without an AI call. Print Handy itself sends about 120 candidates of at most 200 characters.
- Other answers: non-POST is 405, a body that is not the contract's JSON is 400.

## Deploy

You need a Cloudflare account (the free plan is enough) and a [supported Node.js release](https://developers.cloudflare.com/workers/wrangler/install-and-update/) (Current, Active or Maintenance LTS) for `npx wrangler`.

```sh
cd examples/cloudflare/fuzzy-lookup
npx wrangler login
npx wrangler secret put LOOKUP_SECRET   # paste a long random value, e.g. from: openssl rand -hex 24
npx wrangler deploy
```

`wrangler deploy` prints the Worker's address, `https://print-handy-fuzzy-lookup.<your-subdomain>.workers.dev`. Then set, wherever Print Handy reads its environment (the `.env` file for Docker or the standalone bot):

```sh
PRINT_FUZZY_URL=https://print-handy-fuzzy-lookup.<your-subdomain>.workers.dev/<the secret>
```

and restart Print Handy. To check it by hand:

```sh
curl -s -X POST "$PRINT_FUZZY_URL" -H 'Content-Type: application/json' \
  -d '{"query":"bed wont stick","candidates":[{"id":"a","text":"First layer not sticking (bed adhesion)"},{"id":"b","text":"Nozzle clog"}]}'
```

Treat the full URL as a password: anyone who has it can spend your Workers AI allocation. To rotate it, run `npx wrangler secret put LOOKUP_SECRET` again and update `PRINT_FUZZY_URL`.

## Test

The tests run offline with Node's built-in test runner and a mock AI binding (deterministic fake embeddings); no `npm install` and no Cloudflare account:

```sh
node --test "examples/cloudflare/**/*.test.mjs"
```

This Worker has only been tested against that mock. It has not been deployed to a real Cloudflare account by the project yet.

## Cost

Embedding Print Handy's whole candidate list (about 120 short texts, roughly 600 tokens) costs about 1 Neuron at the [published rate](https://developers.cloudflare.com/workers-ai/platform/pricing/) of 1841 Neurons per million input tokens; with a warm cache a lookup costs a tiny fraction of one. The free allocation is 10,000 Neurons per day. See [docs/CLOUDFLARE.md](../../../docs/CLOUDFLARE.md) for the full estimate.
