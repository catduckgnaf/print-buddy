# Local overlay (everything here except this file is gitignored)

Put your real, private profile files here. `scripts/install-hermes.sh` copies each one over the Hermes profile at the same relative path.
Examples: `SOUL.md` (your persona), `MEMORY.md` (slot colors, house rules), `config.yaml` (LAN URLs, channel IDs, model), `.env` (tokens).
`systemd/hermes-print-buddy-listener.service.d/90-local.conf` adds personal `Environment=` lines to the listener.
A replaced profile file is first moved to `<name>.bak-<time>`. Never commit anything here.
