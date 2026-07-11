# Accountability MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the approved single-building Accountability MVP from resident maintenance report through independently verified, blockchain-anchored fund publication.

**Architecture:** A Django modular monolith owns operational state in PostgreSQL and serves one responsive, installable PWA with server-rendered templates and small vanilla-JavaScript enhancements. Private files live in S3-compatible storage; database-backed jobs handle AI, email, integrity checks, and a transactional blockchain outbox. A minimal Solidity registry on a four-validator Besu QBFT network verifies stakeholder-controlled signatures and stores evidence hashes only.

**Tech Stack:** Python 3.12+, Django 5.2 LTS, PostgreSQL 17, Django templates, vanilla JavaScript, S3-compatible object storage/MinIO, ClamAV, `django-otp`, Web3.py 7, `eth-account`, Solidity 0.8.27, OpenZeppelin Contracts 5, Foundry, Hyperledger Besu QBFT, Docker Compose, and Django's test runner with Playwright for final browser journeys.

## Global Constraints

- Execution hosts must provide Python 3.12+, Docker with Compose, Foundry (`forge`/`cast`), `curl`, `jq`, `shellcheck`, and WAL-G; verify each tool before Task 1 rather than adding wrapper dependencies.
- The governing specification is `docs/superpowers/specs/2026-07-11-accountability-mvp-design.md`.
- Keep one repository, one Django application deployment, and one worker deployment; do not add microservices, a broker, a workflow engine, a SPA framework, or event sourcing.
- Create an empty `__init__.py` in every Python package directory named below (each Django app plus its `tests`, `migrations`, `models`, `forms`, and `management/commands` directories); the file lists omit repeated initializer entries for readability.
- Store every amount as integer đồng in `BigIntegerField`; never use floating point for money.
- Every privileged read or mutation records actor, active membership, action, target, timestamp, and result.
- Operator creates proposals; Board approves; resident representative co-approves; an eligible Board user publishes.
- Enforce `payment_verifier_id != payment_recorder_id`, `publisher_id != proposal_creator_id`, `publisher_id != proposal_approver_id`, and `publisher_id != payment_recorder_id` server-side.
- The publisher may also verify payment only when all four actor checks pass.
- Exact locally verified signatures authorize normal work even while anchoring is pending; resident-visible verified publication waits for all required chain confirmations, including the publication snapshot.
- Emergency work starts from locally verified Board authorization and records ratification, rejection, or overdue outcome within the fixed 24-hour window.
- Never update or delete verified financial versions, fund entries, published ledger snapshots, audit events, or a blockchain event's signed identity/payload; only outbox delivery status/attempt metadata is mutable. Append corrections and verification observations.
- Every model described below as insert-only must have a PostgreSQL `BEFORE UPDATE OR DELETE` rejection trigger in the same migration, plus a test that covers model save, queryset update, and queryset delete; mutable aggregate pointers and outbox retry fields are the explicit exceptions.
- Store only event identifiers, canonical hashes, prior hashes, organization/signer identifiers, timestamps, and process results on-chain. Never store report text, documents, photos, bank details, or personal profiles on-chain.
- AI receives report text and selected location only; photos remain evidence and are not analyzed in this MVP. Every AI result requires operator confirmation.
- Use private object storage, malware scanning, immutable versions, and distinct hashes for original and redacted documents.
- The platform records external-payment evidence only and never initiates or holds funds.
- No personal billing, vehicle access, native app, offline synchronization, multi-building tenancy, or production-scale HA work belongs in this plan.
- Use `transaction.atomic()` for every state transition coupled to an outbox, fund, or publication record.
- Write the failing test first, observe the expected failure, implement only enough for the test, rerun the focused test, then run the affected app suite before committing.

## Target File Map

```text
pyproject.toml                         Python dependencies and tool metadata
manage.py                              Django command entry point
compose.yaml                           PostgreSQL, MinIO, ClamAV development services
.env.example                           Non-secret local configuration contract
src/lamto/config/                      Django settings, root URLs, ASGI, WSGI
src/lamto/accounts/                    Users, building, organizations, memberships, capabilities, signer wallets, MFA
src/lamto/audit/                       Immutable privileged activity records
src/lamto/documents/                   Private file versions, hashing, scanning, redaction, access checks
src/lamto/maintenance/                 Reports, AI triage, duplicate grouping, cases, work orders
src/lamto/evidence/                    Canonical payloads, signatures, blockchain outbox, chain client, worker
src/lamto/finance/                     Proposals, approvals, emergency flow, acceptance, payment, fund, publication, corrections
src/lamto/notifications/               Durable in-app/email deliveries and worker
src/lamto/web/                         Forms, role-specific views, URLs, templates, PWA assets
chain/src/                             Solidity evidence registry
chain/test/                            Foundry contract tests
chain/script/                          Foundry deployment script
chain/besu/                            QBFT config, generation script, Compose definition
ops/                                   Backup, restore, health, deployment, and pilot runbooks
tests/e2e/                             Cross-role Playwright journeys and adversarial scenarios
```

## Test Fixture Convention

Every `self.make_*`, `self.sign_*`, `self.payment_time()`, `self.valid_payment_payload()`, and `self.replace_test_storage_bytes()` name shown below is test setup, not an unimplemented production API. Define the named helper in the same test module before running that task's failing test. It must return values in the exact left-to-right order shown, create records only through already completed public services after the record under test exists, and use direct ORM creation only for prerequisite users/buildings/memberships. Signature helpers create an `eth_account.Account`, prove address control through the wallet-registration challenge service, build typed data with `build_evidence_typed_data()`, and return the signature plus a fresh deterministic bytes32 event ID. Keep reusable versions in `src/lamto/testing/factories.py`; never copy domain transition logic into factories.

---

### Task 1: Bootstrap Django and the account/organization foundation

**Files:**
- Create: `pyproject.toml`
- Create: `manage.py`
- Create: `compose.yaml`
- Create: `.env.example`
- Modify: `.gitignore`
- Create: `src/lamto/config/settings.py`
- Create: `src/lamto/config/urls.py`
- Create: `src/lamto/config/asgi.py`
- Create: `src/lamto/config/wsgi.py`
- Create: `src/lamto/accounts/apps.py`
- Create: `src/lamto/accounts/managers.py`
- Create: `src/lamto/accounts/models.py`
- Create: `src/lamto/testing/__init__.py`
- Create: `src/lamto/testing/factories.py`
- Create: `src/lamto/accounts/migrations/0001_initial.py`
- Test: `src/lamto/accounts/tests/test_models.py`

**Interfaces:**
- Consumes: none.
- Produces: `User`, `Building`, `Unit`, `Organization`, `OrganizationMembership`, and `ResidentOccupancy` models used by every later task.

- [ ] **Step 1: Create the environment and Django skeleton**

Create `pyproject.toml` with these dependency bounds:

```toml
[build-system]
requires = ["setuptools>=75"]
build-backend = "setuptools.build_meta"

[project]
name = "lamto-accountability"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "Django~=5.2",
  "psycopg[binary]>=3.2,<4",
  "django-otp>=1.6,<2",
  "django-storages[s3]>=1.14,<2",
  "boto3>=1.35,<2",
  "Pillow>=11,<13",
  "argon2-cffi>=23,<26",
  "web3>=7,<8",
  "eth-account>=0.13,<1",
  "gunicorn>=23,<24",
]

[project.optional-dependencies]
dev = [
  "playwright>=1.50,<2",
  "pytest-playwright>=0.6,<1",
  "pytest>=8,<9",
  "pytest-django>=4.9,<5",
]

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
DJANGO_SETTINGS_MODULE = "lamto.config.settings"
pythonpath = ["src"]
testpaths = ["tests"]
```

Create `compose.yaml` with this local-only service definition:

```yaml
services:
  db:
    image: postgres:17
    environment:
      POSTGRES_DB: lamto
      POSTGRES_USER: lamto
      POSTGRES_PASSWORD: lamto
    ports: ["127.0.0.1:5432:5432"]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U lamto -d lamto"]
      interval: 3s
      timeout: 3s
      retries: 20
    volumes: ["postgres-data:/var/lib/postgresql/data"]
  minio:
    image: minio/minio:latest
    command: server /data --console-address :9001
    environment:
      MINIO_ROOT_USER: lamto-local
      MINIO_ROOT_PASSWORD: lamto-local-secret
    ports: ["127.0.0.1:9000:9000", "127.0.0.1:9001:9001"]
    volumes: ["minio-data:/data"]
  minio-init:
    image: minio/mc:latest
    depends_on: [minio]
    entrypoint: >-
      /bin/sh -c "until mc alias set local http://minio:9000 lamto-local lamto-local-secret; do sleep 1; done;
      mc mb --ignore-existing local/lamto-documents;
      mc version enable local/lamto-documents"
  clamav:
    image: clamav/clamav:stable
    ports: ["127.0.0.1:3310:3310"]
    volumes: ["clamav-data:/var/lib/clamav"]
volumes:
  postgres-data:
  minio-data:
  clamav-data:
```

`.env.example` defines `POSTGRES_DB=lamto`, `POSTGRES_USER=lamto`, `POSTGRES_PASSWORD=lamto`, `POSTGRES_HOST=127.0.0.1`, `POSTGRES_PORT=5432`, private-storage endpoint/bucket/access values matching Compose, `CLAMAV_HOST=127.0.0.1`, `CLAMAV_PORT=3310`, `AI_TRIAGE_URL`, `AI_TRIAGE_TOKEN`, chain ID `1337`, RPC URL, contract address, and secret variable names without real secrets.

Run:

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e '.[dev]'
mkdir -p src/lamto
.venv/bin/python -c 'from pathlib import Path; Path("src/lamto/__init__.py").touch()'
.venv/bin/django-admin startproject config src/lamto
mv src/lamto/manage.py manage.py
docker compose up -d
docker compose wait minio-init
curl -fsS http://127.0.0.1:9000/minio/health/live
.venv/bin/python -c 'import socket; s=socket.create_connection(("127.0.0.1", 3310), 3); s.sendall(b"zPING\0"); assert s.recv(16) == b"PONG\0"'
```

Expected: dependencies install, PostgreSQL becomes healthy, the MinIO live check succeeds, bucket initialization exits zero, and ClamAV answers its ping.

- [ ] **Step 2: Write the failing account-model test**

```python
from django.contrib.auth import get_user_model
from django.test import TestCase

from lamto.accounts.models import Building, Organization, OrganizationMembership


class AccountModelTests(TestCase):
    def test_email_user_can_join_one_building_organization(self):
        user = get_user_model().objects.create_user(
            email="board@example.test", password="secret", display_name="Board One"
        )
        building = Building.objects.create(name="Minh An Residence", timezone="Asia/Ho_Chi_Minh")
        organization = Organization.objects.create(
            building=building, name="Management Board", kind=Organization.Kind.BOARD
        )
        membership = OrganizationMembership.objects.create(
            user=user, organization=organization, role=OrganizationMembership.Role.BOARD
        )

        self.assertEqual(user.username, None)
        self.assertEqual(membership.organization.building, building)
```

- [ ] **Step 3: Run the focused test and confirm the expected failure**

Run: `.venv/bin/python manage.py test lamto.accounts.tests.test_models -v 2`

Expected: FAIL because the project and account models do not exist yet.

- [ ] **Step 4: Implement the custom user and organization records**

Create `UserManager` from `BaseUserManager` with `create_user(email, password=None, **fields)` and `create_superuser(email, password, **fields)`. Normalize email, require a non-empty address, set `is_staff` and `is_superuser` for superusers, and save through `self._db`.

Create these models in `src/lamto/accounts/models.py`:

```python
from django.contrib.auth.models import AbstractUser
from django.db import models

from .managers import UserManager


class User(AbstractUser):
    username = None
    email = models.EmailField(unique=True)
    display_name = models.CharField(max_length=160)
    objects = UserManager()
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []


class Building(models.Model):
    name = models.CharField(max_length=200)
    timezone = models.CharField(max_length=64, default="Asia/Ho_Chi_Minh")


class Unit(models.Model):
    building = models.ForeignKey(Building, on_delete=models.PROTECT)
    label = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["building", "label"], name="unit_label_per_building")
        ]


class Organization(models.Model):
    class Kind(models.TextChoices):
        BOARD = "BOARD", "Management Board"
        OPERATOR = "OPERATOR", "Property-management operator"
        RESIDENT_REP = "RESIDENT_REP", "Resident representative"
        AUDITOR = "AUDITOR", "Auditor"
        PLATFORM = "PLATFORM", "Platform provider"

    building = models.ForeignKey(Building, on_delete=models.PROTECT)
    name = models.CharField(max_length=200)
    kind = models.CharField(max_length=24, choices=Kind.choices)


class OrganizationMembership(models.Model):
    class Role(models.TextChoices):
        OPERATOR = "OPERATOR", "Operator"
        MAINTENANCE = "MAINTENANCE", "Maintenance"
        BOARD = "BOARD", "Board"
        RESIDENT_REP = "RESIDENT_REP", "Resident representative"
        AUDITOR = "AUDITOR", "Auditor"
        TECH_ADMIN = "TECH_ADMIN", "Technical administrator"

    user = models.ForeignKey(User, on_delete=models.PROTECT)
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT)
    role = models.CharField(max_length=24, choices=Role.choices)
    active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "organization", "role"], name="membership_once"
            )
        ]


class ResidentOccupancy(models.Model):
    user = models.ForeignKey(User, on_delete=models.PROTECT)
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT)
    active = models.BooleanField(default=True)
