# Demo operations

Scripts for the self-run demo: a visitor works the main flow on their own
devices, served from this laptop through a Cloudflare quick tunnel.

## Reset (at home, before a visit)

```bash
ops/demo/reset.sh
```

Needs `docker`, `flutter`, `gzip`, `brotli` and the project's `.venv`. In order:

1. creates `.env.demo` on the first run only (later runs reuse it unchanged)
2. saves a dump of the previous visit's database as
   `.demo/archive/lamto-<date>-<time>.dump` (skipped when there is no database yet)
3. removes the demo's Postgres and MinIO volumes
4. recreates them, migrates and runs `seed_demo`, which prints the logins
5. builds the Resident app for the web (`--base-href /app/`) into
   `.demo/app` and pre-compresses it (`.gz` and `.br` beside each file)
6. collects static files into `.demo/static`
7. records fingerprints of the evidence secret and of the signer address in
   `.demo/fingerprints` (never the secrets)

Only the database is archived; the documents in MinIO are wiped without a copy.

It stops at the first failing step and says which. Run it again to retry.
A reset that stops partway leaves no fingerprints file, so `up` refuses.

`.env.demo`, `.demo/` are gitignored.

### Demo environment file

Generated once with its own secret key, evidence secret and platform signer
key (never the development key in `.env.example`), anchoring disabled, an empty
AI provider, debug off, the static root, and every `*.trycloudflare.com` host
allowed. Delete it to mint new keys; the next reset then re-records the
fingerprints.

### The development stack is never touched

The demo is its own compose project, `lamto-demo`; every compose call names it.
`compose.yaml` sets no project name, so the development stack's volumes belong
to the default project and the reset cannot reach them. The two stacks bind the
same fixed ports, so the reset refuses to run, with a message, while the
development stack is up. Stop it first (`docker compose stop`); its data stays.

Only the demo's Postgres and MinIO volumes are removed. The ClamAV volume, with
its downloaded signatures, is kept.

## Tests

`tests/ops/test_demo_reset.py` runs `reset.sh` against stand-ins for `docker`,
`flutter` and `manage.py`; `tests/ops/test_demo_env.py` covers the environment
file and fingerprints. Neither needs Docker.
