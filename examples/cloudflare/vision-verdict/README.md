# Camera verdict Worker (PRINT_VISION_URL)

A small Cloudflare Worker that answers Print Handy's `PRINT_VISION_URL` contract ([docs/SETTINGS.md](../../../docs/SETTINGS.md#custom-vision-endpoint-print_vision_url)). The camera watchdog sends a JPEG frame and its question; the Worker asks a Workers AI vision model, [`@cf/meta/llama-3.2-11b-vision-instruct`](https://developers.cloudflare.com/workers-ai/models/llama-3.2-11b-vision-instruct/) by default, and maps the answer onto Print Handy's verdicts: `ok`, `air`, `spaghetti`, `detached`, `empty_idle`, `uncertain`.

The operator guide for all of Print Handy's Cloudflare options is [docs/CLOUDFLARE.md](../../../docs/CLOUDFLARE.md).

## What it does

- Prepends a short instruction asking the model for `{"verdict": ..., "reason": ...}`, then reads the first JSON object in the answer. A verdict outside the vocabulary, or an answer that cannot be read, becomes `uncertain`, which Print Handy alerts on. It never guesses `ok`.
- A model error (quota used up, license not yet accepted, outage) or a missing AI binding answers HTTP 200 with `uncertain` and the error in `reason`, so the alert says what went wrong.
- `reason` is capped at 300 characters, the same cap Print Handy applies.
- Secret in the path: the first path segment must equal the `VISION_SECRET` secret (compared in constant time); anything else answers 404. Non-POST is 405, a malformed body is 400, an image over 4 MB is 413. Nothing is stored.
- `VISION_MODEL` (a plain variable in `wrangler.toml`) swaps in another Workers AI vision model.
- It answers verdicts only. Print Handy also sends spool-label photo reads (#514) to `PRINT_VISION_URL`; with this Worker those reads come back as a verdict instead of label fields, so the walkthrough falls back to its manual steps, as documented for verdict-only endpoints.

The image is passed to the model as the `image` byte array that the model's [published input schema](https://developers.cloudflare.com/workers-ai/models/llama-3.2-11b-vision-instruct/sync-input.json) documents. That schema marks the field as deprecated in favor of an image inside `messages`, but does not document the `messages` image shape, so this Worker uses the documented field.

## Deploy

You need a Cloudflare account (the free plan is enough) and a [supported Node.js release](https://developers.cloudflare.com/workers/wrangler/install-and-update/) (Current, Active or Maintenance LTS) for `npx wrangler`.

**One-time license step.** Meta's Llama 3.2 vision model needs its license accepted once per account before it answers. Cloudflare's [model page](https://developers.cloudflare.com/workers-ai/models/llama-3.2-11b-vision-instruct/) says to send one request with `"prompt": "agree"`:

```sh
curl https://api.cloudflare.com/client/v4/accounts/$CLOUDFLARE_ACCOUNT_ID/ai/run/@cf/meta/llama-3.2-11b-vision-instruct \
  -X POST -H "Authorization: Bearer $CLOUDFLARE_AUTH_TOKEN" -d '{"prompt": "agree"}'
```

`CLOUDFLARE_ACCOUNT_ID` and a Workers AI API token come from the dashboard's Workers AI page, **Use REST API** ([steps](https://developers.cloudflare.com/workers-ai/get-started/rest-api/)). Until this is done, every check answers `uncertain` with the model's error in the reason.

Then:

```sh
cd examples/cloudflare/vision-verdict
npx wrangler login
npx wrangler secret put VISION_SECRET   # paste a long random value, e.g. from: openssl rand -hex 24
npx wrangler deploy
```

`wrangler deploy` prints `https://print-handy-vision-verdict.<your-subdomain>.workers.dev`. Set, wherever Print Handy reads its environment (the `.env` file for Docker or the standalone bot):

```sh
PRINT_VISION_URL=https://print-handy-vision-verdict.<your-subdomain>.workers.dev/<the secret>
```

and restart Print Handy. `PRINT_VISION_URL` takes precedence over `services.vision_chat_url` for camera checks. Treat the full URL as a password.

## Test

Offline, with Node's built-in test runner and a mock AI binding; no `npm install`:

```sh
node --test "examples/cloudflare/**/*.test.mjs"
```

This Worker has only been tested against that mock. It has not been deployed to a real Cloudflare account, and the model's accuracy on real printer frames is unmeasured.

## Cost

At the [published rate](https://developers.cloudflare.com/workers-ai/platform/pricing/) (4410 Neurons per million input tokens, 61493 per million output tokens) one check is roughly 10 to 35 Neurons, depending on how many tokens the model counts for the image, which Cloudflare does not publish. See [docs/CLOUDFLARE.md](../../../docs/CLOUDFLARE.md) for the estimate against the 10,000 Neurons per day free allocation.