```

Enforce the fixed membership map in model validation and a PostgreSQL insert/update trigger: Board role belongs to a Board organization; resident representative to resident-representative; auditor to auditor; technical administrator to platform; operator and maintenance to the property-management operator. This prevents a role label from being attached to an organization with different authority.

Change the generated `manage.py`, `asgi.py`, and `wsgi.py` settings reference from `config.settings` to `lamto.config.settings`. Set `AUTH_USER_MODEL = "accounts.User"`, `TIME_ZONE = "Asia/Ho_Chi_Minh"`, `USE_TZ = True`, `SECRET_KEY` from environment, PostgreSQL database settings from environment variables, and add `lamto.accounts` to `INSTALLED_APPS` before its first migration. Each later task adds its app only after creating that app package.

- [ ] **Step 5: Generate migrations and run the test**

Run:

```bash
.venv/bin/python manage.py makemigrations accounts
.venv/bin/python manage.py migrate
.venv/bin/python manage.py test lamto.accounts.tests.test_models -v 2
```

Expected: one test passes against PostgreSQL.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml manage.py compose.yaml .env.example .gitignore src/lamto/config src/lamto/accounts src/lamto/testing
git commit -m "feat: bootstrap accountability application"
```

---

### Task 2: Add capability checks and immutable audit events

**Files:**
- Modify: `src/lamto/config/settings.py`
- Create: `src/lamto/accounts/capabilities.py`
- Create: `src/lamto/accounts/services.py`
- Modify: `src/lamto/accounts/models.py`
- Create: `src/lamto/accounts/migrations/0002_capability_grants.py`
- Create: `src/lamto/audit/apps.py`
- Create: `src/lamto/audit/models.py`
- Create: `src/lamto/audit/services.py`
- Create: `src/lamto/audit/migrations/0001_initial.py`
- Test: `src/lamto/accounts/tests/test_capabilities.py`
- Test: `src/lamto/audit/tests/test_immutability.py`

**Interfaces:**
- Consumes: `OrganizationMembership` from Task 1.
- Produces: `grant_capability(membership, code) -> CapabilityGrant`, `require_capability(user, membership_id, code) -> OrganizationMembership`, and `record_audit(actor, membership, action, target_type, target_id, result, metadata=None) -> AuditEvent`.

- [ ] **Step 1: Write failing capability and immutability tests**

```python
from django.core.exceptions import PermissionDenied
from django.test import TestCase

from lamto.accounts.capabilities import PROPOSAL_APPROVE
from lamto.accounts.services import grant_capability, require_capability
from lamto.audit.services import record_audit


class CapabilityAndAuditTests(TestCase):
    def test_capability_must_be_explicit_and_audit_is_append_only(self):
        membership = self.make_board_membership()
        with self.assertRaises(PermissionDenied):
            require_capability(membership.user, membership.id, PROPOSAL_APPROVE)

        grant_capability(membership, PROPOSAL_APPROVE)
        self.assertEqual(
            require_capability(membership.user, membership.id, PROPOSAL_APPROVE), membership
        )

        event = record_audit(
            actor=membership.user,
            membership=membership,
            action="proposal.approve",
            target_type="ProposalVersion",
            target_id="42",
            result="allowed",
        )
        event.result = "changed"
        with self.assertRaises(ValueError):
            event.save()
        with self.assertRaises(ValueError):
            event.delete()
```

Use a local `make_board_membership()` helper in the test class that creates one user, building, Board organization, and Board membership.

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `.venv/bin/python manage.py test lamto.accounts.tests.test_capabilities lamto.audit.tests.test_immutability -v 2`

Expected: FAIL because capabilities and audit services do not exist.

- [ ] **Step 3: Implement explicit capability grants**

Add `CapabilityGrant(membership, code)` with a unique `(membership, code)` constraint. Define string constants in `capabilities.py`, including `REPORT_TRIAGE`, `WORK_ASSIGN`, `PROPOSAL_CREATE`, `PROPOSAL_APPROVE`, `EMERGENCY_AUTHORIZE`, `WORK_ACCEPT`, `PAYMENT_RECORD`, `PAYMENT_VERIFY`, `FUND_RECORD`, `FUND_VERIFY`, `LEDGER_PUBLISH`, `CORRECTION_CREATE`, `CORRECTION_APPROVE`, `AUDIT_EXPORT`, and `TECH_ADMIN`.

Define and test a fixed organization-kind allowlist so grants cannot erase role separation: operator-only for triage, assignment, proposal creation, and correction creation; Board-only for emergency authorization, work acceptance, payment record/verify, fund record/verify, and publication; Board or resident-representative for proposal/correction approval with the service selecting the required stage; auditor-only for export; and platform-only for technical administration. `grant_capability()` must reject an unknown code or an organization kind outside that map. Every domain service must check both the capability and the expected organization kind; a mistaken database grant must never turn an operator into a Board actor.

Implement:

```python
from django.core.exceptions import PermissionDenied

from .capabilities import ALLOWED_ORGANIZATION_KINDS
from .models import CapabilityGrant, OrganizationMembership


def grant_capability(membership: OrganizationMembership, code: str) -> CapabilityGrant:
    if membership.organization.kind not in ALLOWED_ORGANIZATION_KINDS.get(code, set()):
        raise PermissionDenied(code)
    grant, _ = CapabilityGrant.objects.get_or_create(membership=membership, code=code)
    return grant


def require_capability(user, membership_id: int, code: str) -> OrganizationMembership:
    membership = OrganizationMembership.objects.filter(
        id=membership_id, user=user, active=True
    ).first()
    if (
        membership is None
        or membership.organization.kind not in ALLOWED_ORGANIZATION_KINDS.get(code, set())
        or not CapabilityGrant.objects.filter(
            membership=membership, code=code
        ).exists()
    ):
        raise PermissionDenied(code)
    return membership
```

- [ ] **Step 4: Implement immutable audit events**

Add `lamto.audit` to `INSTALLED_APPS`. Create `AuditEvent` with actor, membership, action, target type/ID, JSON metadata, result, and `created_at`. Its `save()` allows inserts only and its `delete()` always raises `ValueError`. Add a PostgreSQL `BEFORE UPDATE OR DELETE` trigger in `0001_initial.py` using `migrations.RunSQL` so queryset updates and raw application SQL cannot mutate audit rows.

Implement `record_audit()` as one `AuditEvent.objects.create` call populated from its seven arguments; never hide audit failure inside `try/except`.

- [ ] **Step 5: Run the focused and app tests**

Run:

```bash
.venv/bin/python manage.py makemigrations accounts audit
.venv/bin/python manage.py migrate
.venv/bin/python manage.py test lamto.accounts lamto.audit -v 2
```

Expected: capability denial, grant, and append-only tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/lamto/accounts src/lamto/audit src/lamto/config/settings.py
git commit -m "feat: enforce capabilities and immutable audit"
```

---

### Task 3: Store immutable original and redacted documents

**Files:**
- Create: `src/lamto/documents/apps.py`
- Create: `src/lamto/documents/models.py`
- Create: `src/lamto/documents/scanner.py`
- Create: `src/lamto/documents/services.py`
- Create: `src/lamto/documents/access.py`
- Create: `src/lamto/documents/migrations/0001_initial.py`
- Test: `src/lamto/documents/tests/test_versions.py`
- Test: `src/lamto/documents/tests/test_access.py`
- Test: `src/lamto/documents/tests/test_quarantine.py`
- Modify: `src/lamto/config/settings.py`

**Interfaces:**
- Consumes: `User`, `OrganizationMembership`, capabilities, and audit recording.
- Produces: `create_document_version(document, uploaded_file, variant, uploader, scanner) -> DocumentVersion`, `add_redacted_copy(original, uploaded_file, uploader, scanner) -> DocumentVersion`, `quarantine_upload(uploaded_file, uploader, reason) -> QuarantinedUpload`, and `authorize_download(user, membership_id, version) -> None`.

- [ ] **Step 1: Write failing hashing and redaction tests**

```python
import hashlib
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from lamto.documents.models import Document, DocumentVersion
from lamto.documents.services import add_redacted_copy, create_document_version


class DocumentVersionTests(TestCase):
    def test_original_and_redacted_bytes_get_distinct_immutable_hashes(self):
        uploader, building = self.make_operator_and_building()
        document = Document.objects.create(building=building, kind=Document.Kind.QUOTATION)
        original = create_document_version(
            document,
            SimpleUploadedFile("quote.pdf", b"private-original"),
            DocumentVersion.Variant.ORIGINAL,
            uploader,
            scanner=lambda _: True,
        )
        redacted = add_redacted_copy(
            original,
            SimpleUploadedFile("quote-redacted.pdf", b"resident-copy"),
            uploader,
            scanner=lambda _: True,
        )

        self.assertEqual(original.sha256, hashlib.sha256(b"private-original").hexdigest())
        self.assertNotEqual(original.sha256, redacted.sha256)
        self.assertEqual(redacted.redacts_id, original.id)
        original.sha256 = "0" * 64
        with self.assertRaises(ValueError):
            original.save()
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `.venv/bin/python manage.py test lamto.documents.tests.test_versions -v 2`

Expected: FAIL because document records and services do not exist.

- [ ] **Step 3: Implement immutable file versions**

Add `lamto.documents` to `INSTALLED_APPS`.

Create `Document` with building, kinds `REPORT_PHOTO`, `BEFORE_PHOTO`, `AFTER_PHOTO`, `QUOTATION`, `INVOICE`, `ACCEPTANCE_REPORT`, `PAYMENT_PROOF`, `CONTRACT`, and `CORRECTION_EVIDENCE`. Create `DocumentVersion` with document, sequential version, `ORIGINAL`/`REDACTED` variant, unique private storage key, provider object-version ID, filename, content type, byte size, SHA-256, scan status, uploader, optional `redacts`, and timestamp. Add unique `(document, version)`; allow multiple immutable redacted versions of one original so a redaction error is corrected by appending, never replacing. Lock the parent document while allocating the next version number, store each upload under a never-reused key, and install a database trigger that rejects update/delete of version rows.

Implement `create_document_version()` by enforcing a configurable 20 MiB limit, allowing only PDF/JPEG/PNG for the document kind, checking file signatures (and Pillow verification for images), then streaming the upload into a `SpooledTemporaryFile`, updating `hashlib.sha256`, and running the supplied scanner on the complete temporary file before one private-storage write. A clean scan writes the immutable version. A type/size violation records rejected metadata without retaining bytes; a positive malware result or scanner failure writes the bytes and hash under a non-downloadable quarantine prefix. Both paths append `QuarantinedUpload`, audit the reason, raise without creating an attachable `DocumentVersion`, and have focused tests. Make version/quarantine rows insert-only.

Configure Django's `STORAGES["private"]` for S3-compatible storage using environment variables; tests override it with `FileSystemStorage` in a temporary directory.

- [ ] **Step 4: Implement ClamAV and access checks**

In `scanner.py`, implement `scan_with_clamav(file_obj) -> bool` using the ClamAV INSTREAM protocol over the configured TCP socket; return `True` only for an `OK` response and raise `DocumentScanUnavailable` on connection/protocol failure.

In `access.py`, allow:

- residents to download redacted versions attached to published entries;
- residents to download their own report photos through the report relationship;
- operators to access documents in their building workflows;
- resident representatives to access originals attached to proposals they review;
- auditors to access originals/redacted copies in their building;
- maintenance to access only report/before/after files on assigned work.

Every allowed and denied download calls `record_audit()`. An allowed download streams the exact stored provider version ID and verifies its SHA-256 before returning bytes; unavailable or mismatched content is denied and surfaced as an integrity action item.

- [ ] **Step 5: Run document tests**

Run:

```bash
.venv/bin/python manage.py makemigrations documents
.venv/bin/python manage.py migrate
.venv/bin/python manage.py test lamto.documents -v 2
```

Expected: hashing, immutable version, redaction-link, and access-matrix tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/lamto/documents src/lamto/config/settings.py
git commit -m "feat: add immutable private documents"
```

---

### Task 4: Accept resident reports and process live AI triage safely

**Files:**
- Create: `src/lamto/maintenance/apps.py`
- Create: `src/lamto/maintenance/models.py`
- Create: `src/lamto/maintenance/reporting.py`
- Create: `src/lamto/maintenance/candidates.py`
- Create: `src/lamto/maintenance/ai.py`
- Create: `src/lamto/maintenance/management/commands/process_triage.py`
- Create: `src/lamto/maintenance/migrations/0001_initial.py`
- Test: `src/lamto/maintenance/tests/test_reporting.py`
- Test: `src/lamto/maintenance/tests/test_ai_fallback.py`
- Modify: `src/lamto/config/settings.py`

**Interfaces:**
- Consumes: resident occupancy, private report-photo versions, audit service.
- Produces: `BuildingLocation`, `submit_report(resident, unit, text, location, photo_versions) -> IssueReport`, `find_duplicate_candidates(report, limit=5) -> QuerySet[IssueReport]`, `process_triage_job(job_id) -> TriageJob`, and a documented JSON AI endpoint contract.

- [ ] **Step 1: Write the failing persistence-before-AI test**

```python
from django.test import TestCase

from lamto.maintenance.models import IssueReport, TriageJob
from lamto.maintenance.reporting import submit_report


class ReportSubmissionTests(TestCase):
    def test_submission_commits_report_and_pending_triage_job(self):
        resident, unit, location = self.make_resident_unit_and_location()
        report = submit_report(resident, unit, "Elevator shakes", location, [])

        self.assertEqual(IssueReport.objects.get(id=report.id).text, "Elevator shakes")
        self.assertEqual(TriageJob.objects.get(report=report).status, TriageJob.Status.PENDING)
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `.venv/bin/python manage.py test lamto.maintenance.tests.test_reporting -v 2`

Expected: FAIL because maintenance models and submission service do not exist.

- [ ] **Step 3: Implement report-first submission**

Add `lamto.maintenance` to `INSTALLED_APPS`.

Create hierarchical `BuildingLocation(building, parent, name, active)` with a unique sibling name and a deterministic `path_label`. Create `IssueReport` with reporter, unit, text, selected-location FK plus immutable path snapshot, status, and timestamp; `ReportPhoto` linking report to document version; `TriageJob` with `PENDING`, `PROCESSING`, `SUCCEEDED`, and `NEEDS_MANUAL` statuses; and `TriageSuggestion` with category, interpreted location, urgency, integer confidence percent, duplicate report IDs, department, deadline minutes, raw response, provider request ID, validation metadata, and elapsed time.

