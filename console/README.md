# Sample console (not part of Print Handy)

A front-end sample for a Print Handy style console. Nothing in `print_handy/`, the Web UI,
the Docker image or CI uses it, and it is excluded from the image by `.dockerignore`.

- **Origin.** The tree started as an app-builder scaffold (TanStack Start, Vite, Tailwind, Better Auth).
  Scaffold machinery remains: `scripts/`, `public/__grok/`, `vercel.json`, `migrations/`, `server/middleware/grok-pwa.ts`.
  The scaffold\x27s agent-instruction file (`AGENTS.md`) was removed because it described a different
  tool\x27s workflow and nothing here follows it. `scripts/brand-check.test.mjs` still refers to it and to
  `.grok/skills`, which are not in this repository, so that test does not pass as shipped.
- **Auth is the scaffold\x27s, not Print Handy\x27s.** `src/lib/auth/` talks to external issuers
  (`https://grok.com`, `https://gate.app-builder-testing.com`, `https://gate.grok.me`) when run on those hosts, and
  keeps its own users in a bundled database. It is unrelated to the Web UI\x27s token auth. Do not deploy it
  as a console for a real printer.
- **Not functional.** Settings persist only in the browser. It does not talk to a printer or to Moonraker.
- **Not built or tested in CI.** There is no Node job. The only repository test touching it is
  `tests/printers/test_snapmaker.py`, which pins `src/lib/printers.ts` to the printer registry.
- **Future.** Keep, trim or move out of this repository is the maintainer\x27s decision.

To run it locally: `npm install` then `npm run dev` (port 8080).
