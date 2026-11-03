# Demo operations

Scripts and the runbook for the self-run demo: a visitor works the main flow on
their own devices, served from this laptop through a Cloudflare quick tunnel.

| When | Command | What it does |
|---|---|---|
| At home, before a visit | `ops/demo/reset.sh` | a clean demo: seed, web build, static files, key fingerprints |
| At the venue | `ops/demo/up.sh` | brings it up, checks it through the tunnel, then shows the address and a QR code |

## Runbook for a visit

**The day before, at home**

1. Stop the development stack if it is up (`docker compose stop`; its data is
   kept). The demo uses the same ports.
2. `ops/demo/reset.sh`. Copy the two logins it prints (from `seed_demo`) onto the
   cue card. A reset that stops partway leaves the demo unusable on purpose:
   run it again.
3. Print the out-of-service notice, `ops/demo-kit/files/thong-bao-tam-ngung-thang-may.pdf`,
   and take it along; it is the prop the visitor photographs.
4. Run `ops/demo/up.sh` once at home to see it pass, then stop it with Ctrl-C.

**At the venue**

1. Connect the laptop to power and the network. Make sure the development stack
   is not running.
2. `ops/demo/up.sh`. Leave it running in its terminal for the whole visit. It
   prints the steps as it goes: ClamAV (the first start after a long time can
   take minutes while it loads its signatures), the processes, the tunnel
   address, then the smoke check.
3. **Do not hand anything over until the address and the QR code appear.** They
   appear only after every smoke check has passed. If a check fails, the script
   says which, shows no address and stops everything it started; fix it and run
   it again. The logs are in `.demo/run/`.
4. The tunnel's address is new on every start. The visitor never needs to type
   it.

**Delivering the address**

| Device | How |
|---|---|
| Phone | The visitor scans the QR code on the laptop screen. It opens the Resident app's sign-in screen. |
| Laptop | Send the `/app/` address in a Zalo message from the phone or the Zalo web app; the visitor opens it in their browser. |

**The addresses the visitor uses**

| Address | What it is |
|---|---|
| `<tunnel>/app/` | the Resident app: sign in as the resident |
| `<tunnel>/s/` | the Management workspace: sign in as Management |
| `<tunnel>/demo-kit/` | the sample documents, listed on a Vietnamese page: the quotation, the Transfer proof, the notice |

`up.sh` prints all three under the QR code. The visitor's Management and
resident logins come from the cue card.

**Ending the visit**

Press Ctrl-C in the `up.sh` terminal. It stops gunicorn, the worker, Caddy and
cloudflared; the containers keep running. Run `ops/demo/reset.sh` before the
next visit; it keeps a copy of this visit's database under `.demo/archive/`.

**Device checklist** (before the first visit, on each phone, through the tunnel;
findings go in ticket 14)

- iPhone Safari and Android Chrome, each:
  - sign in with the demo resident login
  - take a photo with the camera, see its thumbnail, and send the report
  - open the quotation PDF in the in-app viewer; its pages render and the share
    action is offered
  - from a ledger entry, open the Evidence explorer in a new tab (note whether
    the browser blocked the tab)
- Note how Vietnamese Telex typing behaves. It does not decide pass or fail.
- A phone on mobile data, not the venue's Wi-Fi, scans the QR code and sees the
  sign-in screen.


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

## Up (at the venue)

```bash
ops/demo/up.sh
```

Needs `docker`, `caddy`, `cloudflared` and the project's `.venv` (with `gunicorn`
and `qrcode`). In order:

1. checks the machine and refuses, with a message, when
   - the development stack holds the ports,
   - there is no demo environment file,
   - the web build is missing (no `index.html` in `.demo/app`),
   - the evidence secret or the signer key no longer matches the fingerprint the
     reset recorded (or none was recorded),
   - Caddy's or gunicorn's port is already taken (`CADDY_PORT` 8080,
     `GUNICORN_PORT` 8000)
2. starts Postgres and MinIO, and ClamAV with `--no-recreate` (its container is
   never recreated), then waits until ClamAV answers a ping (up to 300 s,
   `DEMO_CLAMAV_TIMEOUT`)
3. copies the kit into `.demo/kit` with a Vietnamese `index.html`, then starts
   gunicorn, the worker (`run_worker`), Caddy and a cloudflared quick tunnel,
   each with its log in `.demo/run/`
4. reads the tunnel's address from cloudflared's log
5. runs the smoke check through that address (below)
6. only then draws the QR code for `/app/` and lists the three addresses

The checks are done before anything is started, so a missing build or a changed
key is reported in seconds rather than after ClamAV has been waited for.

The processes read `.env.demo` (never `PILOT_ALLOW_FIXTURES`). Ctrl-C or SIGTERM
stops every process `up.sh` started, each in its own session so gunicorn's
workers go with it. If one of them dies while the demo runs, `up.sh` says which
and stops the rest. It never stops, removes or recreates a container.

### The smoke check

`demo_up.py smoke` prints `ok  <check>` or `FAIL  <check>` for each of these,
through the tunnel's address, and runs them all even when one fails:

| Check | What it proves |
|---|---|
| `app` | `/app/` serves the build's own `index.html` |
| `wasm` | a `.wasm` asset is `application/wasm` and compressed (Cloudflare may re-encode brotli as gzip; either passes) |
| `static` | a collected workspace asset loads from `/static/` |
| `kit` | the kit's three PDFs and the index load from `/demo-kit/` |
| `login` | `/s/` ends at the login page |
| `api` | `/api/v1/registration/options` answers with the seeded building |
| `worker` | the worker process is running |
| `clamav` | ClamAV scans the quotation, the Transfer proof and the notice and finds each clean |

A new tunnel name can take a few seconds to resolve; the check waits up to 90 s
for `/app/` to answer before it starts.

### `/demo-kit/`

Only the demo serves it. `ops/Caddyfile` imports the file named by
`CADDY_EXTRA_ROUTES` and imports nothing when it is unset; `up.sh` sets it to
[`demo-kit.caddy`](demo-kit.caddy), so a Caddy started any other way has no
`/demo-kit/`.

## Tests

`tests/ops/test_demo_reset.py` and `tests/ops/test_demo_up.py` run `reset.sh` and
`up.sh` against stand-ins for `docker`, `flutter`, `manage.py`, gunicorn, the
worker, Caddy, cloudflared and ClamAV; `tests/ops/test_demo_smoke.py` runs the
smoke check against a stand-in front door; `tests/ops/test_demo_up_helpers.py`
covers the other helpers in `demo_up.py` (tunnel address, kit site, ClamAV wait,
the QR code); `tests/ops/test_demo_env.py` covers the environment file and
fingerprints. None needs Docker. `tests/ops/test_caddyfile.py` runs the real
Caddyfile, including `/demo-kit/`, when a `caddy` binary is available.

Not covered by tests: a real phone on mobile data scanning the QR code, which is
the last item of the device checklist above.