Implement `submit_report()` inside one transaction: validate active occupancy, non-empty text, an active location in the same building, and photo versions belonging to the same building; create report/photo links, create one pending triage job, and append an audit event. Do not call AI inside the transaction or request path.

- [ ] **Step 4: Implement the strict AI HTTP contract and manual fallback**

Enable PostgreSQL `pg_trgm` in the initial maintenance migration. `find_duplicate_candidates()` selects unresolved reports in the same building, annotates `TrigramSimilarity("text", report.text)`, excludes the current report, orders by similarity descending, and returns at most five rows with similarity at least `0.2`.

POST to `AI_TRIAGE_URL` using the standard library, a short configured timeout, and bearer authentication from `AI_TRIAGE_TOKEN`, with a JSON body containing `report_id`, `text`, the selected-location path snapshot, and the five candidate IDs/text/location snapshots. Require HTTPS outside local/test mode. Accept only a JSON object with these exact keys and types:

```json
{
  "category": "Elevator",
  "interpreted_location": "Building B / Lift 2",
  "urgency": "HIGH",
  "confidence_percent": 87,
  "requires_manual_review": false,
  "duplicate_report_ids": [17, 21],
  "department": "Maintenance",
  "deadline_minutes": 240,
  "provider_request_id": "req-123"
}
```

Validate urgency against `LOW`, `MEDIUM`, `HIGH`, `EMERGENCY`; require confidence from 0 through 100 and a boolean `requires_manual_review`; ensure duplicate IDs were supplied as candidates; and require positive deadline minutes. Provider-declared manual review, timeout, transport error, invalid JSON, or schema failure sets the job to `NEEDS_MANUAL`, records the reason/timing, and preserves the report. Store confidence for pilot measurement but do not invent an accuracy cutoff or give the score workflow authority. The worker command claims pending rows with `select_for_update(skip_locked=True)` so concurrent workers do not duplicate calls.

- [ ] **Step 5: Test success and failure paths**

Run:

```bash
.venv/bin/python manage.py makemigrations maintenance
.venv/bin/python manage.py migrate
.venv/bin/python manage.py test lamto.maintenance.tests.test_reporting lamto.maintenance.tests.test_ai_fallback -v 2
```

Expected: report persists, valid response creates a suggestion, and transport/schema failures route to manual triage.

- [ ] **Step 6: Commit**

```bash
git add src/lamto/maintenance src/lamto/config/settings.py
git commit -m "feat: add resident reports and safe AI triage"
```

---

### Task 5: Confirm triage, group duplicates, and run work orders

**Files:**
- Modify: `src/lamto/maintenance/models.py`
- Create: `src/lamto/maintenance/triage.py`
- Create: `src/lamto/maintenance/workorders.py`
- Create: `src/lamto/maintenance/migrations/0002_cases_and_workorders.py`
- Test: `src/lamto/maintenance/tests/test_cases.py`
- Test: `src/lamto/maintenance/tests/test_workorders.py`

**Interfaces:**
- Consumes: `IssueReport`, `TriageSuggestion`, operator capabilities, document versions.
- Produces: `confirm_triage(report, operator, category, urgency, location, department, deadline_minutes) -> MaintenanceCase`, `group_report(case, report, operator) -> CaseReport`, `create_work_order(case, operator, assignee, requires_spending) -> WorkOrder`, `start_work_order(work_order, maintenance_user) -> WorkOrder`, and `complete_work_order(work_order, maintenance_user, cause, result, before_versions, after_versions) -> WorkOrder`.

- [ ] **Step 1: Write the failing duplicate-preservation and paid-work gate tests**

```python
from django.core.exceptions import PermissionDenied
from django.test import TestCase

from lamto.maintenance.triage import confirm_triage, group_report
from lamto.maintenance.workorders import create_work_order, start_work_order


class CaseAndWorkOrderTests(TestCase):
    def test_grouping_preserves_reports_and_paid_work_needs_authorization(self):
        operator = self.make_operator_with_triage_capability()
        report_one, report_two = self.make_two_reports()
        case = confirm_triage(
            report_one, operator, category="Elevator", urgency="HIGH",
            location=report_one.selected_location,
            department="Maintenance", deadline_minutes=240,
        )
        group_report(case, report_two, operator)
        self.assertEqual(set(case.reports.values_list("id", flat=True)), {report_one.id, report_two.id})

        assignee = self.make_maintenance_user()
        work = create_work_order(case, operator, assignee, requires_spending=True)
        with self.assertRaises(PermissionDenied):
            start_work_order(work, assignee)
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `.venv/bin/python manage.py test lamto.maintenance.tests.test_cases -v 2`

Expected: FAIL because case/work-order records and services do not exist.

- [ ] **Step 3: Implement cases and grouping**

Add `TriageDecision`, `MaintenanceCase`, and explicit through model `CaseReport`. A report may belong to only one active case. `confirm_triage()` requires `REPORT_TRIAGE`, requires an active same-building `BuildingLocation`, records both the operator decision and differences from the AI suggestion, creates a case, links the first report, and audits the action. `group_report()` locks both records, preserves the original report, links it once, and audits the grouping.

- [ ] **Step 4: Implement work-order transitions**

Add `WorkOrder` statuses `ASSIGNED`, `IN_PROGRESS`, `AWAITING_ACCEPTANCE`, `ACCEPTED`, `CLOSED`, and `CANCELLED`; fields for assignee, priority, deadline, `requires_spending`, authorization state (`NOT_REQUIRED`, `PENDING`, `AUTHORIZED`), emergency/drill flags, cause, result, and timestamps. Add immutable `WorkUpdate` rows for progress and before/after document links.

`start_work_order()` must lock the row, require the assigned user, allow `NOT_REQUIRED` or `AUTHORIZED`, reject `PENDING`, set start time/status, and audit. `complete_work_order()` requires cause, result, and at least one before and after image before moving to `AWAITING_ACCEPTANCE`.

Represent a pre-authorization diagnostic inspection as a separate `requires_spending=False` work order on the same case. Never flip a started diagnostic order into paid repair; create a new paid work order so expenditure authorization cannot be bypassed.

- [ ] **Step 5: Run maintenance tests**

Run:

```bash
.venv/bin/python manage.py makemigrations maintenance
.venv/bin/python manage.py migrate
.venv/bin/python manage.py test lamto.maintenance -v 2
```

Expected: grouping, authorization gate, assignment, progress, and completion-evidence tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/lamto/maintenance
git commit -m "feat: add maintenance cases and work orders"
```

---

### Task 6: Add canonical evidence payloads, stakeholder wallets, and the transactional outbox

**Files:**
- Modify: `src/lamto/accounts/models.py`
- Create: `src/lamto/accounts/migrations/0003_signer_wallets.py`
- Create: `src/lamto/evidence/apps.py`
- Create: `src/lamto/evidence/models.py`
- Create: `src/lamto/evidence/canonical.py`
- Create: `src/lamto/evidence/signatures.py`
- Create: `src/lamto/evidence/services.py`
- Create: `src/lamto/evidence/migrations/0001_initial.py`
- Test: `src/lamto/evidence/tests/test_signatures.py`
- Test: `src/lamto/evidence/tests/test_outbox.py`
- Modify: `src/lamto/config/settings.py`

**Interfaces:**
- Consumes: memberships and audit service.
- Produces: `canonical_bytes(payload) -> bytes`, `payload_hash(payload) -> str`, `build_evidence_typed_data(event_id, event_type, payload_hash_hex, previous_hash_hex) -> dict`, `recover_signer(typed_data, signature) -> str`, `begin_wallet_registration(membership) -> dict`, `register_wallet(membership, checksum_address, proof_signature) -> SignerWallet`, `revoke_wallet(wallet, authorizing_membership) -> SignerWallet`, and `queue_signed_event(event_id, event_type, payload, previous_hash, membership, signature) -> BlockchainOutboxEvent`.

- [ ] **Step 1: Write the failing deterministic-signature test**

```python
from eth_account import Account
from eth_account.messages import encode_typed_data
from django.test import TestCase

from lamto.evidence.canonical import payload_hash
from lamto.evidence.signatures import build_evidence_typed_data, recover_signer


class EvidenceSignatureTests(TestCase):
    def test_canonical_payload_and_eip712_signature_recover_same_wallet(self):
        wallet = Account.create()
        payload = {"amount_vnd": 18500000, "proposal_version": 2}
        typed = build_evidence_typed_data(
            event_id="0x" + "11" * 32,
            event_type=1,
            payload_hash_hex="0x" + payload_hash(payload),
            previous_hash_hex="0x" + "00" * 32,
        )
        signature = Account.sign_message(
            encode_typed_data(full_message=typed), wallet.key
        ).signature.hex()

        self.assertEqual(recover_signer(typed, signature).lower(), wallet.address.lower())
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `.venv/bin/python manage.py test lamto.evidence.tests.test_signatures -v 2`

Expected: FAIL because evidence helpers do not exist.

- [ ] **Step 3: Implement deterministic hashing and EIP-712 data**

Add `lamto.evidence` to `INSTALLED_APPS`.

`canonical_bytes()` must accept only dictionaries/lists, NFC-normalized strings, integers, booleans, and null; use UTF-8 JSON with sorted keys, compact separators, `ensure_ascii=False`; and reject floats, decimals, datetimes, bytes, and non-string object keys. Service payload builders convert timestamps to UTC RFC 3339 with exactly six fractional digits and `Z`, identifiers/hashes to lowercase strings, and money to integer đồng before canonicalization. `payload_hash()` returns lowercase SHA-256 hex.

`build_evidence_typed_data()` must return the exact EIP-712 domain/message used by the Solidity contract:

```python
def build_evidence_typed_data(event_id, event_type, payload_hash_hex, previous_hash_hex):
    return {
        "types": {
            "EIP712Domain": [
                {"name": "name", "type": "string"},
                {"name": "version", "type": "string"},
                {"name": "chainId", "type": "uint256"},
                {"name": "verifyingContract", "type": "address"},
            ],
            "Evidence": [
                {"name": "eventId", "type": "bytes32"},
                {"name": "payloadHash", "type": "bytes32"},
                {"name": "previousHash", "type": "bytes32"},
                {"name": "eventType", "type": "uint8"},
            ],
        },
        "primaryType": "Evidence",
        "domain": {
            "name": "LamToEvidence",
            "version": "1",
            "chainId": settings.BLOCKCHAIN_CHAIN_ID,
            "verifyingContract": settings.EVIDENCE_CONTRACT_ADDRESS,
        },
        "message": {
            "eventId": event_id,
            "payloadHash": payload_hash_hex,
            "previousHash": previous_hash_hex,
            "eventType": event_type,
        },
    }
```

- [ ] **Step 4: Implement wallet registration and outbox queueing**

Add `SignerWallet(membership, address, active, registered_at, revoked_at)` with normalized checksum address and one active wallet per membership. Add `BlockchainOutboxEvent` with event ID stored as a unique lowercase `0x`-prefixed 64-hex-character `CharField(max_length=66)`, type code, canonical payload JSON/hash, previous hash, signature, signer wallet, status (`PENDING`, `SUBMITTED`, `CONFIRMED`, `FAILED`, `MISMATCH`), attempts, next-attempt/lease timestamps, transaction hash, error, timestamps, and chain-confirmed block. Its migration trigger rejects changes to event ID/type, payload/hash, previous hash, signer, or signature while allowing delivery status, receipt, error, lease, and retry metadata to advance.

Define and never renumber these `EvidenceType(models.IntegerChoices)` values because Solidity and historical evidence depend on them:

```python
class EvidenceType(models.IntegerChoices):
    PROPOSAL_CREATED = 1, "Proposal created"
    BOARD_APPROVAL = 2, "Board approval"
    REPRESENTATIVE_APPROVAL = 3, "Representative approval"
    EMERGENCY_AUTHORIZATION = 4, "Emergency authorization"
    EMERGENCY_OUTCOME = 5, "Emergency outcome"
    WORK_ACCEPTANCE = 6, "Work acceptance"
    PAYMENT_RECORDED = 7, "Payment recorded"
    PAYMENT_VERIFIED = 8, "Payment verified"
    PUBLICATION_SNAPSHOT = 9, "Publication snapshot"
    CORRECTION = 10, "Correction"
    FUND_ENTRY = 11, "Fund entry"
