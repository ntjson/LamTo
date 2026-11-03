# LamTo

**From a resident's photo to a verifiable Maintenance Fund expense.**

![Django 5.2](https://img.shields.io/badge/Django-5.2-2f3a8f?style=flat-square)
![Python 3.12+](https://img.shields.io/badge/Python-3.12%2B-2f3a8f?style=flat-square)
![Flutter](https://img.shields.io/badge/Flutter-iOS%20%2B%20Android%20%2B%20Web-2f3a8f?style=flat-square)
![Solidity 0.8.27](https://img.shields.io/badge/Solidity-0.8.27-2f3a8f?style=flat-square)

LamTo is a Vietnamese-first accountability layer for apartment maintenance.
Residents report problems; management records the decision, work, and payment
evidence; and the building publishes an append-only ledger that anyone can
verify. LamTo complements existing property-management and accounting systems.
It does not move or hold money.

## Why it matters

A maintenance complaint and the expense that eventually appears in a building's
fund are usually disconnected. LamTo creates one traceable chain:

```text
report -> triage -> proposal -> Proceed decision -> work -> Settlement -> public ledger
```

AI may suggest a category, urgency, deadline, or duplicate report, but a named
manager always makes the recorded decision, including the Proceed decision on a
spending proposal. Published evidence is never edited
in place; corrections are appended.

## Hackathon demo

1. A resident reports a problem with a photo and location in the Resident app.
2. LamTo proposes a triage result, and a manager accepts or overrides it in the
   Management workspace.
3. The manager publishes a spending proposal with its quotation, then makes the
   Proceed decision. For a case with a proposal, deciding to proceed is what starts the work.
4. The manager publishes progress, completes the work, and files the Transfer
   proof. Filing it settles the proposal and creates the public ledger entry.
5. The resident follows the expense back to the original report and verifies its
   evidence.
6. If published data is changed, LamTo reports `MISMATCH`; the anchored hash held
   by independent Besu nodes remains unchanged.

The key principle is **explain before proving**: people see a plain-language
status first, with hashes and signatures available as technical proof.

## What we built

- A Flutter Resident app, on iOS, Android and the web, for reports, updates,
  ratings, and the public ledger.
- A server-rendered Django Management workspace for triage, cases, proposals, Proceed
  decisions, Settlements, and verification.
- Human-accountable AI triage with manual fallback.
- Private, virus-scanned evidence storage with hash-checked downloads.
- EIP-712 signed evidence anchored to a Solidity `EvidenceRegistry` on a
  four-validator Hyperledger Besu QBFT network.
- An idempotent outbox so a chain outage delays anchoring without losing or
  duplicating records.

```text
Resident app ---> DRF API ----> Django + PostgreSQL
                                    |       |
Management web ---------------------+       +----> MinIO + ClamAV
                                    |
                                    +----> signed outbox
                                               |
                                               v
                                      EvidenceRegistry
                                      Besu QBFT network
```

## Quick start

Prerequisites: Docker, Python 3.12+, and
[`uv`](https://docs.astral.sh/uv/). Flutter stable is only required for the
Resident app.

```bash
# Infrastructure and Python dependencies
docker compose up -d
uv sync

# Local demo environment: load defaults, generate a secret once, and use local signing.
# The secret must stay the same across shells: `migrate` copies it into the
# database, and signed writes fail with "evidence queue authorization is
# invalid" if the server later runs with a different one.
[ -f .env.local ] || echo "SECRET_KEY=$(python -c 'import secrets; print(secrets.token_urlsafe(64))')" > .env.local
set -a
source .env.example
source .env.local
set +a
export DEBUG=1
export EVIDENCE_ANCHORING_BACKEND=disabled

# Database and synthetic demo data
POSTGRES_USER=lamto_owner POSTGRES_PASSWORD=lamto-owner \
  .venv/bin/python manage.py migrate
PILOT_ALLOW_FIXTURES=1 .venv/bin/python manage.py seed_pilot --fixture

# Management workspace: http://127.0.0.1:8000/s/
.venv/bin/python manage.py runserver 0.0.0.0:8000
```

Start the worker in a second terminal, with the same environment (run the
`set -a` … `set +a` block above there too). It runs triage, the evidence outbox, and the Integrity
observations; without it a new report gets no triage suggestion and no
Integrity observation is recorded.

```bash
.venv/bin/python manage.py run_worker
```

Demo management login:

```text
pilot-management-1@pilot.lamto.test
pilot-test-secret
```

Run the Resident app in another terminal:

```bash
cd app
flutter pub get
flutter run --dart-define=API_BASE_URL=http://10.0.2.2:8000
```

Use `127.0.0.1` instead of `10.0.2.2` for an iOS simulator or Linux desktop.
The resident login is `pilot-resident@pilot.lamto.test` with the same demo
password. The Resident app also runs on the web, served under `/app/`; see
[`app/README.md`](app/README.md) for the web build and the other targets, and
[`ops/single-origin.md`](ops/single-origin.md) for serving it beside the
workspace.

Local mode settles evidence as `LOCAL_SIGNED`. For the on-chain route, see the
Besu devnet in [`chain/besu/`](chain/besu/) (`compose.yaml`,
`generate-network.sh`) and the optional Blockscout chain explorer in
[`chain/explorer/`](chain/explorer/) (not the Evidence explorer).

To run the self-run demo from this laptop, see [`ops/demo/README.md`](ops/demo/README.md).

## Tests

```bash
POSTGRES_USER=lamto_owner POSTGRES_PASSWORD=lamto-owner \
  .venv/bin/python manage.py test lamto
.venv/bin/python -m pytest tests -v
(cd chain && forge test)
(cd app && flutter analyze && flutter test)
```

## Repository map

| Path | Purpose |
|---|---|
| `src/lamto/` | Django domain, API, Management workspace, and workers |
| `app/` | Flutter Resident app (iOS, Android, web) |
| `chain/` | Solidity contract, Foundry tests, and Besu devnet |
| `ops/` | Pilot runbook, single-origin serving, and the demo scripts |
| `docs/api/openapi-v1.yaml` | Resident API contract |
| `tests/` | Cross-cutting and end-to-end tests |

More detail: [pilot runbook](ops/pilot-runbook.md) and
[OpenAPI contract](docs/api/openapi-v1.yaml).

## Status

LamTo is a pre-pilot hackathon prototype. All included buildings, residents,
documents, and amounts are synthetic. Do not use the demo fixtures or credentials
in production.

No license has been published yet.