```

Use the preceding event's canonical `payload_hash`, prefixed with `0x`, as `previous_hash`; use zero bytes only for the first evidence event in an aggregate. Do not depend on a transaction hash, because local signatures must be verifiable before anchoring. Apply this deterministic linkage:

| Event | Previous evidence hash | Required hashes inside its canonical payload |
|---|---|---|
| Proposal version 1 | Zero, or emergency authorization when already present | Work/case/report snapshot and quotation original/redacted hashes |
| Proposal revision | Prior proposal-version event | New exact snapshot and quotation hashes |
| Board decision | Current proposal-version event | Proposal hash, decision, actor organization |
| Representative decision | Board-decision event | Proposal hash, decision, actor organization |
| Emergency authorization | Zero when it precedes a proposal | Work order, reason, available estimate, drill flag |
| Emergency outcome | Emergency-authorization event | Ratified/rejected result, reason, deadline result, drill flag |
| Work acceptance | Representative decision for normal work; latest proposal event for emergency work | Actual cost plus invoice and acceptance-report original/redacted hashes |
| Payment recorded | Work-acceptance event | Bank-reference digest, external status/time, proof original/redacted hashes |
| Payment verified | Payment-recorded event | Exact payment hash and verification result |
| Publication snapshot | Payment-verification event | Every applicable prerequisite event hash, emergency outcome, resident payload, and document hashes |
| Fund opening/inflow | Prior verified source event for that fund, otherwise zero | Entry type, amount, source-document hashes, maker/checker identities |
| Correction creation/decisions/snapshot | Original publication, then prior correction stage | Original link, replacement hashes, decisions, and publisher snapshot |

Emergency outcome and execution evidence can be parallel descendants of the authorization; the publication payload must name and hash both branches. The registry does not infer workflow order: PostgreSQL services enforce the gates, while the stored hashes make those exact decisions independently checkable.

Implement `begin_wallet_registration(membership) -> typed_challenge` with a single-use, expiring server nonce and `register_wallet(membership, checksum_address, proof_signature)` that recovers the same address from that challenge before activation. Implement `revoke_wallet(wallet, authorizing_membership)` with same-organization authorization, immutable registration/revocation history, and a chain signer-authorization request consumed by Task 11. Restrict wallet activation to roles that can sign pilot evidence. The server never accepts, stores, logs, exports, or backs up a stakeholder private key. `queue_signed_event()` must recover the signer, require it to match the active wallet, create the outbox row inside the caller's existing transaction, and audit the signed action. Duplicate event ID with identical hash returns the existing row; duplicate ID with another hash raises `EvidenceConflict`.

- [ ] **Step 5: Run evidence tests**

Run:

```bash
.venv/bin/python manage.py makemigrations accounts evidence
.venv/bin/python manage.py migrate
.venv/bin/python manage.py test lamto.evidence -v 2
```

Expected: canonicalization rejects floats, signature recovery matches, wallet mismatch fails, and duplicate event IDs are idempotent/conflict-safe.

- [ ] **Step 6: Commit**

```bash
git add src/lamto/accounts src/lamto/evidence src/lamto/config/settings.py
git commit -m "feat: add signed blockchain outbox"
```

---

### Task 7: Create immutable expenditure proposal versions

**Files:**
- Create: `src/lamto/finance/apps.py`
- Create: `src/lamto/finance/models/__init__.py`
- Create: `src/lamto/finance/models/proposals.py`
- Create: `src/lamto/finance/proposals.py`
- Create: `src/lamto/finance/migrations/0001_initial.py`
- Test: `src/lamto/finance/tests/test_proposals.py`
- Modify: `src/lamto/config/settings.py`

**Interfaces:**
- Consumes: `WorkOrder`, quotation `DocumentVersion`, `PROPOSAL_CREATE`, `canonical_bytes()`, and `queue_signed_event()`.
- Produces: `create_proposal(work_order, creator_membership) -> Proposal` and `submit_proposal_version(proposal, amount_vnd, contractor_name, quotation_versions, signature, event_id) -> ProposalVersion`.

- [ ] **Step 1: Write the failing immutable-version test**

```python
from django.test import TestCase

from lamto.finance.proposals import create_proposal, submit_proposal_version


class ProposalVersionTests(TestCase):
    def test_submitted_version_is_signed_immutable_and_tied_to_work_order(self):
        operator, work_order, quotation, signature, event_id = self.make_signed_proposal_inputs()
        proposal = create_proposal(work_order, operator)
        version = submit_proposal_version(
            proposal=proposal,
            amount_vnd=18_500_000,
            contractor_name="Company X",
            quotation_versions=[quotation],
            signature=signature,
            event_id=event_id,
        )

        self.assertEqual(version.number, 1)
        self.assertEqual(version.amount_vnd, 18_500_000)
        self.assertEqual(version.outbox_event.event_id, event_id)
        version.amount_vnd = 1
        with self.assertRaises(ValueError):
            version.save()
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `.venv/bin/python manage.py test lamto.finance.tests.test_proposals -v 2`

Expected: FAIL because finance proposal models and services do not exist.

- [ ] **Step 3: Implement proposal aggregates and constraints**

Add `lamto.finance` to `INSTALLED_APPS`.

Create mutable aggregate `Proposal` with work order, creator membership, mode (`NORMAL`, `EMERGENCY`), status (`DRAFT`, `IN_REVIEW`, `NORMAL_AUTHORIZED`, `EMERGENCY_EVIDENCE`, `REJECTED`), and current version. Mode is fixed from the work order when the aggregate is created and cannot later change. Create insert-only `ProposalVersion` with sequential number, positive integer amount, contractor name, purpose copied from the case/work order, immutable snapshot JSON/hash, creator signature/wallet, quotation many-to-many through `ProposalDocument`, and outbox event. Enforce one proposal per work order and unique `(proposal, number)`.

Add a `CheckConstraint(condition=models.Q(amount_vnd__gt=0), name="proposal_amount_positive")`.

- [ ] **Step 4: Implement signed submission and revision**

`submit_proposal_version()` must:

1. lock proposal/work order;
2. require `PROPOSAL_CREATE` and the operator organization kind;
3. require at least one safe original quotation plus its safe redacted copy;
4. build a snapshot containing work-order/case/report IDs, amount, contractor, fund code `MAINTENANCE`, purpose, and exact quotation hashes;
5. verify the creator signature and queue `EvidenceType.PROPOSAL_CREATED` in the same transaction;
6. insert the immutable version and set normal proposals to `IN_REVIEW` or emergency proposals to `EMERGENCY_EVIDENCE`; emergency evidence never masquerades as an exact-version normal approval;
7. point `Proposal.current_version` to the new row; older rows remain unchanged and are derived as superseded;
8. set a normal work order's authorization state to `PENDING`; preserve authorization already granted by a valid emergency Board signature.

An edit always calls the same service to create the next numbered version; there is no update endpoint for submitted versions.

- [ ] **Step 5: Run proposal tests**

Run:

```bash
.venv/bin/python manage.py makemigrations finance
.venv/bin/python manage.py migrate
.venv/bin/python manage.py test lamto.finance.tests.test_proposals -v 2
```

Expected: first version, revision, positive amount, quotation requirements, signature, and immutability tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/lamto/finance src/lamto/config/settings.py
git commit -m "feat: add immutable expenditure proposals"
```

---

### Task 8: Enforce fixed approvals and local normal-work authorization

**Files:**
- Create: `src/lamto/finance/models/approvals.py`
- Modify: `src/lamto/finance/models/__init__.py`
- Create: `src/lamto/finance/approvals.py`
- Create: `src/lamto/finance/migrations/0002_approval_decisions.py`
- Test: `src/lamto/finance/tests/test_approvals.py`
- Create: `src/lamto/web/static/web/wallet-signing.js`

**Interfaces:**
- Consumes: proposal versions, Board/representative capabilities, signer wallets, evidence outbox.
- Produces: `decide_proposal(version, membership, decision, reason, signature, event_id) -> ApprovalDecision` and `proposal_is_locally_authorized(version) -> bool`.

- [ ] **Step 1: Write the failing local-authorization/outbox test**

```python
from django.test import TestCase

from lamto.evidence.models import BlockchainOutboxEvent
from lamto.finance.approvals import decide_proposal, proposal_is_locally_authorized


class ProposalApprovalTests(TestCase):
    def test_two_local_signatures_authorize_work_while_chain_is_pending(self):
        version, board, representative = self.make_version_and_approvers()
        board_signature, board_event = self.sign_decision(version, board, "APPROVE")
        rep_signature, rep_event = self.sign_decision(version, representative, "APPROVE")

        decide_proposal(version, board, "APPROVE", "Within budget", board_signature, board_event)
        decide_proposal(version, representative, "APPROVE", "Evidence checked", rep_signature, rep_event)

        version.refresh_from_db()
        version.proposal.work_order.refresh_from_db()
        self.assertTrue(proposal_is_locally_authorized(version))
        self.assertEqual(version.proposal.work_order.authorization_state, "AUTHORIZED")
        self.assertEqual(
            set(BlockchainOutboxEvent.objects.filter(event_id__in=[board_event, rep_event]).values_list("status", flat=True)),
            {"PENDING"},
        )
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `.venv/bin/python manage.py test lamto.finance.tests.test_approvals -v 2`

Expected: FAIL because approval records and services do not exist.

- [ ] **Step 3: Implement ordered, signed decisions**

Create insert-only `ApprovalDecision` with version, stage (`BOARD`, `RESIDENT_REP`), decision (`APPROVE`, `REJECT`), reason, membership, wallet, signature, outbox event, and timestamp. Enforce one decision per stage/version.

`decide_proposal()` must lock the current normal-mode version, require Board first and representative second, verify the exact proposal snapshot hash in the signed payload, queue `EvidenceType.BOARD_APPROVAL` or `EvidenceType.REPRESENTATIVE_APPROVAL` atomically, and audit both approval and rejection. Either rejection sets only the mutable proposal aggregate to `REJECTED`; the proposal version and prior decision remain insert-only and unchanged.

After both approvals, set proposal status `NORMAL_AUTHORIZED` and work-order authorization state `AUTHORIZED` even when outbox events remain pending. Expose the derived verification label `Pending blockchain anchoring` until all version/approval events are confirmed.

- [ ] **Step 4: Invalidate old approvals on revision**

Add tests and service checks showing that decisions belong only to their immutable version. Creating normal version 2 makes version 1 non-current by derivation, sets the aggregate to `IN_REVIEW`, and returns work authorization to `PENDING`; no decision rows are copied and no version row is updated.

Add `wallet-signing.js` with `window.ethereum.request({method: "eth_signTypedData_v4", params: [account, JSON.stringify(typedData)]})`; return the signature to the form endpoint. The server remains authoritative and rejects address/membership mismatch.

- [ ] **Step 5: Run finance approval and maintenance gate tests**

Run: `.venv/bin/python manage.py test lamto.finance.tests.test_approvals lamto.maintenance.tests.test_workorders -v 2`

Expected: ordered approvals, rejections, revision invalidation, pending-anchor label, and locally authorized work start pass.

- [ ] **Step 6: Commit**

```bash
git add src/lamto/finance src/lamto/web/static/web/wallet-signing.js
git commit -m "feat: enforce fixed proposal approvals"
```

---

### Task 9: Implement emergency authorization and 24-hour outcomes

**Files:**
- Create: `src/lamto/finance/models/emergencies.py`
- Modify: `src/lamto/finance/models/__init__.py`
- Create: `src/lamto/finance/emergencies.py`
- Create: `src/lamto/finance/management/commands/mark_overdue_ratifications.py`
- Create: `src/lamto/finance/migrations/0003_emergency_flow.py`
- Test: `src/lamto/finance/tests/test_emergencies.py`

**Interfaces:**
- Consumes: work orders, `EMERGENCY_AUTHORIZE`, representative membership, signed evidence outbox.
- Produces: `request_emergency(work_order, operator_membership, reason, drill=False) -> WorkOrder`, `authorize_emergency(work_order, board_membership, estimate_vnd, signature, event_id, now) -> EmergencyAuthorization`, `decide_emergency(authorization, representative_membership, decision, reason, signature, event_id) -> EmergencyRatification`, and `mark_overdue_ratifications(now) -> int`.

- [ ] **Step 1: Write the failing emergency-start test**

```python
from datetime import timedelta
from django.test import TestCase
from django.utils import timezone

from lamto.finance.emergencies import authorize_emergency, decide_emergency, request_emergency
from lamto.maintenance.workorders import start_work_order


class EmergencyFlowTests(TestCase):
    def test_board_signature_allows_start_before_chain_and_rep_records_outcome(self):
        work, operator, board, representative, maintenance = self.make_emergency_actors()
        request_emergency(work, operator, "Active water leak")
        authorization_signature, auth_event = self.sign_emergency(work, board)
        authorization = authorize_emergency(
            work, board, 9_200_000,
            authorization_signature, auth_event, now=timezone.now(),
        )

        started = start_work_order(work, maintenance)
        self.assertEqual(started.status, "IN_PROGRESS")
        self.assertEqual(started.verification_label, "Pending blockchain anchoring")

        decision_signature, decision_event = self.sign_ratification(authorization, representative, "REJECT")
        outcome = decide_emergency(
            authorization, representative, "REJECT", "Insufficient estimate detail",
            decision_signature, decision_event,
        )
        self.assertLessEqual(outcome.decided_at, authorization.authorized_at + timedelta(hours=24))
        self.assertEqual(outcome.decision, "REJECT")
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `.venv/bin/python manage.py test lamto.finance.tests.test_emergencies -v 2`

Expected: FAIL because emergency records and services do not exist.

- [ ] **Step 3: Implement emergency authorization**

Add emergency-request fields to `WorkOrder`: requesting operator membership, mandatory safety reason, requested time, and irreversible drill flag. `request_emergency()` requires the operator organization and `WORK_ASSIGN`, runs before Board authorization, and audits the request. Once requested, the emergency/drill identity cannot be cleared or converted.

Create insert-only `EmergencyAuthorization` with work order, copied mandatory reason, optional positive estimate, Board membership/wallet/signature, authorized time, ratification deadline, drill flag, outbox event, and persistent label. `authorize_emergency()` requires a prior request plus `EMERGENCY_AUTHORIZE`, verifies the signed payload including the request reason and drill flag, atomically queues `EMERGENCY_AUTHORIZATION`, marks the work order `AUTHORIZED`, and sets deadline exactly `authorized_at + timedelta(hours=24)`.

- [ ] **Step 4: Implement ratified, rejected, and overdue outcomes**

Create insert-only `EmergencyRatification` with one of `RATIFIED`, `REJECTED`, `OVERDUE`, membership/signature/outbox event when a human decides, reason, and timestamp, with one terminal outcome per authorization. Representative decisions require the matching organization and signature, must arrive by the deadline, and queue `EMERGENCY_OUTCOME`. `mark_overdue_ratifications()` locks expired unanswered authorizations and appends an unsigned system-derived `OVERDUE` row idempotently; it never fabricates a stakeholder signature. A late human attempt is denied and audited without replacing `OVERDUE`. The later publisher-signed publication snapshot includes and anchors that exact overdue fact.

Every view/export must render `Emergency`; drill records additionally render `Emergency drill`. Rejected and overdue outcomes remain publishable only under those exact labels after all other evidence gates.

- [ ] **Step 5: Run emergency tests**

Run:

```bash
.venv/bin/python manage.py makemigrations finance
.venv/bin/python manage.py migrate
.venv/bin/python manage.py test lamto.finance.tests.test_emergencies -v 2
```

Expected: authorization, immediate start, 24-hour decision, overdue append, pending anchor, and persistent labels pass.

- [ ] **Step 6: Commit**

```bash
git add src/lamto/finance
git commit -m "feat: add emergency authorization and ratification"
```

---

### Task 10: Build and test the minimal Solidity evidence registry

**Files:**
- Create: `chain/foundry.toml`
- Create: `chain/remappings.txt`
- Create: `chain/src/EvidenceRegistry.sol`
- Create: `chain/test/EvidenceRegistry.t.sol`
- Create: `chain/script/DeployEvidenceRegistry.s.sol`
- Create: `chain/.gitignore`

**Interfaces:**
- Consumes: the EIP-712 domain and `Evidence` fields defined in Task 6.
- Produces: `EvidenceRegistry.recordEvidence(eventId, payloadHash, previousHash, eventType, signer, signature)`, `EvidenceRegistry.records(eventId)`, `setAuthorizedSigner(signer, authorized)`, ABI, and deployment address.

- [ ] **Step 1: Initialize Foundry and install reviewed cryptography**

Run:

```bash
mkdir -p chain
cd chain
forge init --force --no-commit
forge install OpenZeppelin/openzeppelin-contracts@v5.4.0 --no-git
rm -f src/Counter.sol test/Counter.t.sol script/Counter.s.sol
```

Expected: `forge build` succeeds with OpenZeppelin Contracts 5.x available under `lib/`.

- [ ] **Step 2: Write the failing contract tests**

Create tests for: authorized signature accepted, unauthorized signer rejected, altered payload rejected, duplicate event ID rejected, zero IDs/hashes and unknown event types rejected, and existing record readable. The central test must sign the digest returned by `hashEvidence()`:

```solidity
function testRecordsOneAuthorizedEvidenceEvent() public {
    bytes32 eventId = keccak256("event-1");
    bytes32 payloadHash = sha256(bytes("payload"));
    bytes32 previousHash = bytes32(0);
    bytes32 digest = registry.hashEvidence(eventId, payloadHash, previousHash, 1);
    (uint8 v, bytes32 r, bytes32 s) = vm.sign(signerKey, digest);
    bytes memory signature = abi.encodePacked(r, s, v);

    registry.recordEvidence(eventId, payloadHash, previousHash, 1, signer, signature);
    (bytes32 storedHash, bytes32 storedPrevious, uint8 storedType, address storedSigner, uint64 recordedAt) = registry.records(eventId);

    assertEq(storedHash, payloadHash);
    assertEq(storedPrevious, previousHash);
    assertEq(storedType, 1);
    assertEq(storedSigner, signer);
    assertGt(recordedAt, 0);
}
```

- [ ] **Step 3: Run the tests and confirm they fail**

Run: `cd chain && forge test -vv`

Expected: FAIL because `EvidenceRegistry` does not exist.

- [ ] **Step 4: Implement the complete evidence registry**

```solidity
// SPDX-License-Identifier: MIT
pragma solidity 0.8.27;

import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";
import {EIP712} from "@openzeppelin/contracts/utils/cryptography/EIP712.sol";
import {ECDSA} from "@openzeppelin/contracts/utils/cryptography/ECDSA.sol";

contract EvidenceRegistry is EIP712, Ownable {
    bytes32 public constant EVIDENCE_TYPEHASH = keccak256(
        "Evidence(bytes32 eventId,bytes32 payloadHash,bytes32 previousHash,uint8 eventType)"
    );

    struct Record {
        bytes32 payloadHash;
        bytes32 previousHash;
        uint8 eventType;
        address signer;
        uint64 recordedAt;
    }

    mapping(address => bool) public authorizedSigners;
    mapping(bytes32 => Record) public records;

    event SignerAuthorizationChanged(address indexed signer, bool authorized);
    event EvidenceRecorded(
        bytes32 indexed eventId,
        bytes32 payloadHash,
        bytes32 previousHash,
        uint8 eventType,
        address indexed signer
    );

    constructor(address initialOwner) EIP712("LamToEvidence", "1") Ownable(initialOwner) {}

    function setAuthorizedSigner(address signer, bool authorized) external onlyOwner {
        require(signer != address(0), "zero signer");
        authorizedSigners[signer] = authorized;
        emit SignerAuthorizationChanged(signer, authorized);
    }

    function hashEvidence(
        bytes32 eventId,
        bytes32 payloadHash,
        bytes32 previousHash,
        uint8 eventType
    ) public view returns (bytes32) {
        return _hashTypedDataV4(
            keccak256(abi.encode(EVIDENCE_TYPEHASH, eventId, payloadHash, previousHash, eventType))
        );
    }

    function recordEvidence(
        bytes32 eventId,
        bytes32 payloadHash,
        bytes32 previousHash,
        uint8 eventType,
        address signer,
        bytes calldata signature
    ) external {
        require(eventId != bytes32(0), "zero event");
        require(payloadHash != bytes32(0), "zero payload");
        require(eventType >= 1 && eventType <= 11, "unknown event type");
        require(records[eventId].recordedAt == 0, "duplicate event");
        require(authorizedSigners[signer], "unauthorized signer");
        require(ECDSA.recover(hashEvidence(eventId, payloadHash, previousHash, eventType), signature) == signer, "bad signature");
        records[eventId] = Record(payloadHash, previousHash, eventType, signer, uint64(block.timestamp));
        emit EvidenceRecorded(eventId, payloadHash, previousHash, eventType, signer);
    }
}
```

- [ ] **Step 5: Add the deployment script and rerun tests**

`DeployEvidenceRegistry.s.sol` reads `OWNER_ADDRESS`, broadcasts from `PRIVATE_KEY`, deploys the contract, and logs its address. Run:

```bash
cd chain
forge fmt --check
forge test -vv
forge build
```

Expected: all contract tests pass and ABI exists at `chain/out/EvidenceRegistry.sol/EvidenceRegistry.json`.

- [ ] **Step 6: Commit**

```bash
git add chain
git commit -m "feat: add signed evidence registry contract"
```

---

### Task 11: Run four Besu validators and process outbox events idempotently

**Files:**
- Create: `chain/besu/qbftConfigFile.json`
- Create: `chain/besu/generate-network.sh`
- Create: `chain/besu/compose.yaml`
- Create: `chain/besu/.gitignore`
- Create: `src/lamto/evidence/chain.py`
- Create: `src/lamto/evidence/worker.py`
- Create: `src/lamto/evidence/management/commands/process_blockchain_outbox.py`
- Create: `src/lamto/evidence/management/commands/sync_signer_authorizations.py`
- Test: `src/lamto/evidence/tests/test_worker.py`
- Test: `src/lamto/evidence/tests/test_chain_integration.py`
- Modify: `.env.example`
- Modify: `src/lamto/config/settings.py`

**Interfaces:**
- Consumes: contract ABI/address, relayer secret, pending outbox rows.
- Produces: `EvidenceRegistryClient.find(event) -> ChainRecord | None`, `EvidenceRegistryClient.submit(event) -> str`, `EvidenceRegistryClient.set_signer(address, authorized) -> str`, `process_outbox_event(event_id) -> BlockchainOutboxEvent`, and signer registration/revocation synchronization.

- [ ] **Step 1: Write the failing idempotent worker test**

```python
from django.test import TestCase

from lamto.evidence.models import BlockchainOutboxEvent
from lamto.evidence.worker import process_outbox_event


class BlockchainWorkerTests(TestCase):
    def test_existing_matching_chain_event_confirms_without_resubmit(self):
        event = self.make_pending_outbox_event()
        client = self.fake_chain_client(existing_hash=event.payload_hash)

        processed = process_outbox_event(event.id, client=client)

        self.assertEqual(processed.status, BlockchainOutboxEvent.Status.CONFIRMED)
        self.assertEqual(client.submit_calls, 0)
```

- [ ] **Step 2: Run the worker test and confirm it fails**

Run: `.venv/bin/python manage.py test lamto.evidence.tests.test_worker -v 2`

Expected: FAIL because the chain client and worker do not exist.

- [ ] **Step 3: Generate a four-validator QBFT development network**

Use this config, matching current Besu QBFT generation syntax:

```json
{
  "genesis": {
    "config": {
      "chainId": 1337,
      "berlinBlock": 0,
      "qbft": {"blockperiodseconds": 2, "epochlength": 30000, "requesttimeoutseconds": 4}
    },
    "nonce": "0x0",
    "timestamp": "0x58ee40ba",
    "gasLimit": "0x1fffffffffffff",
    "difficulty": "0x1",
    "mixHash": "0x63746963616c2062797a616e74696e65206661756c7420746f6c6572616e6365",
    "coinbase": "0x0000000000000000000000000000000000000000",
    "alloc": {
      "f39fd6e51aad88f6f4ce6ab8827279cfffb92266": {"balance": "0x3635c9adc5dea00000"}
    }
  },
  "blockchain": {"nodes": {"generate": true, "count": 4}}
}
```

`generate-network.sh` runs `hyperledger/besu:25.7.0 operator generate-blockchain-config --config-file=qbftConfigFile.json --to=networkFiles --private-key-file-name=key`, copies generated validator keys into fixed ignored `Node-1` through `Node-4` data paths, and writes the Node-1 enode URL into ignored `.env.network`. Map and label the validators deterministically as Node 1 Management Board, Node 2 property-management operator, Node 3 resident representative, and Node 4 auditor. `compose.yaml` starts all four validators on one private Docker network, exposes Node-1 JSON-RPC only on localhost `8545`, and enables `ETH,NET,QBFT` APIs. Never commit generated validator keys, `.env.network`, or data directories.

Run:

```bash
cd chain/besu
bash generate-network.sh
docker compose up -d
curl -s -X POST http://127.0.0.1:8545 -H 'Content-Type: application/json' --data '{"jsonrpc":"2.0","method":"net_peerCount","params":[],"id":1}'
```

Expected: peer count reaches `0x3`.

- [ ] **Step 4: Implement Web3.py lookup, submission, and receipt handling**

`EvidenceRegistryClient` loads the ABI artifact and checksum contract address, calls `records(event_id)` before submission, builds `recordEvidence(event_id, payload_hash, previous_hash, event_type, signer, signature)`, signs the relayer transaction from environment-injected `BLOCKCHAIN_RELAYER_PRIVATE_KEY`, sends raw bytes, and waits up to 60 seconds for a receipt. A receipt with status other than `1` is failure.

Serialize relayer nonce allocation/submission with a PostgreSQL advisory lock shared by worker replicas, read the pending-chain nonce inside that lock, and release it immediately after `send_raw_transaction`; receipt waiting happens after release. The relayer key never signs stakeholder evidence, only pays/submits the already signed call.

`process_outbox_event()` must:

1. atomically claim one due row with `select_for_update(skip_locked=True)`, set a short `SUBMITTED` lease, then release the database transaction before network I/O;
2. query the chain by stable event ID on every attempt, including expired-lease recovery;
3. if chain already holds the event, compare payload/previous/type/signer and mark `CONFIRMED` or `MISMATCH` without submitting;
4. otherwise submit and store transaction hash/receipt status in a second short transaction;
5. on timeout/network failure increment attempts and return to `PENDING` with bounded exponential retry time;
6. never create another event ID or signature;
7. append an audit/health signal on mismatch.

`sync_signer_authorizations` reads audited pending wallet registration/revocation requests, uses the same nonce-lock pattern for the separate owner account, calls owner-only `setAuthorizedSigner`, waits for a successful receipt, and records the chain transaction. Revocation prevents new signatures but never changes historical records. The contract-owner key and relayer key are separate injected secrets.

- [ ] **Step 5: Run unit and live-chain integration checks**

Run:

```bash
.venv/bin/python manage.py test lamto.evidence -v 2
cd chain
PRIVATE_KEY=0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80 OWNER_ADDRESS=0xf39fd6e51aad88f6f4ce6ab8827279cfffb92266 forge script script/DeployEvidenceRegistry.s.sol:DeployEvidenceRegistry --rpc-url http://127.0.0.1:8545 --broadcast
cd ..
export EVIDENCE_CONTRACT_ADDRESS="$(jq -r '.transactions[] | select(.transactionType == "CREATE") | .contractAddress' chain/broadcast/DeployEvidenceRegistry.s.sol/1337/run-latest.json | head -1)"
BLOCKCHAIN_CONTRACT_OWNER_PRIVATE_KEY=0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80 CHAIN_INTEGRATION=1 .venv/bin/python manage.py test lamto.evidence.tests.test_chain_integration -v 2
```

The integration test creates disposable database actors, proves/registers a stakeholder test wallet, synchronizes its chain authorization with the test owner key, creates a separate ephemeral relayer account and funds it from the owner only for this local test, queues one signed event, processes it twice through the real RPC client, asserts one chain record/transaction, and revokes the disposable signer in teardown. Skip it unless `CHAIN_INTEGRATION=1`.

Expected: unit tests pass, the contract deploys, one signed fixture event confirms, and the second processing call does not submit it twice.

- [ ] **Step 6: Commit**

```bash
git add chain/besu src/lamto/evidence .env.example src/lamto/config/settings.py
git commit -m "feat: anchor evidence on managed Besu network"
```

---

### Task 12: Accept completed work and enforce payment maker-checker separation

**Files:**
- Create: `src/lamto/finance/models/execution.py`
- Modify: `src/lamto/finance/models/__init__.py`
- Create: `src/lamto/finance/acceptance.py`
- Create: `src/lamto/finance/payments.py`
- Create: `src/lamto/finance/migrations/0004_acceptance_and_payment.py`
- Test: `src/lamto/finance/tests/test_acceptance.py`
- Test: `src/lamto/finance/tests/test_payments.py`

**Interfaces:**
- Consumes: completed work orders, invoice/acceptance/payment document versions, Board capabilities, evidence outbox.
- Produces: `accept_work(work_order, membership, actual_cost_vnd, invoice_original, invoice_redacted, acceptance_original, acceptance_redacted, signature, event_id) -> AcceptanceRecord`, `record_payment(acceptance, membership, bank_reference, amount_vnd, external_status, completed_at, proof_original, proof_redacted, signature, event_id) -> PaymentEvidence`, and `verify_payment(payment, membership, decision, reason, signature, event_id) -> PaymentVerification`.

- [ ] **Step 1: Write the failing payment-separation test**

```python
from django.core.exceptions import PermissionDenied
from django.test import TestCase

from lamto.finance.acceptance import accept_work
from lamto.finance.payments import record_payment, verify_payment


class PaymentMakerCheckerTests(TestCase):
    def test_payment_recorder_cannot_verify_own_evidence(self):
        (
            work,
            board_recorder,
            invoice_original,
            invoice_redacted,
            acceptance_original,
            acceptance_redacted,
            proof_original,
            proof_redacted,
        ) = self.make_completed_work_inputs()
        acceptance_signature, acceptance_event = self.sign_acceptance(work, board_recorder)
        acceptance = accept_work(
            work, board_recorder, 18_500_000,
            invoice_original, invoice_redacted, acceptance_original, acceptance_redacted,
            acceptance_signature, acceptance_event,
        )
        payment_signature, payment_event = self.sign_payment(acceptance, board_recorder)
        payment = record_payment(
            acceptance, board_recorder, "BANK-2026-001", 18_500_000, "COMPLETED",
            self.payment_time(), proof_original, proof_redacted, payment_signature, payment_event,
        )

        verification_signature, verification_event = self.sign_payment_verification(payment, board_recorder)
        with self.assertRaises(PermissionDenied):
            verify_payment(
                payment, board_recorder, "VERIFIED", "Matches accepted cost",
                verification_signature, verification_event,
            )
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `.venv/bin/python manage.py test lamto.finance.tests.test_payments -v 2`

Expected: FAIL because acceptance/payment records and services do not exist.

- [ ] **Step 3: Implement acceptance and actual-cost confirmation**

Create insert-only `AcceptanceRecord` with work order, positive actual cost, invoice original/redacted versions, acceptance-report original/redacted versions, Board confirmer, signature/outbox, and timestamp. The operator uploads and redacts these versions through Task 3 before Board review. `accept_work()` requires work status `AWAITING_ACCEPTANCE`, a Board organization with `WORK_ACCEPT`, safe same-building required documents, and a signature over the exact actual cost, cause/result, before/after image hashes, and invoice/acceptance original/redacted hashes. It queues `WORK_ACCEPTANCE`, marks work `ACCEPTED`, and audits atomically.

- [ ] **Step 4: Implement payment recording and independent verification**

Create insert-only `PaymentEvidence` with acceptance, normalized unique bank reference, exact amount, external status (`COMPLETED`, `FAILED`, `REVERSED`), external completion time, payment-proof original/redacted versions, recorder, signature/outbox, and timestamp. Require a Board organization with `PAYMENT_RECORD`, safe same-building proof versions, amount equal to accepted actual cost, and a completion time for `COMPLETED`.

Create insert-only `PaymentVerification` with payment, verifier, decision (`VERIFIED`, `REJECTED`), reason, signature/outbox, and timestamp. `verify_payment()` requires a Board organization with `PAYMENT_VERIFY`, `verifier.user_id != payment.recorder.user_id`, and a signature over the entire payment-evidence hash plus decision/reason. Add application validation and a database trigger that rejects equal actor IDs across the payment relationship. Only `VERIFIED` satisfies publication; a rejection remains visible and immutable. The actual-cost confirmer may record payment; the recorder may never verify it.

- [ ] **Step 5: Run acceptance/payment tests**

Run:

```bash
.venv/bin/python manage.py makemigrations finance
.venv/bin/python manage.py migrate
.venv/bin/python manage.py test lamto.finance.tests.test_acceptance lamto.finance.tests.test_payments -v 2
```

Expected: document/amount gates, accepted transition, bank-reference uniqueness, recorder/verifier separation, and signed outbox tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/lamto/finance
git commit -m "feat: add acceptance and payment maker-checker"
```

---

### Task 13: Publish through an anchored snapshot and post the Maintenance Fund atomically

**Files:**
- Create: `src/lamto/finance/models/ledger.py`
- Modify: `src/lamto/finance/models/__init__.py`
- Create: `src/lamto/finance/fund.py`
- Create: `src/lamto/finance/publication.py`
- Create: `src/lamto/finance/management/commands/finalize_publications.py`
- Create: `src/lamto/finance/migrations/0005_fund_and_publication.py`
- Test: `src/lamto/finance/tests/test_fund.py`
- Test: `src/lamto/finance/tests/test_publication.py`

**Interfaces:**
- Consumes: normal-authorized or emergency-evidenced proposal, acceptance, verified payment, confirmed prerequisite evidence, redacted documents.
- Produces: `record_fund_source(fund, entry_type, amount_vnd, evidence_original, evidence_redacted, recorder, signature, event_id) -> MaintenanceFundEntry`, `verify_fund_source(entry, verifier, signature, event_id) -> FundEntryVerification`, `prepare_publication(proposal, publisher, signature, event_id) -> PublicationSnapshot`, `finalize_publication(snapshot_id) -> PublishedLedgerEntry`, and `fund_balance(building_id, verified_only=True) -> int`.

- [ ] **Step 1: Write the failing two-stage publication test**

```python
from django.test import TestCase

from lamto.finance.models import MaintenanceFundEntry, PublishedLedgerEntry
from lamto.finance.publication import finalize_publication, prepare_publication


class PublicationTests(TestCase):
    def test_publication_waits_for_its_own_chain_confirmation_then_posts_once(self):
        proposal, publisher, signature, event_id = self.make_ready_proposal_and_publisher()
        snapshot = prepare_publication(proposal, publisher, signature, event_id)

        self.assertFalse(PublishedLedgerEntry.objects.filter(proposal=proposal).exists())
        self.assertFalse(MaintenanceFundEntry.objects.filter(proposal=proposal).exists())

        snapshot.outbox_event.status = "CONFIRMED"
        snapshot.outbox_event.save(update_fields=["status", "confirmed_at"])
        first = finalize_publication(snapshot.id)
        second = finalize_publication(snapshot.id)

        self.assertEqual(first.id, second.id)
        self.assertEqual(MaintenanceFundEntry.objects.filter(proposal=proposal).count(), 1)
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `.venv/bin/python manage.py test lamto.finance.tests.test_publication -v 2`

Expected: FAIL because fund/publication records and services do not exist.

- [ ] **Step 3: Implement the append-only Maintenance Fund**

Create one `MaintenanceFund` per building. Create insert-only `MaintenanceFundEntry` types `OPENING_BALANCE`, `INFLOW`, `OUTFLOW`, `REVERSAL`, and `REPLACEMENT`, with signed integer `amount_vnd`, evidence original/redacted links and hashes, recorder/outbox for manually entered sources, optional proposal/publication/correction link, and unique source key. Create a separate insert-only `FundEntryVerification` with entry, different Board verifier, signature/outbox, and timestamp. Positive values increase balance and negative values decrease it; validate the allowed sign for each entry type. `fund_balance(verified_only=True)` sums only opening/inflow rows whose maker and checker events are confirmed plus finalized publication/correction entries; a staff-only pending-reconciliation query may include unverified sources. Never read or maintain a stored balance field.

`record_fund_source()` accepts only opening/inflow types, requires a Board organization with `FUND_RECORD`, requires safe same-building original/redacted evidence, and atomically queues signed evidence. `verify_fund_source()` requires a different Board user with `FUND_VERIFY`, creates the separate verification row, queues signed verification, and exposes opening/inflow entries to residents only after both events confirm. Outflows are created only by `finalize_publication()`.

- [ ] **Step 4: Implement publisher eligibility and immutable publication snapshots**

Create insert-only `PublicationSnapshot` with proposal, canonical resident payload/hash, publisher, signature, and outbox event. Derive pending/confirmed state from the mutable outbox row; never mutate the snapshot. Create insert-only `PublicationGateFailure` with proposal, gate code, expected/actual hashes where applicable, severity, actor, and timestamp. Create insert-only `PublishedLedgerEntry` with snapshot, work/case/proposal/payment references, actual cost, contractor, published time, and unique proposal.

`prepare_publication()` must require:

- accepted work and a `VERIFIED` payment decision whose evidence status is `COMPLETED`;
- for normal mode, the current proposal version has Board and resident-representative approvals; for emergency mode, the 24-hour decision deadline has passed, a valid Board emergency authorization plus a terminal ratified/rejected/overdue outcome exists, and the submitted proposal is treated as evidence rather than mislabeled as normal approval;
- all required original/redacted documents;
- all prerequisite financial/document outbox events confirmed;
- a Board organization with `LEDGER_PUBLISH`;
- publisher not proposal creator, Board proposal approver, or payment recorder;
- publisher may equal payment verifier;
- immutable resident payload containing report/case/work/proposal IDs, proposed/actual amounts, contractor, approval actors/results, document hashes, payment verification, and emergency outcome.

Before accepting the publisher signature, stream and recompute every required stored document hash, match it to its immutable version and the corresponding confirmed event payload, and freeze publication with a `PublicationGateFailure`, audit event, and Board/auditor action item on any unavailable or mismatched byte stream.

Reject every drill-mode proposal before snapshot creation. For a real emergency, retain `Emergency` plus exactly one of `Ratified`, `Ratification rejected`, or `Ratification overdue` in the snapshot and resident entry; rejected/overdue must never render as approved.

It verifies the publisher signature and atomically queues `PUBLICATION_SNAPSHOT`; it does not expose a ledger entry or post the fund.

Enforce the publisher comparisons by user identity, not membership-row identity, in both the service and a PostgreSQL `BEFORE INSERT` trigger on `PublicationSnapshot`. The trigger must reject a publisher matching the proposal creator, Board proposal approver, or payment recorder even if an application path is bypassed.

`finalize_publication()` locks the snapshot, requires its outbox event `CONFIRMED`, and atomically creates one negative outflow and one ledger entry using unique constraints/get-or-create semantics.

- [ ] **Step 5: Run fund/publication tests**

Run:

```bash
.venv/bin/python manage.py makemigrations finance
.venv/bin/python manage.py migrate
.venv/bin/python manage.py test lamto.finance.tests.test_fund lamto.finance.tests.test_publication -v 2
```

Expected: source maker-checker, publisher actor rules, pending publication, confirmed finalization, idempotency, and computed balance tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/lamto/finance
git commit -m "feat: publish verified maintenance fund entries"
```

---

### Task 14: Append corrections and integrity observations without rewriting history

**Files:**
- Create: `src/lamto/finance/models/corrections.py`
- Modify: `src/lamto/finance/models/__init__.py`
- Create: `src/lamto/finance/corrections.py`
- Create: `src/lamto/finance/integrity.py`
- Create: `src/lamto/finance/management/commands/verify_integrity.py`
- Create: `src/lamto/finance/migrations/0006_corrections_and_observations.py`
- Test: `src/lamto/finance/tests/test_corrections.py`
- Test: `src/lamto/finance/tests/test_integrity.py`

**Interfaces:**
- Consumes: published entries, proposal-style signatures/approvals, document storage, fund/publication services.
- Produces: `create_correction(entry, operator, reason, replacement_payload, document_versions, signature, event_id) -> Correction`, `decide_correction(correction, membership, stage, decision, reason, signature, event_id) -> CorrectionDecision`, `prepare_correction_publication(correction, publisher, signature, event_id) -> CorrectionPublicationSnapshot`, `finalize_correction_publication(snapshot_id) -> Correction`, and `verify_published_entry(entry_id) -> VerificationObservation`.

- [ ] **Step 1: Write the failing tamper-observation test**

```python
from django.test import TestCase

from lamto.finance.integrity import verify_published_entry


class IntegrityTests(TestCase):
    def test_changed_document_appends_mismatch_without_mutating_entry(self):
        entry, version = self.make_published_entry()
        original_published_at = entry.published_at
        self.replace_test_storage_bytes(version.storage_key, b"tampered-copy")

        observation = verify_published_entry(entry.id)
        entry.refresh_from_db()

        self.assertEqual(observation.result, "MISMATCH")
        self.assertEqual(entry.published_at, original_published_at)
        self.assertEqual(entry.effective_integrity_status, "MISMATCH")
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `.venv/bin/python manage.py test lamto.finance.tests.test_integrity -v 2`

Expected: FAIL because integrity observations do not exist.

- [ ] **Step 3: Implement append-only integrity observations**

Create insert-only `VerificationObservation` with published entry, result (`VERIFIED`, `MISMATCH`, `UNAVAILABLE`), checked hashes/chain IDs, details, and timestamp. `verify_published_entry()` streams every published document, recomputes SHA-256, checks chain records through `EvidenceRegistryClient`, appends one observation, and alerts Board/auditor on mismatch. `PublishedLedgerEntry.effective_integrity_status` derives from the latest observation; it never updates the entry.

`verify_integrity` accepts `--all` and Django's standard `--database ALIAS`; when run against a restored database it reads the selected alias and writes the drill report outside that restored database.

- [ ] **Step 4: Implement correction versions and reversing fund entries**

Create insert-only `Correction`, `CorrectionDecision`, and `CorrectionPublicationSnapshot`. Require the operator organization plus correction capability and reason/replacement evidence; Board approval then representative co-approval; a Board publisher different from the correction's Board approver and still satisfying the original publication actor exclusions; and chain confirmation of correction/prior/decision/publisher hashes before resident exposure.

`finalize_correction_publication()` is idempotent and runs only after its snapshot event confirms. When a financial amount changes, that transaction creates a reversing entry for the original outflow and a replacement outflow, each linked to the correction, then exposes the correction beside the original resident entry. It does not alter the original entry, fund entry, documents, approvals, or chain event.

- [ ] **Step 5: Run correction and integrity tests**

Run:

```bash
.venv/bin/python manage.py makemigrations finance
.venv/bin/python manage.py migrate
.venv/bin/python manage.py test lamto.finance.tests.test_corrections lamto.finance.tests.test_integrity -v 2
.venv/bin/python manage.py verify_integrity --all
```

Expected: mismatch observation, unchanged original, correction approvals, prior-hash linkage, reversing/replacement entries, and reconciled balance pass.

- [ ] **Step 6: Commit**

```bash
git add src/lamto/finance
git commit -m "feat: append corrections and integrity observations"
```

---

### Task 15: Build the resident mobile-first PWA

**Files:**
- Modify: `src/lamto/maintenance/models.py`
- Create: `src/lamto/maintenance/ratings.py`
- Create: `src/lamto/maintenance/migrations/0003_completion_ratings.py`
- Test: `src/lamto/maintenance/tests/test_ratings.py`
- Create: `src/lamto/web/apps.py`
- Create: `src/lamto/web/forms/resident.py`
- Create: `src/lamto/web/views/resident.py`
- Create: `src/lamto/web/urls.py`
- Create: `src/lamto/web/templates/web/base.html`
- Create: `src/lamto/web/templates/web/resident/home.html`
- Create: `src/lamto/web/templates/web/resident/report_form.html`
- Create: `src/lamto/web/templates/web/resident/report_list.html`
- Create: `src/lamto/web/templates/web/resident/report_detail.html`
- Create: `src/lamto/web/templates/web/resident/work_rating_form.html`
- Create: `src/lamto/web/templates/web/resident/ledger_list.html`
- Create: `src/lamto/web/templates/web/resident/ledger_detail.html`
- Create: `src/lamto/web/templates/web/resident/account.html`
- Create: `src/lamto/web/static/web/app.css`
- Create: `src/lamto/web/static/web/manifest.webmanifest`
- Create: `src/lamto/web/static/web/service-worker.js`
- Test: `src/lamto/web/tests/test_resident_views.py`
- Modify: `src/lamto/config/urls.py`
- Modify: `src/lamto/config/settings.py`

**Interfaces:**
- Consumes: report submission, resident occupancy, published ledger/fund queries, document access service.
- Produces: `rate_completed_work(resident, work_order, score, comment) -> CompletionRating`, resident routes `home`, `report-create`, `report-list`, `report-detail`, `work-rate`, `ledger-list`, `ledger-detail`, `account`, and an installable static PWA shell.

- [ ] **Step 1: Write failing resident visibility tests**

```python
from django.test import TestCase
from django.urls import reverse


class ResidentViewTests(TestCase):
    def test_resident_sees_own_case_and_published_redacted_ledger_only(self):
        resident, own_report, published_entry, unpublished_entry = self.make_resident_view_fixtures()
        self.client.force_login(resident)

        home = self.client.get(reverse("web:resident-home"))
        ledger = self.client.get(reverse("web:ledger-list"))

        self.assertContains(home, own_report.text)
        self.assertContains(ledger, str(published_entry.actual_cost_vnd))
        self.assertNotContains(ledger, str(unpublished_entry.actual_cost_vnd))
        self.assertContains(ledger, "Record verified")
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `.venv/bin/python manage.py test lamto.web.tests.test_resident_views -v 2`

Expected: FAIL because resident routes/templates do not exist.

- [ ] **Step 3: Implement resident forms, queries, and routes**

Add `lamto.web` to `INSTALLED_APPS` and include `lamto.web.urls` from the root URL configuration.

Use Django `ModelForm`/plain `Form` classes with server-side validation. The report form accepts text, an active `BuildingLocation` from the resident's building, and image files; it creates document versions first, then calls `submit_report()`. Resident queries filter reports through active occupancy/user and ledger entries through finalized publication only. Home shows the verified opening/current balance, period inflows/outflows, active reports, and recent verified spending. Account initially shows profile and session-security links without exposing staff-role data; Task 16 extends it with notification preferences and unread notices.

Ledger detail must show report/case/work/proposal links, proposed and actual amount, contractor, Board/representative decisions, payment verification actor/time, emergency outcome, redacted documents, transaction IDs, correction chain, and effective integrity status. It never exposes originals or private bank details.

Add `CompletionRating` with resident, accepted/closed work order, integer score constrained to 1-5, optional 500-character comment, timestamp, and unique `(resident, work_order)`. `rate_completed_work()` requires the resident to own a report in the linked case and the work to be accepted/closed; the report-detail page exposes the rating form only when eligible.

- [ ] **Step 4: Implement accessible templates and PWA assets**

Use semantic landmarks, real labels, keyboard-visible focus, text plus icon status, minimum 44px primary touch targets, responsive CSS, and no color-only meaning. Resident bottom navigation contains Home, Report, My issues, Ledger, and Account. Register `service-worker.js` from `base.html`.

The service worker caches only versioned static assets and the offline shell; it does not cache authenticated HTML, API responses, documents, or mutation requests. Report drafts use `sessionStorage` and submit only online.

- [ ] **Step 5: Run resident and accessibility smoke tests**

Run:

```bash
.venv/bin/python manage.py test lamto.web.tests.test_resident_views -v 2
.venv/bin/python manage.py test lamto.maintenance.tests.test_ratings -v 2
.venv/bin/python manage.py check --deploy
```

Expected: resident authorization/content tests pass; deploy check reports only environment-dependent HTTPS/HSTS warnings in local mode.

- [ ] **Step 6: Commit**

```bash
git add src/lamto/web src/lamto/maintenance src/lamto/config
git commit -m "feat: add resident accountability PWA"
```

---

### Task 16: Build role workspaces, action inboxes, and durable notifications

**Files:**
- Modify: `src/lamto/config/settings.py`
- Create: `src/lamto/config/worker.py`
- Create: `src/lamto/config/management/commands/run_worker.py`
- Modify: `src/lamto/documents/services.py`
- Modify: `src/lamto/maintenance/reporting.py`
- Modify: `src/lamto/maintenance/triage.py`
- Modify: `src/lamto/maintenance/workorders.py`
- Modify: `src/lamto/finance/proposals.py`
- Modify: `src/lamto/finance/approvals.py`
- Modify: `src/lamto/finance/emergencies.py`
- Modify: `src/lamto/finance/acceptance.py`
- Modify: `src/lamto/finance/payments.py`
- Modify: `src/lamto/finance/publication.py`
- Modify: `src/lamto/finance/corrections.py`
- Modify: `src/lamto/finance/integrity.py`
- Create: `src/lamto/web/forms/staff.py`
- Modify: `src/lamto/web/forms/resident.py`
- Modify: `src/lamto/web/urls.py`
- Create: `src/lamto/web/views/operator.py`
- Create: `src/lamto/web/views/maintenance.py`
- Create: `src/lamto/web/views/board.py`
- Create: `src/lamto/web/views/representative.py`
- Create: `src/lamto/web/views/auditor.py`
- Create: `src/lamto/web/action_inbox.py`
- Create: `src/lamto/web/templates/web/staff/shell.html`
- Create: `src/lamto/web/templates/web/staff/action_inbox.html`
- Create: `src/lamto/web/templates/web/staff/case_detail.html`
- Create: `src/lamto/web/templates/web/staff/work_order_detail.html`
- Create: `src/lamto/web/templates/web/staff/proposal_detail.html`
- Create: `src/lamto/web/templates/web/staff/payment_detail.html`
- Create: `src/lamto/web/templates/web/staff/audit_search.html`
- Create: `src/lamto/notifications/apps.py`
- Create: `src/lamto/notifications/models.py`
- Create: `src/lamto/notifications/services.py`
- Create: `src/lamto/notifications/management/commands/process_notifications.py`
- Create: `src/lamto/notifications/migrations/0001_initial.py`
- Modify: `src/lamto/web/views/resident.py`
- Modify: `src/lamto/web/templates/web/resident/home.html`
- Modify: `src/lamto/web/templates/web/resident/account.html`
- Test: `src/lamto/web/tests/test_role_workspaces.py`
- Test: `src/lamto/notifications/tests/test_delivery.py`
- Test: `src/lamto/config/tests/test_worker_cycle.py`

**Interfaces:**
- Consumes: all domain services; no view performs direct protected-model updates.
- Produces: `action_items_for(membership) -> list[ActionItem]`, role routes/forms, `queue_notification(recipient, event_key, subject, body, channels) -> list[NotificationDelivery]`, per-user notification preferences, and one `run_worker` process for all database-backed jobs.

- [ ] **Step 1: Write failing least-privilege workspace tests**

```python
from django.test import TestCase
from django.urls import reverse


class RoleWorkspaceTests(TestCase):
    def test_maintenance_cannot_open_finance_and_board_sees_only_granted_actions(self):
        maintenance, board = self.make_workspace_users()
        self.client.force_login(maintenance)
        self.assertEqual(self.client.get(reverse("web:proposal-list")).status_code, 403)

        self.client.force_login(board.user)
        response = self.client.get(reverse("web:action-inbox"), {"membership": board.id})
        self.assertContains(response, "Payment verification")
        self.assertNotContains(response, "Record payment")
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `.venv/bin/python manage.py test lamto.web.tests.test_role_workspaces -v 2`

Expected: FAIL because staff workspaces and inbox queries do not exist.

- [ ] **Step 3: Implement task-oriented role views**

Each route calls `require_capability()` before loading protected objects, calls a domain service for mutations, and audits allowed/denied results. Build one staff shell whose navigation is derived from granted capabilities. Implement an explicit active-membership switcher stored in session; never combine capabilities across memberships.

Action inbox items cover manual triage, deadline risk, assigned work, proposal approval, representative co-approval, emergency authorization/ratification, work acceptance, payment recording, payment verification, pending publication, correction review, failed outbox, quarantined upload, and integrity mismatch.

The auditor workspace provides read-only search from a ledger entry to reports/work/proposal, original-versus-redacted hashes, signer addresses, outbox/transaction IDs, integrity observations, and recomputed fund balance. Its verify action calls the read-only integrity service and never mutates business state beyond appending the verification observation/audit event.

Use `wallet-signing.js` on every signed action to display the canonical snapshot/hash and request `eth_signTypedData_v4`; POST the signature/event ID to the domain endpoint.

- [ ] **Step 4: Implement durable in-app and email notifications**

Add `lamto.notifications` to `INSTALLED_APPS`.

Create `NotificationPreference` with user, material-event code, and email-enabled flag; required in-app notices cannot be disabled. Create `NotificationDelivery` with recipient, event key, subject/body, channel (`IN_APP`, `EMAIL`), status, attempts, retry time, error, and unique `(recipient, event_key, channel)`. Add the preference form to the resident account route.

Modify the named maintenance/finance domain services to queue notifications after transaction commit using `transaction.on_commit()`. Cover report receipt, triage/case status, assignment/deadline risk, approval/rejection, emergency deadline/outcome, acceptance, payment actions, publication, and correction/integrity status. Notification failure never rolls back business state.

The worker claims rows with `select_for_update(skip_locked=True)`, sends email through Django, marks in-app rows immediately available, and retries email with bounded backoff. The action inbox, not email, remains authoritative.

`run_worker` executes short bounded batches for triage, expired emergency outcomes, blockchain outbox, confirmed publication/correction finalization, due integrity checks, and notifications, then sleeps with jitter. Each processor remains independently callable/testable, catches and audits only its own adapter failure, and releases database connections between cycles; one failed adapter must not stop the other queues. The deployment runs this one command and may scale replicas because every queue uses locks, leases, and idempotency keys.

- [ ] **Step 5: Run workspace and notification tests**

Run:

```bash
.venv/bin/python manage.py makemigrations notifications
.venv/bin/python manage.py migrate
.venv/bin/python manage.py test lamto.web.tests.test_role_workspaces lamto.notifications lamto.config.tests.test_worker_cycle -v 2
```

Expected: role isolation, active membership, signed-form, idempotent queue, and notification failure isolation tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/lamto/config src/lamto/documents src/lamto/maintenance src/lamto/finance src/lamto/web src/lamto/notifications
git commit -m "feat: add role workspaces and notifications"
```

---

### Task 17: Add MFA, re-authentication, exports, health, backup, and restore controls

**Files:**
- Modify: `src/lamto/config/settings.py`
- Modify: `src/lamto/accounts/models.py`
- Create: `src/lamto/accounts/mfa.py`
- Create: `src/lamto/accounts/security.py`
- Create: `src/lamto/accounts/migrations/0004_security_controls.py`
- Create: `src/lamto/web/views/security.py`
- Create: `src/lamto/web/views/exports.py`
- Create: `src/lamto/web/views/health.py`
- Modify: `src/lamto/web/urls.py`
- Create: `src/lamto/web/templates/web/security/mfa_setup.html`
- Create: `src/lamto/web/templates/web/security/reauth.html`
- Create: `src/lamto/documents/management/commands/backup_objects.py`
- Create: `src/lamto/documents/management/commands/restore_object_backup.py`
- Create: `ops/backup/backup.sh`
- Create: `ops/backup/restore-drill.sh`
- Create: `ops/backup/README.md`
- Create: `ops/deployment-checklist.md`
- Test: `src/lamto/accounts/tests/test_security.py`
- Test: `src/lamto/web/tests/test_exports_and_health.py`

**Interfaces:**
- Consumes: Django sessions, `django-otp`, audit/export data, outbox/worker/storage health.
- Produces: `require_recent_auth(request, max_age_seconds=300)`, protected CSV exports, privileged health endpoint, and executable backup/restore drill.

- [ ] **Step 1: Write failing sensitive-action and export tests**

```python
from django.test import TestCase
from django.urls import reverse


class SecurityTests(TestCase):
    def test_privileged_action_requires_verified_otp_and_recent_reauth(self):
        board = self.make_board_user_with_payment_capability()
        self.client.force_login(board.user)
        response = self.client.post(reverse("web:payment-record"), self.valid_payment_payload())
        self.assertEqual(response.status_code, 403)

    def test_only_auditor_can_export_original_document_history(self):
        operator, auditor = self.make_operator_and_auditor()
        self.client.force_login(operator.user)
        self.assertEqual(self.client.get(reverse("web:audit-export")).status_code, 403)
        self.client.force_login(auditor.user)
        self.assertEqual(self.client.get(reverse("web:audit-export")).status_code, 200)
```

Add focused cases for throttle expiry/reset, session rotation/revocation, break-glass expiry/early revocation, and denial of every finance/document route to a technical administrator even during break glass.

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `.venv/bin/python manage.py test lamto.accounts.tests.test_security lamto.web.tests.test_exports_and_health -v 2`

Expected: FAIL because privileged security/export routes do not exist.

- [ ] **Step 3: Implement TOTP MFA and recent re-authentication**

Add `django_otp.middleware.OTPMiddleware` and TOTP enrollment/verification views. Privileged memberships cannot enter staff workspaces until the session user has a confirmed `TOTPDevice`. Signed financial actions also require `session["recent_reauth_at"]` within 300 seconds; after password + OTP verification, store the current UTC epoch. Log enrollment, verification, failure, device revocation, and sensitive-action denial.

Use Django's Argon2 password hasher first, secure/HTTP-only/SameSite session cookies, CSRF protection, session rotation on login/MFA, and logout/session revocation. Add `AuthThrottleBucket` keyed by a SHA-256 digest of normalized account/IP, lock it during updates, and enforce five login/MFA failures in 15 minutes across application workers; successful authentication resets the bucket. Emit suspicious-login audit events and never store the raw password or OTP in throttle/audit metadata.

Add insert-only `BreakGlassSession` with technical-admin membership, mandatory reason, activating organization authorizer, start, and expiry capped at 60 minutes; append a separate `BreakGlassRevocation` when ended early. It grants only account/organization support and health access, never business approvals, financial/document contents, or stakeholder-key access; every request under it is separately audited and expiry/revocation are checked server-side.

- [ ] **Step 4: Implement auditor exports and the protected health view**

CSV exports stream fixed columns for audit events, fund entries, proposal/approval signatures, document hashes, outbox/transaction IDs, verification observations, and corrections. Require the auditor organization plus `AUDIT_EXPORT`, audit both success/failure, neutralize spreadsheet-formula prefixes in text cells, and never include raw file bytes, wallet private data, or bank account numbers.

The health view requires `TECH_ADMIN` and returns queue age/count, quarantined files, notification failures, outbox status, last confirmed block, latest successful backup marker, and mismatches. A separate pilot metrics panel reports AI suggestion accepted/edited counts, duplicate-confirmation results, triage latency, work response time, approval time, and anchoring delay without turning any metric into workflow authority. Neither view displays stakeholder signatures/private keys or document content.

- [ ] **Step 5: Add executable backup and restore drill**

`backup.sh` must run a PostgreSQL base/WAL backup through WAL-G with `WALG_S3_PREFIX`, `WALG_LIBSODIUM_KEY`, and private S3 credentials; verify the latest backup; invoke `backup_objects` to enumerate every source object version through Boto3, copy it under an immutable version-addressed backup key, and write a hash/version manifest; then write a signed timestamp marker to the private operations bucket. The commands fail closed unless source versioning and destination server-side encryption are enabled.

`restore-drill.sh` must restore into an isolated database name and isolated object bucket/prefix, run migrations in check mode, invoke `restore_object_backup`, execute `verify_integrity --all --database restored` against the restored object location, compare object hashes, computed fund balance, and record counts with the source manifest, replay pending outbox fixtures, assert no duplicates, and destroy the isolated resources only after exporting the drill report.

`ops/deployment-checklist.md` requires HTTPS/HSTS at the reverse proxy, TLS to managed PostgreSQL/object storage, encrypted database volumes/backups, private versioned object buckets with server-side encryption and no public ACLs, secret-manager injection for Django/relayer/contract-owner credentials, localhost/private-network blockchain RPC, log redaction, daily backup scheduling, restore-drill cadence, and documented key/session revocation. Stakeholder wallet keys are explicitly outside every server, backup, and support workflow.

Run:

```bash
.venv/bin/python manage.py makemigrations accounts
.venv/bin/python manage.py migrate
shellcheck ops/backup/backup.sh ops/backup/restore-drill.sh
.venv/bin/python manage.py test lamto.accounts.tests.test_security lamto.web.tests.test_exports_and_health -v 2
```

Expected: shell scripts pass ShellCheck and security/export/health tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/lamto/accounts src/lamto/config/settings.py src/lamto/documents src/lamto/web ops
git commit -m "feat: harden privileged access and recovery"
```

---

### Task 18: Prove the complete normal path, emergency drill, adversarial cases, and pilot handoff

**Files:**
- Modify: `src/lamto/testing/factories.py`
- Create: `src/lamto/accounts/management/commands/seed_pilot.py`
- Create: `tests/e2e/conftest.py`
- Create: `tests/e2e/test_normal_flow.py`
- Create: `tests/e2e/test_blockchain_outage.py`
- Create: `tests/e2e/test_emergency_drill.py`
- Create: `tests/e2e/test_payment_separation.py`
- Create: `tests/e2e/test_tamper_and_correction.py`
- Create: `tests/e2e/test_role_access.py`
- Create: `ops/pilot-runbook.md`
- Create: `ops/emergency-drill-runbook.md`
- Create: `ops/acceptance-report-template.md`
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: every prior task.
- Produces: reproducible pilot seed, automated end-to-end proof, controlled drill procedure, and signed acceptance report.

- [ ] **Step 1: Create deterministic non-production factories and seed data**

Factories create one building, units, organizations, users/memberships/capability grants, stakeholder test wallets, one resident report, required document pairs, and clearly labeled test/drill records. `seed_pilot --fixture` is idempotent and refuses to run when `PILOT_ALLOW_FIXTURES` is false. It prints created login identifiers but never private keys; test wallet keys live only in ignored test environment files.

Run `.venv/bin/playwright install --with-deps chromium` once before the browser suite.

`tests/e2e/conftest.py` defines `PilotDriver` with the exact methods used below: `login`, `pause_chain`, `resume_chain`, `confirm_all_chain_events`, `latest_outbox_event_ids`, `fund_balance`, `ledger_count(drill=False)`, `audit_contains`, `prepare_locally_approved_normal_work`, and role-page methods for report, triage, proposal, approval, work, acceptance, payment, publication eligibility/blocking, emergency decision, resident ledger inspection, and auditor verification. Each method drives a visible browser action and then queries only public read views for assertions.

- [ ] **Step 2: Write the cross-role normal-flow test before adding missing glue**

```python
def test_realistic_normal_flow(page, seeded_pilot):
    resident = seeded_pilot.login(page, "resident")
    resident.submit_report("Elevator shakes heavily", "Building B / Lift 2", "tests/fixtures/elevator.jpg")

    operator = seeded_pilot.login(page, "operator")
    operator.confirm_triage_and_create_paid_work_order()
    operator.submit_signed_proposal(amount_vnd=18_500_000)

    seeded_pilot.login(page, "board_approver").approve_proposal()
    seeded_pilot.login(page, "resident_representative").coapprove_proposal()
    seeded_pilot.login(page, "maintenance").complete_assigned_work()
    seeded_pilot.login(page, "board_payment_recorder").accept_and_record_payment()
    seeded_pilot.login(page, "board_payment_verifier").verify_payment()
    seeded_pilot.confirm_all_chain_events()
    seeded_pilot.login(page, "eligible_publisher").sign_publication_snapshot()
    seeded_pilot.confirm_all_chain_events()

    ledger = seeded_pilot.login(page, "resident").open_latest_ledger_entry()
    assert ledger.actual_cost_vnd == 18_500_000
    assert ledger.status == "Record verified"
    assert ledger.has_redacted_documents()

    verification = seeded_pilot.login(page, "auditor").verify_latest_ledger_entry()
    assert verification.document_hashes_match
    assert verification.chain_events_match
    assert verification.recomputed_fund_balance_vnd == ledger.current_fund_balance_vnd
```

- [ ] **Step 3: Run the normal-flow acceptance test**

Run: `.venv/bin/python -m pytest tests/e2e/test_normal_flow.py -v`

Expected: PASS because Tasks 1-17 already provide every route and transition. If it fails, stop and repair the owning earlier task with a focused regression test; do not duplicate a domain rule in `PilotDriver` or browser helpers.

- [ ] **Step 4: Add adversarial and emergency-drill browser tests**

Required tests must prove:

- chain paused after local normal approvals: work starts with `Pending blockchain anchoring`, retries reuse event IDs, ledger remains absent until confirmation;
- payment recorder self-verification denied; publisher-as-verifier succeeds only when that user was not proposal creator, Board proposal approver, or payment recorder, and each forbidden combination is denied/audited;
- proposal/document changed after signature creates new version or mismatch and cannot reuse approval;
- AI/email outage leaves report/action inbox authoritative;
- role/object/file/export matrix denies every prohibited access;
- controlled emergency drill is permanently labeled, uses actual role accounts/wallets, starts while chain is paused, records ratification or rejection within 24 hours, restores/retries original IDs, preserves all events, never posts the real fund, and cannot convert to a real record;
- automated emergency outcomes cover ratified, rejected, and overdue;
- tampered controlled document appends mismatch, correction preserves original, and reversing/replacement entries reconcile exactly;
- backup restore and outbox replay produce the same hashes/balance with no duplicates.

At minimum, include these executable tests rather than a prose-only checklist:

```python
def test_normal_work_can_start_pending_anchor_but_cannot_publish(page, seeded_pilot):
    seeded_pilot.pause_chain()
    seeded_pilot.prepare_locally_approved_normal_work(page)
    work = seeded_pilot.login(page, "maintenance").start_assigned_work()

    assert work.verification_label == "Pending blockchain anchoring"
    seeded_pilot.login(page, "maintenance").complete_assigned_work()
    seeded_pilot.login(page, "board_payment_recorder").accept_and_record_payment()
    seeded_pilot.login(page, "board_payment_verifier").verify_payment()
    before_ids = seeded_pilot.latest_outbox_event_ids()
    blocked = seeded_pilot.login(page, "eligible_publisher").attempt_publication()

    assert blocked.reason == "Required blockchain evidence is still pending"
    assert seeded_pilot.ledger_count() == 0

    seeded_pilot.resume_chain()
    seeded_pilot.confirm_all_chain_events()
    assert seeded_pilot.latest_outbox_event_ids() == before_ids
    seeded_pilot.login(page, "eligible_publisher").sign_publication_snapshot()
    assert seeded_pilot.ledger_count() == 0
    seeded_pilot.confirm_all_chain_events()
    assert seeded_pilot.ledger_count() == 1


def test_controlled_emergency_drill_is_isolated_and_preserved(page, seeded_pilot):
    starting_balance = seeded_pilot.fund_balance()
    seeded_pilot.pause_chain()
    drill = seeded_pilot.login(page, "board_emergency_approver").authorize_emergency_drill()
    started = seeded_pilot.login(page, "maintenance").start_drill_work()
    outcome = seeded_pilot.login(page, "resident_representative").reject_drill("Estimate incomplete")

    assert drill.label == "Emergency drill"
    assert started.verification_label == "Pending blockchain anchoring"
    assert outcome.label == "Ratification rejected"

    seeded_pilot.resume_chain()
    seeded_pilot.confirm_all_chain_events()
    assert seeded_pilot.fund_balance() == starting_balance
    assert seeded_pilot.ledger_count(drill=True) == 0
    assert seeded_pilot.audit_contains(drill.id, ["authorized", "started", "rejected", "anchored"])
```

- [ ] **Step 5: Run the complete verification suite**

Run:

```bash
docker compose up -d
docker compose -f chain/besu/compose.yaml up -d
cd chain && forge fmt --check && forge test -vv && cd ..
.venv/bin/python manage.py check --deploy
.venv/bin/python manage.py test -v 2
.venv/bin/python -m pytest tests/e2e -v
.venv/bin/python manage.py verify_integrity --all
bash ops/backup/restore-drill.sh
```

Expected: all contract, Django, browser, integrity, authorization, and restore checks pass; zero duplicate financial/chain rows; zero unresolved high-severity finding.

- [ ] **Step 6: Execute controlled pilot acceptance and commit**

Follow `ops/pilot-runbook.md` for one real normal case. Follow `ops/emergency-drill-runbook.md` for the isolated drill unless a genuine emergency naturally supplies the same proof. The runbook must state that no incident is manufactured, safety action is never delayed, and the pilot is not held open awaiting an emergency.

Collect sign-off from Board, operator, resident representative, auditor, maintenance, and participating resident in `ops/acceptance-report-template.md`.

```bash
git add src/lamto/testing src/lamto/accounts/management tests/e2e ops pyproject.toml
git commit -m "test: prove accountability pilot acceptance"
```

## Spec Coverage Index

| Approved design area | Implemented by |
|---|---|
| Scope, single-building records, roles | Tasks 1-2 |
| Immutable audit and privileged capability boundaries | Tasks 2, 16-17 |
| Original/redacted documents, hashing, malware scanning, access | Tasks 3, 12, 14-17 |
| Text/photo reports, live AI, fallback, duplicate candidates, human confirmation | Tasks 4-5 |
| Cases, assignments, deadlines, progress, before/after evidence, ratings | Tasks 5, 15-16 |
| Immutable proposal versions and exact local signatures | Tasks 6-8 |
| Normal authorization while anchoring is pending | Tasks 8, 11, 18 |
| Emergency authorization and 24-hour outcomes | Tasks 9, 18 |
| Evidence-only chain, independent wallets, four managed validators | Tasks 6, 10-11 |
| Acceptance, actual cost, payment recording and independent verification | Task 12 |
| Opening balance/inflows, two-stage publication, outflow, computed balance | Task 13 |
| Corrections, reversing entries, tamper observations | Task 14 |
| Resident Transparency Ledger and role-specific PWA | Tasks 15-16 |
| Notifications, MFA, recent re-authentication, exports, health | Tasks 16-17 |
| Encryption/storage deployment controls, backup and restore | Tasks 3, 17 |
| Adversarial scenarios, real normal case, controlled emergency drill | Task 18 |
