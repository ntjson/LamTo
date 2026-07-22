# Gate Recognition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Residents register vehicle plates and enrol a face in the LamTo app; a credentialled reader phone recognizes them at the gate and writes a rolling 24-hour entry/exit log for Management.

**Architecture:** A new Django app `lamto.gate` holds enrolments, reader credentials, and short-lived events, reusing `lamto.accounts` tenancy (`Building` / `Unit` / `ResidentOccupancy`). Face embeddings are computed server-side behind a `FaceEmbedder` Protocol (InsightFace in production, a deterministic fake in tests) and stored Fernet-encrypted; plate OCR runs on the reader device with Google ML Kit and arrives as text. The subsystem logs identity and authorizes nothing.

**Tech Stack:** Django 5.2, DRF + drf-spectacular, django-rest-knox, PostgreSQL 17, MinIO/S3 private storage, ClamAV, numpy + onnxruntime + insightface, Flutter (riverpod, dio, image_picker, google_mlkit_text_recognition).

**Spec:** `docs/superpowers/specs/2026-07-22-gate-recognition-design.md`

## Global Constraints

- Python `>=3.12`, Django `~=5.2`. Settings read config with `os.getenv("NAME", default)` and coerce types explicitly.
- **`GATE_FACE_MATCH_THRESHOLD = 0.38` is an UNVALIDATED PILOT STARTING POINT, NOT a production default.** InsightFace's own clustering tooling defaults to cosine `0.48`, so `0.38` is on the permissive side. No environment may run face recognition on the fallback value: Task 14 calibrates it and the pilot sets the calibrated value explicitly. The same applies to `GATE_MIN_FACE_SHARPNESS` and `GATE_MIN_FACE_DET_SCORE`.
- **The gate app never writes to `lamto.audit`.** A 24-hour event that leaves a permanent audit row is not a 24-hour event. Enrolment *decisions* are not gate events and may be audited; recognitions may not.
- **Gate capture images are never stored.** Recognition embeds in-memory and discards within the request.
- `GateEvent` is append-only against UPDATE only — **never `BEFORE UPDATE OR DELETE`**. Copying the `documents` trigger pattern makes the retention purge impossible.
- All staff web routes live under `/s/`. There is no resident web surface.
- Resident API lives under `/api/v1/`, knox-authenticated, occupancy selected with the `X-LamTo-Occupancy` header via `resolve_api_occupancy`.
- Errors are RFC 9457 problem+json with a stable machine `code`. `detail` is developer English. **All Vietnamese user-facing copy lives in the Flutter app**, keyed off `code` — never a server-supplied display string.
- After any API change: `python manage.py spectacular --file docs/api/openapi-v1.yaml`, then `app/tool/generate_api.sh`. `src/lamto/api/tests/test_openapi.py` fails if the committed schema is stale; `app/tool/check_api_generated.sh` fails if the Dart client is stale.
- Django app tests live in `src/lamto/<app>/tests/test_*.py`. `pyproject.toml` sets `testpaths = ["tests"]`, so app tests must be run with an explicit path.
- Shell prefix for every Python command in this plan (loads `.env`): `set -a && . .env && set +a &&`
- WCAG 2.2 AA on both surfaces. Staff templates extend `web/staff/shell.html` and fill `{% block content %}`.
- No new dependency where stdlib, an installed dependency, or a native platform feature does the job. `cryptography` is already present transitively via `web3`.

## Deviations From The Spec

Two mechanical refinements, both deliberate:

1. **`POST /api/v1/gate/recognize` is split into `/gate/recognize/face` (multipart) and `/gate/recognize/plate` (JSON).** One path carrying two content types generates a bad Dart client and a confused OpenAPI schema. Real hardware calls one of the two; nothing else changes.
2. **A rejected or expired enrolment keeps its row with `embedding = NULL` rather than deleting the row.** The spec says "delete the embedding row". The biometric is what must not survive; the review note is what the resident needs to read. A database `CheckConstraint` makes retaining a vector on a non-approved row impossible, which is a stronger guarantee than a delete that someone can forget to call.

## File Structure

**New Django app — `src/lamto/gate/`**

| File | Responsibility |
|---|---|
| `apps.py` | App config |
| `models.py` | `FaceEnrollment`, `VehiclePlate`, `PendingEnrollmentPhoto`, `GateDevice`, `GateDeviceCredential`, `GateEvent`, `GatePurgeHeartbeat` |
| `plates.py` | `normalize_plate` — the single comparison form |
| `crypto.py` | Fernet seal/open for embedding vectors |
| `embedding.py` | `FaceEmbedder` Protocol, quality errors, `get_embedder()`, `InsightFaceEmbedder` |
| `photos.py` | Pending review photo put/delete against private storage (version-aware) |
| `enrollment.py` | Resident-initiated submit and revoke |
| `review.py` | Manager decisions |
| `devices.py` | Credential issue / rotate / revoke / authenticate |
| `matching.py` | Cosine match against approved enrolments, plate lookup |
| `recognition.py` | Reader entry points; writes `GateEvent` |
| `retention.py` | Purge of expired events and expired photos |
| `management/commands/purge_gate_data.py` | Hourly ops entry point |
| `management/commands/calibrate_gate_threshold.py` | Threshold calibration report |
| `tests/fakes.py` | Deterministic embedder |
| `tests/test_*.py` | Per-module tests |

**Modified**

| File | Change |
|---|---|
| `src/lamto/config/settings.py` | `lamto.gate` in `INSTALLED_APPS`; gate settings block |
| `src/lamto/api/problems.py` | Gate machine codes |
| `src/lamto/api/urls.py` | Gate routes |
| `src/lamto/web/urls.py` | `/s/gate/…` routes |
| `src/lamto/web/staff.py` | "Gate" nav item |
| `src/lamto/web/views/health.py` | Purge heartbeat on the ops health snapshot |
| `src/lamto/web/templates/web/staff/ops_health.html` | Purge heartbeat row |
| `pyproject.toml` | numpy, onnxruntime, insightface, opencv-python-headless; `insightface` pytest marker |
| `.env.example` | Gate settings |
| `ops/deployment-checklist.md` | Hourly purge cron entry |
| `docs/api/openapi-v1.yaml` | Regenerated |

**New API modules** — `src/lamto/api/views.py` is already 801 lines and `serializers.py` 452. Gate goes in its own pair rather than growing either.

| File | Responsibility |
|---|---|
| `src/lamto/api/gate_serializers.py` | Resident + reader request/response shapes |
| `src/lamto/api/gate_views.py` | Resident registration endpoints and the two reader endpoints |

**New staff web** — `src/lamto/web/views/gate.py`, plus templates `web/staff/gate_queue.html`, `gate_registrations.html`, `gate_devices.html`, `gate_log.html`.

**New Flutter** — `app/lib/features/gate/`: `gate_repository.dart`, `gate_registration_screen.dart`, `reader/reader_credential_store.dart`, `reader/plate_ocr.dart`, `reader/gate_reader_screen.dart`.

---

### Task 1: Plate normalization

**Files:**
- Create: `src/lamto/gate/__init__.py`, `src/lamto/gate/plates.py`
- Create: `src/lamto/gate/tests/__init__.py`
- Test: `src/lamto/gate/tests/test_plates.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `normalize_plate(raw: str) -> str`, `PlateFormatError(ValueError)`. Task 5 (enrolment), Task 9 (recognition), and Task 16 (Dart port) all depend on this exact behaviour.

- [ ] **Step 1: Create the package directories**

```bash
mkdir -p src/lamto/gate/tests
touch src/lamto/gate/__init__.py src/lamto/gate/tests/__init__.py
```

- [ ] **Step 2: Write the failing test**

Create `src/lamto/gate/tests/test_plates.py`:

```python
import pytest

from lamto.gate.plates import PlateFormatError, normalize_plate


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("51F-123.45", "51F12345"),
        ("  51f 123 45 ", "51F12345"),
        ("29-A1 234.56", "29A123456"),
        ("59X1-99999", "59X199999"),
        ("51F12345", "51F12345"),
    ],
)
def test_normalizes_to_uppercase_alphanumeric(raw, expected):
    assert normalize_plate(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "!!!", "51F", "-.-", "51F1234567890123"])
def test_rejects_plates_without_usable_content(raw):
    with pytest.raises(PlateFormatError):
        normalize_plate(raw)


def test_rejects_none_without_raising_type_error():
    with pytest.raises(PlateFormatError):
        normalize_plate(None)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `set -a && . .env && set +a && .venv/bin/python -m pytest src/lamto/gate/tests/test_plates.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'lamto.gate.plates'`

- [ ] **Step 4: Write the implementation**

Create `src/lamto/gate/plates.py`:

```python
"""Vietnamese licence plate normalization.

Plates are compared as one normalized string: uppercase, ASCII letters and
digits only. ``51F-123.45``, ``51f 123.45`` and ``51F12345`` are the same
plate. This is the only form the system stores or matches on; the raw text a
reader produced is kept separately on the event so a bad OCR read stays
visible.
"""

import re
import unicodedata

# Vietnamese plates are ASCII, but a reader or a keyboard can emit full-width
# or decorated characters; fold them before stripping.
_NON_ALNUM = re.compile(r"[^A-Z0-9]")

MIN_LENGTH = 5
MAX_LENGTH = 12


class PlateFormatError(ValueError):
    """Plate has no usable alphanumeric content, or an implausible length."""


def normalize_plate(raw: str | None) -> str:
    folded = unicodedata.normalize("NFKD", raw or "").upper()
    normalized = _NON_ALNUM.sub("", folded)
    if not MIN_LENGTH <= len(normalized) <= MAX_LENGTH:
        raise PlateFormatError(
            f"Plate must contain {MIN_LENGTH} to {MAX_LENGTH} letters or digits."
        )
    return normalized
```

- [ ] **Step 5: Run test to verify it passes**

Run: `set -a && . .env && set +a && .venv/bin/python -m pytest src/lamto/gate/tests/test_plates.py -v`
Expected: PASS, 9 passed

- [ ] **Step 6: Commit**

```bash
git add src/lamto/gate/__init__.py src/lamto/gate/plates.py src/lamto/gate/tests/
git commit -m "feat(gate): normalize Vietnamese licence plates to one comparison form"
```

---

### Task 2: Models, settings, and the append-only trigger

**Files:**
- Create: `src/lamto/gate/apps.py`, `src/lamto/gate/models.py`
- Create: `src/lamto/gate/migrations/__init__.py`, `src/lamto/gate/migrations/0001_initial.py` (generated, then edited)
- Modify: `src/lamto/config/settings.py` (INSTALLED_APPS ~line 48-61; new settings block after `PILOT_ALLOW_FIXTURES` ~line 318)
- Modify: `.env.example`
- Test: `src/lamto/gate/tests/test_models.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `ReviewStatus`, `FaceEnrollment`, `VehiclePlate`, `PendingEnrollmentPhoto`, `GateDevice`, `GateDeviceCredential`, `GateEvent`, `GatePurgeHeartbeat`. Settings names: `GATE_EVENT_RETENTION_HOURS`, `GATE_ENROLLMENT_PHOTO_TTL_HOURS`, `GATE_CREDENTIAL_ROTATION_GRACE_HOURS`, `GATE_FACE_MATCH_THRESHOLD`, `GATE_FACE_EMBEDDER`, `GATE_EMBEDDING_KEY`, `GATE_MAX_FACE_UPLOAD_BYTES`, `GATE_MIN_FACE_PIXELS`, `GATE_MIN_FACE_DET_SCORE`, `GATE_MIN_FACE_SHARPNESS`.

- [ ] **Step 1: Write the app config**

Create `src/lamto/gate/apps.py`:

```python
from django.apps import AppConfig


class GateConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "lamto.gate"
    label = "gate"
```

- [ ] **Step 2: Write the models**

Create `src/lamto/gate/models.py`:

```python
"""Gate recognition records: enrolments, readers, and short-lived events.

Retention is the defining constraint. ``GateEvent`` rows are deleted whole
``GATE_EVENT_RETENTION_HOURS`` after ``occurred_at``; the pending review photo
has its own, independent TTL. Nothing in this app writes to ``lamto.audit`` —
a 24-hour event that leaves a permanent audit row is not a 24-hour event.

No gate capture image is ever stored. The only image that touches storage is
the enrolment review photo, and it lives until a manager decides or the TTL
expires, whichever comes first.
"""

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from lamto.accounts.models import Building, ResidentOccupancy


class ReviewStatus(models.TextChoices):
    PENDING = "PENDING", "Pending review"
    APPROVED = "APPROVED", "Approved"
    REJECTED = "REJECTED", "Rejected"
    EXPIRED = "EXPIRED", "Expired before review"


class FaceEnrollment(models.Model):
    """One face per resident occupancy.

    ``embedding`` holds a Fernet-sealed float32 vector. A rejected or expired
    enrolment keeps its row so the resident can read the reason, but the
    check constraint makes it impossible for that row to still hold a vector.
    """

    occupancy = models.OneToOneField(
        ResidentOccupancy, on_delete=models.CASCADE, related_name="face_enrollment"
    )
    embedding = models.BinaryField(
        null=True,
        blank=True,
        help_text="Fernet-sealed float32 vector; NULL once deleted.",
    )
    model_name = models.CharField(max_length=64, blank=True)
    model_version = models.CharField(max_length=64, blank=True)
    status = models.CharField(
        max_length=16, choices=ReviewStatus.choices, default=ReviewStatus.PENDING
    )
    submitted_at = models.DateTimeField(default=timezone.now)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.CharField(max_length=255, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    ~Q(status__in=[ReviewStatus.REJECTED, ReviewStatus.EXPIRED])
                    | Q(embedding__isnull=True)
                ),
                name="gate_no_embedding_when_not_live",
            )
        ]

    def __str__(self):
        return f"FaceEnrollment(occupancy={self.occupancy_id}, status={self.status})"


class VehiclePlate(models.Model):
    """A plate claimed by one occupancy. Many rows per resident is the feature.

    ``building`` is denormalized from ``occupancy.unit.building`` so the
    approved-uniqueness constraint can be expressed without an FK traversal.
    """

    occupancy = models.ForeignKey(
        ResidentOccupancy, on_delete=models.CASCADE, related_name="vehicle_plates"
    )
    building = models.ForeignKey(
        Building, on_delete=models.PROTECT, related_name="vehicle_plates"
    )
    plate = models.CharField(max_length=12, help_text="Normalized form only.")
    status = models.CharField(
        max_length=16, choices=ReviewStatus.choices, default=ReviewStatus.PENDING
    )
    submitted_at = models.DateTimeField(default=timezone.now)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.CharField(max_length=255, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["occupancy", "plate"], name="gate_plate_once_per_occupancy"
            ),
            models.UniqueConstraint(
                fields=["building", "plate"],
                condition=Q(status=ReviewStatus.APPROVED),
                name="gate_approved_plate_once_per_building",
            ),
        ]

    def __str__(self):
        return f"VehiclePlate({self.plate}, status={self.status})"


class PendingEnrollmentPhoto(models.Model):
    """The review image. Lives until a decision or ``expires_at``, never longer.

    ``provider_version_id`` matters: the private bucket is versioned, so a
    plain delete leaves a delete marker and keeps the object. Deletion must
    name the version.
    """

    enrollment = models.OneToOneField(
        FaceEnrollment, on_delete=models.CASCADE, related_name="pending_photo"
    )
    storage_key = models.CharField(max_length=512, unique=True)
    provider_version_id = models.CharField(max_length=512, blank=True)
    content_type = models.CharField(max_length=127)
    byte_size = models.PositiveBigIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(db_index=True)


class GateDevice(models.Model):
    """A reader. Direction is declared, because one camera cannot infer it."""

    class Direction(models.TextChoices):
        ENTRY = "ENTRY", "Entry"
        EXIT = "EXIT", "Exit"

    building = models.ForeignKey(
        Building, on_delete=models.PROTECT, related_name="gate_devices"
    )
    label = models.CharField(max_length=120)
    direction = models.CharField(max_length=8, choices=Direction.choices)
    active = models.BooleanField(default=True)
    last_seen_hour = models.DateTimeField(
        null=True,
        blank=True,
        help_text=(
            "Truncated to the hour on purpose: enough to see a reader go dark, "
            "too coarse to place anyone at the gate."
        ),
    )

    def __str__(self):
        return f"{self.label} ({self.direction})"


class GateDeviceCredential(models.Model):
    """A reader token. Only the SHA-256 digest is stored.

    Rotation issues a new row and sets the previous row's ``expires_at`` to
    now + grace, so a device is reconfigured without a lockout. Revocation
    sets ``revoked_at`` and takes effect on the next request, no grace.
    Multiple live credentials per device is the mechanism, not an accident.
    """

    device = models.ForeignKey(
        GateDevice, on_delete=models.CASCADE, related_name="credentials"
    )
    token_sha256 = models.CharField(max_length=64, unique=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )

    def is_valid(self, now=None) -> bool:
        now = now or timezone.now()
        if self.revoked_at is not None:
            return False
        return self.expires_at is None or self.expires_at > now


class GateEvent(models.Model):
    """One sighting. Deleted whole by the retention purge — never updated.

    Face events carry the audit metadata that makes a live match explainable
    while it is being disputed at the gate. Because the row dies within
    24-25 hours, this is not a calibration dataset.
    """

    class Kind(models.TextChoices):
        FACE = "FACE", "Face"
        PLATE = "PLATE", "Plate"

    building = models.ForeignKey(
        Building, on_delete=models.CASCADE, related_name="gate_events"
    )
    device = models.ForeignKey(
        GateDevice, on_delete=models.CASCADE, related_name="events"
    )
    kind = models.CharField(max_length=8, choices=Kind.choices)
    direction = models.CharField(max_length=8, choices=GateDevice.Direction.choices)
    occurred_at = models.DateTimeField(default=timezone.now, db_index=True)
    matched_occupancy = models.ForeignKey(
        ResidentOccupancy,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="gate_events",
    )
    matched_plate = models.ForeignKey(
        VehiclePlate,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="gate_events",
    )
    raw_plate_text = models.CharField(max_length=64, blank=True)
    normalized_plate_text = models.CharField(max_length=12, blank=True)
    model_name = models.CharField(max_length=64, blank=True)
    model_version = models.CharField(max_length=64, blank=True)
    match_metric = models.CharField(max_length=16, blank=True)
    threshold_used = models.FloatField(null=True, blank=True)
    match_score = models.FloatField(null=True, blank=True)


class GatePurgeHeartbeat(models.Model):
    """Single row: when the retention job last completed successfully.

    A bare timestamp of a successful job run identifies nobody. Purge failure
    is a retention breach, so ops needs to see staleness.
    """

    last_success_at = models.DateTimeField()
    events_deleted = models.PositiveIntegerField(default=0)
    photos_deleted = models.PositiveIntegerField(default=0)
```

- [ ] **Step 3: Register the app and add settings**

In `src/lamto/config/settings.py`, add `'lamto.gate',` to `INSTALLED_APPS` immediately after `'lamto.finance',`.

Then append this block after the `PILOT_ALLOW_FIXTURES` block (around line 318):

```python
# --- Gate recognition (docs/superpowers/specs/2026-07-22-gate-recognition-design.md) ---
# Logs identity; authorizes nothing. No gate capture image is ever stored.
GATE_EVENT_RETENTION_HOURS = int(os.getenv("GATE_EVENT_RETENTION_HOURS", "24"))
GATE_ENROLLMENT_PHOTO_TTL_HOURS = int(os.getenv("GATE_ENROLLMENT_PHOTO_TTL_HOURS", "72"))
GATE_CREDENTIAL_ROTATION_GRACE_HOURS = int(
    os.getenv("GATE_CREDENTIAL_ROTATION_GRACE_HOURS", "24")
)
# UNVALIDATED PILOT STARTING POINT — NOT a production default. InsightFace's own
# clustering tooling defaults to cosine 0.48, so this is deliberately permissive.
# Calibrate per building before any pilot: manage.py calibrate_gate_threshold.
GATE_FACE_MATCH_THRESHOLD = float(os.getenv("GATE_FACE_MATCH_THRESHOLD", "0.38"))
# Image-quality gates. Also unvalidated starting points; calibrated with the threshold.
GATE_MAX_FACE_UPLOAD_BYTES = int(os.getenv("GATE_MAX_FACE_UPLOAD_BYTES", str(8 * 1024 * 1024)))
GATE_MIN_FACE_PIXELS = int(os.getenv("GATE_MIN_FACE_PIXELS", "80"))
GATE_MIN_FACE_DET_SCORE = float(os.getenv("GATE_MIN_FACE_DET_SCORE", "0.6"))
GATE_MIN_FACE_SHARPNESS = float(os.getenv("GATE_MIN_FACE_SHARPNESS", "40"))
# Dotted path to the FaceEmbedder implementation. Empty until Task 13 lands the
# production embedder; get_embedder() raises rather than guessing.
GATE_FACE_EMBEDDER = os.getenv("GATE_FACE_EMBEDDER", "")
GATE_EMBEDDING_KEY = coalesce_secret(os.getenv("GATE_EMBEDDING_KEY"), SECRET_KEY)
```

Append to `.env.example`:

```
# --- Gate recognition ---
GATE_EVENT_RETENTION_HOURS=24
GATE_ENROLLMENT_PHOTO_TTL_HOURS=72
GATE_CREDENTIAL_ROTATION_GRACE_HOURS=24
# Unvalidated pilot starting point. Set the calibrated value before any pilot.
GATE_FACE_MATCH_THRESHOLD=0.38
GATE_MIN_FACE_SHARPNESS=40
GATE_EMBEDDING_KEY=
```

- [ ] **Step 4: Generate the migration**

Run: `set -a && . .env && set +a && .venv/bin/python manage.py makemigrations gate`
Expected: `Migrations for 'gate': src/lamto/gate/migrations/0001_initial.py` listing seven `CreateModel` operations.

- [ ] **Step 5: Add the UPDATE-only trigger to the generated migration**

Append this operation to the `operations` list in `src/lamto/gate/migrations/0001_initial.py`.

**`BEFORE UPDATE` only.** The `documents` and `audit` apps use `BEFORE UPDATE OR DELETE` plus a TRUNCATE guard because their rows must survive forever. Gate events must be deletable — that is the whole retention design — so DELETE and TRUNCATE stay open.

```python
        migrations.RunSQL(
            """
            CREATE FUNCTION gate_event_prevent_update()
            RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'gate events are append-only'
                USING ERRCODE = 'check_violation';
            END;
            $$ LANGUAGE plpgsql;

            CREATE TRIGGER gate_event_append_only
            BEFORE UPDATE ON gate_gateevent
            FOR EACH ROW EXECUTE FUNCTION gate_event_prevent_update();
            """,
            """
            DROP TRIGGER gate_event_append_only ON gate_gateevent;
            DROP FUNCTION gate_event_prevent_update();
            """,
        ),
```

- [ ] **Step 6: Write the failing test**

Create `src/lamto/gate/tests/test_models.py`:

```python
import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from lamto.accounts.models import Building, ResidentOccupancy, Unit, User
from lamto.gate.models import (
    FaceEnrollment,
    GateDevice,
    GateEvent,
    ReviewStatus,
    VehiclePlate,
)


@pytest.fixture
def occupancy(db):
    building = Building.objects.create(name="Gate Test Building")
    unit = Unit.objects.create(building=building, label="12A")
    user = User.objects.create(email="resident@example.com", display_name="Resident")
    return ResidentOccupancy.objects.create(user=user, unit=unit)


def test_rejected_enrollment_cannot_keep_an_embedding(occupancy):
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            FaceEnrollment.objects.create(
                occupancy=occupancy,
                embedding=b"sealed",
                status=ReviewStatus.REJECTED,
            )


def test_pending_enrollment_may_hold_an_embedding(occupancy):
    enrollment = FaceEnrollment.objects.create(
        occupancy=occupancy, embedding=b"sealed", status=ReviewStatus.PENDING
    )
    assert enrollment.pk is not None


def test_approved_plate_is_unique_per_building(occupancy):
    building = occupancy.unit.building
    other_unit = Unit.objects.create(building=building, label="14B")
    other_user = User.objects.create(email="other@example.com", display_name="Other")
    other = ResidentOccupancy.objects.create(user=other_user, unit=other_unit)
    VehiclePlate.objects.create(
        occupancy=occupancy,
        building=building,
        plate="51F12345",
        status=ReviewStatus.APPROVED,
    )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            VehiclePlate.objects.create(
                occupancy=other,
                building=building,
                plate="51F12345",
                status=ReviewStatus.APPROVED,
            )


def test_pending_duplicates_are_allowed_until_approval(occupancy):
    building = occupancy.unit.building
    other_unit = Unit.objects.create(building=building, label="15C")
    other_user = User.objects.create(email="third@example.com", display_name="Third")
    other = ResidentOccupancy.objects.create(user=other_user, unit=other_unit)
    VehiclePlate.objects.create(
        occupancy=occupancy, building=building, plate="51F99999"
    )
    VehiclePlate.objects.create(
        occupancy=other, building=building, plate="51F99999"
    )
    assert VehiclePlate.objects.filter(plate="51F99999").count() == 2


def _event(occupancy):
    building = occupancy.unit.building
    device = GateDevice.objects.create(
        building=building, label="North gate", direction=GateDevice.Direction.ENTRY
    )
    return GateEvent.objects.create(
        building=building,
        device=device,
        kind=GateEvent.Kind.PLATE,
        direction=device.direction,
        occurred_at=timezone.now(),
        raw_plate_text="51F-123.45",
        normalized_plate_text="51F12345",
    )


def test_gate_event_cannot_be_updated(occupancy):
    event = _event(occupancy)
    event.raw_plate_text = "tampered"
    with pytest.raises(Exception):
        with transaction.atomic():
            event.save(update_fields=["raw_plate_text"])


def test_gate_event_can_be_deleted(occupancy):
    event = _event(occupancy)
    event.delete()
    assert not GateEvent.objects.filter(pk=event.pk).exists()
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `set -a && . .env && set +a && .venv/bin/python -m pytest src/lamto/gate/tests/test_models.py -v`
Expected: PASS, 6 passed

`test_gate_event_can_be_deleted` is the one that matters: it proves the trigger did not copy the `documents` pattern and block DELETE.

- [ ] **Step 8: Commit**

```bash
git add src/lamto/gate/apps.py src/lamto/gate/models.py src/lamto/gate/migrations/ \
  src/lamto/gate/tests/test_models.py src/lamto/config/settings.py .env.example
git commit -m "feat(gate): add enrolment, reader, and event models with UPDATE-only events"
```

---

### Task 3: Embedding encryption

**Files:**
- Create: `src/lamto/gate/crypto.py`
- Modify: `pyproject.toml` (add `numpy`)
- Test: `src/lamto/gate/tests/test_crypto.py`

**Interfaces:**
- Consumes: `settings.GATE_EMBEDDING_KEY` (Task 2).
- Produces: `seal_embedding(vector) -> bytes`, `open_embedding(sealed: bytes) -> np.ndarray`, `EmbeddingDecryptionError`, `VECTOR_DTYPE = np.float32`.

`cryptography` is already installed transitively via `web3`, so Fernet costs nothing new. `numpy` is a genuine addition — it is the vector container and the matcher.

- [ ] **Step 1: Add numpy**

In `pyproject.toml`, add to `dependencies`, after `"Pillow>=11,<13",`:

```toml
  "numpy>=2,<3",
```

Run: `set -a && . .env && set +a && .venv/bin/python -m pip install "numpy>=2,<3"`
Expected: numpy installed.

- [ ] **Step 2: Write the failing test**

Create `src/lamto/gate/tests/test_crypto.py`:

```python
import numpy as np
import pytest

from lamto.gate.crypto import (
    EmbeddingDecryptionError,
    open_embedding,
    seal_embedding,
)


def test_roundtrips_a_vector(settings):
    settings.GATE_EMBEDDING_KEY = "test-key"
    vector = np.arange(512, dtype=np.float32) / 512.0
    restored = open_embedding(seal_embedding(vector))
    assert np.allclose(restored, vector)
    assert restored.dtype == np.float32
    assert restored.shape == (512,)


def test_ciphertext_does_not_contain_the_raw_bytes(settings):
    settings.GATE_EMBEDDING_KEY = "test-key"
    vector = np.ones(8, dtype=np.float32)
    assert vector.tobytes() not in seal_embedding(vector)


def test_a_different_key_cannot_open_the_vector(settings):
    settings.GATE_EMBEDDING_KEY = "first-key"
    sealed = seal_embedding(np.ones(8, dtype=np.float32))
    settings.GATE_EMBEDDING_KEY = "second-key"
    with pytest.raises(EmbeddingDecryptionError):
        open_embedding(sealed)


def test_rejects_a_non_vector(settings):
    settings.GATE_EMBEDDING_KEY = "test-key"
    with pytest.raises(ValueError):
        seal_embedding(np.zeros((2, 2), dtype=np.float32))
    with pytest.raises(ValueError):
        seal_embedding([])
```

- [ ] **Step 3: Run test to verify it fails**

Run: `set -a && . .env && set +a && .venv/bin/python -m pytest src/lamto/gate/tests/test_crypto.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'lamto.gate.crypto'`

- [ ] **Step 4: Write the implementation**

Create `src/lamto/gate/crypto.py`:

```python
"""Encryption for stored face embeddings.

Vectors are float32, serialized with ``ndarray.tobytes()`` and sealed with
Fernet before they reach the database. The Fernet key is derived from
``GATE_EMBEDDING_KEY`` so an operator can set any sufficiently random string
instead of a base64-encoded 32-byte blob.

Database compromise *combined with* key compromise exposes biometric
identifiers. Encryption at rest is not a substitute for the retention rules;
it is the floor under them.
"""

import base64
import hashlib

import numpy as np
from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings

VECTOR_DTYPE = np.float32


class EmbeddingDecryptionError(RuntimeError):
    """Stored embedding could not be opened with the configured key."""


def _fernet() -> Fernet:
    digest = hashlib.sha256(settings.GATE_EMBEDDING_KEY.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def seal_embedding(vector) -> bytes:
    array = np.asarray(vector, dtype=VECTOR_DTYPE)
    if array.ndim != 1 or array.size == 0:
        raise ValueError("Embedding must be a non-empty 1-D vector.")
    return _fernet().encrypt(array.tobytes())


def open_embedding(sealed: bytes) -> np.ndarray:
    try:
        raw = _fernet().decrypt(bytes(sealed))
    except InvalidToken as error:
        raise EmbeddingDecryptionError("Embedding could not be decrypted.") from error
    return np.frombuffer(raw, dtype=VECTOR_DTYPE)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `set -a && . .env && set +a && .venv/bin/python -m pytest src/lamto/gate/tests/test_crypto.py -v`
Expected: PASS, 4 passed

- [ ] **Step 6: Commit**

```bash
git add src/lamto/gate/crypto.py src/lamto/gate/tests/test_crypto.py pyproject.toml
git commit -m "feat(gate): seal face embeddings with Fernet before storage"
```

---

### Task 4: Face embedder boundary and the test fake

**Files:**
- Create: `src/lamto/gate/embedding.py`, `src/lamto/gate/tests/fakes.py`
- Test: `src/lamto/gate/tests/test_embedding.py`

**Interfaces:**
- Consumes: `settings.GATE_FACE_EMBEDDER` (Task 2).
- Produces: `FaceEmbedder` Protocol with `embed(image_bytes: bytes) -> EmbeddingResult`; `EmbeddingResult(vector: list[float], model_name: str, model_version: str, detection_score: float)`; errors `FaceQualityError`, `NoFaceDetected`, `MultipleFacesDetected`, `FaceTooSmall`, `FaceTooBlurry`, `FaceEmbedderUnavailable`; `get_embedder()`. Test helpers `FakeEmbedder`, `fake_vector(seed)`, `FAKE_MODEL_NAME`, `FAKE_MODEL_VERSION`, `face_bytes(seed)`.

This is the seam that keeps a 326MB model out of CI. Nothing outside this module knows which model is in use.

- [ ] **Step 1: Write the failing test**

Create `src/lamto/gate/tests/test_embedding.py`:

```python
import numpy as np
import pytest

from lamto.gate.embedding import (
    FaceEmbedderUnavailable,
    MultipleFacesDetected,
    NoFaceDetected,
    get_embedder,
)
from lamto.gate.tests.fakes import FakeEmbedder, face_bytes, fake_vector

FAKE_PATH = "lamto.gate.tests.fakes.FakeEmbedder"


def test_get_embedder_loads_the_configured_class(settings):
    settings.GATE_FACE_EMBEDDER = FAKE_PATH
    assert isinstance(get_embedder(), FakeEmbedder)


def test_get_embedder_refuses_to_guess_when_unset(settings):
    settings.GATE_FACE_EMBEDDER = ""
    with pytest.raises(FaceEmbedderUnavailable):
        get_embedder()


def test_fake_is_deterministic_and_unit_length():
    result = FakeEmbedder().embed(face_bytes("nguyen"))
    again = FakeEmbedder().embed(face_bytes("nguyen"))
    assert result.vector == again.vector
    assert np.isclose(np.linalg.norm(np.array(result.vector)), 1.0)


def test_distinct_seeds_are_near_orthogonal():
    a = np.array(fake_vector("a"))
    b = np.array(fake_vector("b"))
    assert abs(float(np.dot(a, b))) < 0.2


def test_fake_signals_the_quality_failures():
    with pytest.raises(NoFaceDetected):
        FakeEmbedder().embed(b"NOFACE")
    with pytest.raises(MultipleFacesDetected):
        FakeEmbedder().embed(b"MANYFACES")
    with pytest.raises(NoFaceDetected):
        FakeEmbedder().embed(b"a random jpeg")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `set -a && . .env && set +a && .venv/bin/python -m pytest src/lamto/gate/tests/test_embedding.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'lamto.gate.embedding'`

- [ ] **Step 3: Write the boundary**

Create `src/lamto/gate/embedding.py`:

```python
"""Face embedding boundary: one image in, one L2-normalized vector out.

The production implementation loads InsightFace; tests bind a deterministic
fake through ``GATE_FACE_EMBEDDER`` so CI needs no model files and no
network. Nothing outside this module knows which model is in use, which is
also what makes a model swap a configuration change plus a re-enrolment
rather than a rewrite.

The quality errors below are an IMAGE-QUALITY gate. They establish that an
image is usable. They are not identity assurance and not liveness detection,
and must never be described or relied on as either.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from django.conf import settings
from django.utils.module_loading import import_string


class FaceQualityError(ValueError):
    """Image is unusable. ``code`` is the resident-facing machine code."""

    code = "gate_face_unusable"


class NoFaceDetected(FaceQualityError):
    code = "gate_no_face_detected"


class MultipleFacesDetected(FaceQualityError):
    code = "gate_multiple_faces"


class FaceTooSmall(FaceQualityError):
    code = "gate_face_too_small"


class FaceTooBlurry(FaceQualityError):
    code = "gate_face_too_blurry"


class FaceEmbedderUnavailable(RuntimeError):
    """The model is not configured, could not load, or failed to run."""


@dataclass(frozen=True)
class EmbeddingResult:
    vector: list[float]
    model_name: str
    model_version: str
    detection_score: float


class FaceEmbedder(Protocol):
    def embed(self, image_bytes: bytes) -> EmbeddingResult: ...


def get_embedder() -> FaceEmbedder:
    path = settings.GATE_FACE_EMBEDDER
    if not path:
        raise FaceEmbedderUnavailable(
            "GATE_FACE_EMBEDDER is not set; refusing to guess a face model."
        )
    return import_string(path)()
```

- [ ] **Step 4: Write the fake**

Create `src/lamto/gate/tests/fakes.py`:

```python
"""Deterministic embedder for tests: no model files, no network, no drift.

An image is a marker: ``b"FACE:<seed>"`` embeds as ``fake_vector(seed)``,
so a test controls similarity exactly. Use ``face_bytes(seed)`` to build one.
"""

import hashlib

import numpy as np

from lamto.gate.embedding import (
    EmbeddingResult,
    MultipleFacesDetected,
    NoFaceDetected,
)

FAKE_MODEL_NAME = "fake"
FAKE_MODEL_VERSION = "1"
VECTOR_SIZE = 512
_PREFIX = b"FACE:"


def face_bytes(seed: str) -> bytes:
    """Image bytes the fake embeds as ``fake_vector(seed)``."""
    return _PREFIX + seed.encode("utf-8")


def fake_vector(seed: str) -> list[float]:
    """Stable unit vector for a seed string."""
    rng = np.random.default_rng(
        int.from_bytes(hashlib.sha256(seed.encode("utf-8")).digest()[:8], "big")
    )
    vector = rng.standard_normal(VECTOR_SIZE).astype(np.float32)
    return (vector / np.linalg.norm(vector)).tolist()


class FakeEmbedder:
    def embed(self, image_bytes: bytes) -> EmbeddingResult:
        if image_bytes.startswith(b"NOFACE"):
            raise NoFaceDetected("No face in image.")
        if image_bytes.startswith(b"MANYFACES"):
            raise MultipleFacesDetected("More than one face in image.")
        if not image_bytes.startswith(_PREFIX):
            raise NoFaceDetected("No face in image.")
        seed = image_bytes[len(_PREFIX):].decode("utf-8", "replace")
        return EmbeddingResult(
            vector=fake_vector(seed),
            model_name=FAKE_MODEL_NAME,
            model_version=FAKE_MODEL_VERSION,
            detection_score=0.99,
        )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `set -a && . .env && set +a && .venv/bin/python -m pytest src/lamto/gate/tests/test_embedding.py -v`
Expected: PASS, 5 passed

- [ ] **Step 6: Commit**

```bash
git add src/lamto/gate/embedding.py src/lamto/gate/tests/fakes.py \
  src/lamto/gate/tests/test_embedding.py
git commit -m "feat(gate): add the face embedder boundary and a deterministic test fake"
```

---

### Task 5: Pending photo storage and resident submission

**Files:**
- Create: `src/lamto/gate/photos.py`, `src/lamto/gate/enrollment.py`
- Create: `src/lamto/gate/tests/conftest.py`
- Test: `src/lamto/gate/tests/test_enrollment.py`

**Interfaces:**
- Consumes: `normalize_plate`/`PlateFormatError` (Task 1); models (Task 2); `seal_embedding` (Task 3); `get_embedder`, `FaceQualityError` (Task 4); `scan_with_clamav` from `lamto.documents.scanner`.
- Produces:
  - `store_pending_photo(file_obj, content_type) -> tuple[str, str]` returning `(storage_key, provider_version_id)`
  - `delete_pending_photo(storage_key: str, provider_version_id: str = "") -> None`
  - `submit_face_enrollment(occupancy, uploaded_file, scanner=None) -> FaceEnrollment` (defaults to ClamAV, resolved at call time)
  - `submit_plate(occupancy, raw_plate: str) -> VehiclePlate`
  - `revoke_face_enrollment(occupancy) -> None`
  - `revoke_plate(occupancy, plate_id: int) -> None`
  - errors `PhotoRejected(ValueError)`, `PlateAlreadyRegistered(ValueError)`
  - fixtures `building`, `occupancy`, `second_occupancy`, `management`, `use_fake_embedder`, `gate_storage`

`lamto.documents` is deliberately not used for the review photo: `Document` rows are append-only at the database level and can never be deleted, and this photo must be deletable. The `scanner` is injected the same way `create_document_version` takes it, so tests do not need a live ClamAV.

- [ ] **Step 1: Write the shared fixtures**

Create `src/lamto/gate/tests/conftest.py`:

```python
import tempfile

import pytest

from lamto.accounts.models import (
    Building,
    ManagementMembership,
    ResidentOccupancy,
    Unit,
    User,
)

FAKE_EMBEDDER_PATH = "lamto.gate.tests.fakes.FakeEmbedder"


@pytest.fixture
def gate_storage(settings):
    """Filesystem private storage so photo put/delete is real but local."""
    location = tempfile.mkdtemp(prefix="lamto-gate-")
    settings.STORAGES = {
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {"location": location},
        },
        "private": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {"location": location},
        },
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    }
    return location


@pytest.fixture
def use_fake_embedder(settings):
    settings.GATE_FACE_EMBEDDER = FAKE_EMBEDDER_PATH
    settings.GATE_EMBEDDING_KEY = "gate-test-key"
    return FAKE_EMBEDDER_PATH


@pytest.fixture
def building(db):
    return Building.objects.create(name="Gate Test Building")


@pytest.fixture
def occupancy(building):
    unit = Unit.objects.create(building=building, label="12A")
    user = User.objects.create(email="resident@example.com", display_name="Nguyen A")
    return ResidentOccupancy.objects.create(user=user, unit=unit)


@pytest.fixture
def second_occupancy(building):
    unit = Unit.objects.create(building=building, label="14B")
    user = User.objects.create(email="second@example.com", display_name="Tran B")
    return ResidentOccupancy.objects.create(user=user, unit=unit)


@pytest.fixture
def management(building):
    user = User.objects.create(email="manager@example.com", display_name="Manager")
    return ManagementMembership.objects.create(user=user, building=building)


@pytest.fixture
def clean_scanner():
    """Stand-in for ClamAV that reports every file clean."""
    return lambda file_obj: True


@pytest.fixture
def infected_scanner():
    return lambda file_obj: False
```

- [ ] **Step 2: Write the failing test**

Create `src/lamto/gate/tests/test_enrollment.py`:

```python
import io
import os

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from lamto.gate.enrollment import (
    PhotoRejected,
    PlateAlreadyRegistered,
    revoke_face_enrollment,
    revoke_plate,
    submit_face_enrollment,
    submit_plate,
)
from lamto.gate.embedding import NoFaceDetected
from lamto.gate.models import (
    FaceEnrollment,
    PendingEnrollmentPhoto,
    ReviewStatus,
    VehiclePlate,
)
from lamto.gate.plates import PlateFormatError
from lamto.gate.tests.fakes import FAKE_MODEL_NAME, face_bytes

pytestmark = pytest.mark.django_db


def _upload(payload: bytes, content_type="image/jpeg"):
    return SimpleUploadedFile("face.jpg", payload, content_type=content_type)


def test_submitting_a_face_stores_a_sealed_vector_and_a_pending_photo(
    occupancy, use_fake_embedder, gate_storage, clean_scanner
):
    enrollment = submit_face_enrollment(
        occupancy, _upload(face_bytes("nguyen")), scanner=clean_scanner
    )
    assert enrollment.status == ReviewStatus.PENDING
    assert enrollment.model_name == FAKE_MODEL_NAME
    assert bytes(enrollment.embedding) != face_bytes("nguyen")
    photo = PendingEnrollmentPhoto.objects.get(enrollment=enrollment)
    assert photo.expires_at > enrollment.submitted_at
    assert os.path.exists(os.path.join(gate_storage, photo.storage_key))


def test_resubmitting_replaces_the_previous_pending_photo(
    occupancy, use_fake_embedder, gate_storage, clean_scanner
):
    first = submit_face_enrollment(
        occupancy, _upload(face_bytes("one")), scanner=clean_scanner
    )
    first_key = PendingEnrollmentPhoto.objects.get(enrollment=first).storage_key
    submit_face_enrollment(
        occupancy, _upload(face_bytes("two")), scanner=clean_scanner
    )
    assert PendingEnrollmentPhoto.objects.count() == 1
    assert not os.path.exists(os.path.join(gate_storage, first_key))


def test_an_infected_image_is_rejected_and_stores_nothing(
    occupancy, use_fake_embedder, gate_storage, infected_scanner
):
    with pytest.raises(PhotoRejected):
        submit_face_enrollment(
            occupancy, _upload(face_bytes("nguyen")), scanner=infected_scanner
        )
    assert not FaceEnrollment.objects.exists()
    assert not PendingEnrollmentPhoto.objects.exists()


def test_a_quality_failure_stores_nothing(
    occupancy, use_fake_embedder, gate_storage, clean_scanner
):
    with pytest.raises(NoFaceDetected):
        submit_face_enrollment(occupancy, _upload(b"NOFACE"), scanner=clean_scanner)
    assert not FaceEnrollment.objects.exists()
    assert not PendingEnrollmentPhoto.objects.exists()


def test_a_non_image_content_type_is_rejected(
    occupancy, use_fake_embedder, gate_storage, clean_scanner
):
    with pytest.raises(PhotoRejected):
        submit_face_enrollment(
            occupancy,
            _upload(face_bytes("x"), content_type="application/pdf"),
            scanner=clean_scanner,
        )


def test_an_oversized_image_is_rejected(
    occupancy, use_fake_embedder, gate_storage, clean_scanner, settings
):
    settings.GATE_MAX_FACE_UPLOAD_BYTES = 10
    with pytest.raises(PhotoRejected):
        submit_face_enrollment(
            occupancy, _upload(face_bytes("a-long-seed-value")), scanner=clean_scanner
        )


def test_revoking_a_face_removes_the_row_and_the_photo(
    occupancy, use_fake_embedder, gate_storage, clean_scanner
):
    enrollment = submit_face_enrollment(
        occupancy, _upload(face_bytes("nguyen")), scanner=clean_scanner
    )
    key = PendingEnrollmentPhoto.objects.get(enrollment=enrollment).storage_key
    revoke_face_enrollment(occupancy)
    assert not FaceEnrollment.objects.exists()
    assert not PendingEnrollmentPhoto.objects.exists()
    assert not os.path.exists(os.path.join(gate_storage, key))


def test_submitting_plates_normalizes_and_allows_several(occupancy):
    car = submit_plate(occupancy, "51F-123.45")
    bike = submit_plate(occupancy, "59x1 999.99")
    assert car.plate == "51F12345"
    assert bike.plate == "59X199999"
    assert VehiclePlate.objects.filter(occupancy=occupancy).count() == 2
    assert car.building_id == occupancy.unit.building_id


def test_resubmitting_the_same_plate_reuses_the_row(occupancy):
    first = submit_plate(occupancy, "51F12345")
    second = submit_plate(occupancy, "51f 123 45")
    assert first.pk == second.pk


def test_a_plate_approved_elsewhere_in_the_building_is_refused(
    occupancy, second_occupancy
):
    approved = submit_plate(second_occupancy, "51F12345")
    VehiclePlate.objects.filter(pk=approved.pk).update(status=ReviewStatus.APPROVED)
    with pytest.raises(PlateAlreadyRegistered):
        submit_plate(occupancy, "51F12345")


def test_an_unusable_plate_is_refused(occupancy):
    with pytest.raises(PlateFormatError):
        submit_plate(occupancy, "!!")


def test_revoking_a_plate_deletes_it(occupancy):
    plate = submit_plate(occupancy, "51F12345")
    revoke_plate(occupancy, plate.pk)
    assert not VehiclePlate.objects.filter(pk=plate.pk).exists()
```

- [ ] **Step 3: Run test to verify it fails**

Run: `set -a && . .env && set +a && .venv/bin/python -m pytest src/lamto/gate/tests/test_enrollment.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'lamto.gate.enrollment'`

- [ ] **Step 4: Write the photo storage module**

Create `src/lamto/gate/photos.py`:

```python
"""Short-lived storage for the pending enrolment photo.

Deliberately NOT ``lamto.documents``: Document rows are append-only at the
database level and can never be deleted, and this photo must be deletable
on decision or at expiry.

The private bucket is versioned. A plain ``storage.delete()`` on S3 writes a
delete marker and keeps the object, which would retain the photo forever, so
deletion names the version — the same rule ``purge_expired_quarantine``
follows in ``lamto/documents/services.py``.
"""

import uuid

from django.core.files.base import File
from django.core.files.storage import storages

PREFIX = "gate/pending-enrollment"


def _is_s3(storage) -> bool:
    return hasattr(storage, "bucket_name") and hasattr(storage, "connection")


def store_pending_photo(file_obj, content_type: str) -> tuple[str, str]:
    """Store the review image. Returns ``(storage_key, provider_version_id)``."""
    storage = storages["private"]
    key = f"{PREFIX}/{uuid.uuid4().hex}"
    file_obj.seek(0)
    if _is_s3(storage):
        response = storage.connection.meta.client.put_object(
            Bucket=storage.bucket_name,
            Key=key,
            Body=file_obj,
            ContentType=content_type,
        )
        version_id = response.get("VersionId") or ""
        return key, version_id
    return storage.save(key, File(file_obj, name=key)), ""


def delete_pending_photo(storage_key: str, provider_version_id: str = "") -> None:
    """Remove the object outright. A delete marker is not a deletion."""
    if not storage_key:
        return
    storage = storages["private"]
    if _is_s3(storage):
        client = storage.connection.meta.client
        if provider_version_id:
            client.delete_object(
                Bucket=storage.bucket_name,
                Key=storage_key,
                VersionId=provider_version_id,
            )
        else:
            client.delete_object(Bucket=storage.bucket_name, Key=storage_key)
        return
    storage.delete(storage_key)
```

- [ ] **Step 5: Write the enrolment module**

Create `src/lamto/gate/enrollment.py`:

```python
"""Resident-initiated enrolment: submit a face, claim a plate, revoke either.

Order matters in ``submit_face_enrollment``: validate, scan, and only then
embed. Unscanned bytes never reach the model. Nothing is written unless every
step succeeded, so a quality failure leaves no half-committed enrolment.
"""

import io
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from lamto.documents.scanner import scan_with_clamav

from .crypto import seal_embedding
from .embedding import get_embedder
from .models import (
    FaceEnrollment,
    PendingEnrollmentPhoto,
    ReviewStatus,
    VehiclePlate,
)
from .photos import delete_pending_photo, store_pending_photo
from .plates import normalize_plate

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png"}


class PhotoRejected(ValueError):
    """Upload refused before it reached the model."""


class PlateAlreadyRegistered(ValueError):
    """Another occupancy already holds this plate in the same building."""


def submit_face_enrollment(occupancy, uploaded_file, scanner=None):
    # Resolved at call time, not bound as a default: a default argument
    # captures the original function object and makes the module attribute
    # impossible to substitute in tests.
    scanner = scanner or scan_with_clamav
    content_type = getattr(uploaded_file, "content_type", "") or ""
    if content_type not in ALLOWED_IMAGE_TYPES:
        raise PhotoRejected("Only JPEG or PNG images are accepted.")
    data = uploaded_file.read()
    if len(data) > settings.GATE_MAX_FACE_UPLOAD_BYTES:
        raise PhotoRejected("Image is too large.")
    if not data:
        raise PhotoRejected("Image is empty.")
    if not scanner(io.BytesIO(data)):
        raise PhotoRejected("Image failed the malware scan.")

    # Raises FaceQualityError subclasses; nothing has been written yet.
    result = get_embedder().embed(data)

    now = timezone.now()
    with transaction.atomic():
        enrollment, _ = FaceEnrollment.objects.get_or_create(occupancy=occupancy)
        previous = PendingEnrollmentPhoto.objects.filter(enrollment=enrollment).first()
        if previous is not None:
            delete_pending_photo(previous.storage_key, previous.provider_version_id)
            previous.delete()
        enrollment.embedding = seal_embedding(result.vector)
        enrollment.model_name = result.model_name
        enrollment.model_version = result.model_version
        enrollment.status = ReviewStatus.PENDING
        enrollment.submitted_at = now
        enrollment.reviewed_by = None
        enrollment.reviewed_at = None
        enrollment.review_note = ""
        enrollment.save()
        key, version_id = store_pending_photo(io.BytesIO(data), content_type)
        PendingEnrollmentPhoto.objects.create(
            enrollment=enrollment,
            storage_key=key,
            provider_version_id=version_id,
            content_type=content_type,
            byte_size=len(data),
            expires_at=now + timedelta(hours=settings.GATE_ENROLLMENT_PHOTO_TTL_HOURS),
        )
    return enrollment


def revoke_face_enrollment(occupancy) -> None:
    """Resident-initiated deletion. The vector and the photo both go."""
    with transaction.atomic():
        enrollment = FaceEnrollment.objects.filter(occupancy=occupancy).first()
        if enrollment is None:
            return
        photo = PendingEnrollmentPhoto.objects.filter(enrollment=enrollment).first()
        if photo is not None:
            delete_pending_photo(photo.storage_key, photo.provider_version_id)
        enrollment.delete()


def submit_plate(occupancy, raw_plate: str) -> VehiclePlate:
    plate = normalize_plate(raw_plate)
    building = occupancy.unit.building
    taken = (
        VehiclePlate.objects.filter(
            building=building, plate=plate, status=ReviewStatus.APPROVED
        )
        .exclude(occupancy=occupancy)
        .exists()
    )
    if taken:
        # Deliberately does not name the holding unit: staff see the collision,
        # a resident does not get a lookup oracle.
        raise PlateAlreadyRegistered("Plate is already registered in this building.")
    now = timezone.now()
    obj, created = VehiclePlate.objects.get_or_create(
        occupancy=occupancy,
        plate=plate,
        defaults={"building": building, "submitted_at": now},
    )
    if not created and obj.status == ReviewStatus.REJECTED:
        obj.status = ReviewStatus.PENDING
        obj.submitted_at = now
        obj.reviewed_by = None
        obj.reviewed_at = None
        obj.review_note = ""
        obj.save()
    return obj


def revoke_plate(occupancy, plate_id: int) -> None:
    VehiclePlate.objects.filter(occupancy=occupancy, pk=plate_id).delete()
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `set -a && . .env && set +a && .venv/bin/python -m pytest src/lamto/gate/tests/test_enrollment.py -v`
Expected: PASS, 12 passed

- [ ] **Step 7: Commit**

```bash
git add src/lamto/gate/photos.py src/lamto/gate/enrollment.py \
  src/lamto/gate/tests/conftest.py src/lamto/gate/tests/test_enrollment.py
git commit -m "feat(gate): let residents submit and revoke plates and a face enrolment"
```

---

### Task 6: Manager review decisions

**Files:**
- Create: `src/lamto/gate/review.py`
- Test: `src/lamto/gate/tests/test_review.py`

**Interfaces:**
- Consumes: models (Task 2), `delete_pending_photo` (Task 5).
- Produces: `approve_face(enrollment, membership)`, `reject_face(enrollment, membership, note)`, `approve_plate(plate, membership)`, `reject_plate(plate, membership, note)`, `revoke_face(enrollment, membership)`, `revoke_plate_as_manager(plate, membership)`; errors `ReviewNotPermitted(PermissionDenied)`, `ReviewNotPossible(ValueError)`.

Approval requires the pending photo to still exist. This is the only identity check in the whole system, and a manager who cannot see the photo has not performed it.

- [ ] **Step 1: Write the failing test**

Create `src/lamto/gate/tests/test_review.py`:

```python
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from lamto.accounts.models import Building, ManagementMembership, User
from lamto.gate.enrollment import submit_face_enrollment, submit_plate
from lamto.gate.models import PendingEnrollmentPhoto, ReviewStatus, VehiclePlate
from lamto.gate.review import (
    ReviewNotPermitted,
    ReviewNotPossible,
    approve_face,
    approve_plate,
    reject_face,
    reject_plate,
    revoke_face,
)
from lamto.gate.tests.fakes import face_bytes

pytestmark = pytest.mark.django_db


def _enrol(occupancy, clean_scanner, seed="nguyen"):
    return submit_face_enrollment(
        occupancy,
        SimpleUploadedFile("f.jpg", face_bytes(seed), content_type="image/jpeg"),
        scanner=clean_scanner,
    )


def test_approving_a_face_keeps_the_vector_and_deletes_the_photo(
    occupancy, management, use_fake_embedder, gate_storage, clean_scanner
):
    enrollment = _enrol(occupancy, clean_scanner)
    approve_face(enrollment, management)
    enrollment.refresh_from_db()
    assert enrollment.status == ReviewStatus.APPROVED
    assert enrollment.embedding is not None
    assert enrollment.reviewed_by_id == management.user_id
    assert enrollment.reviewed_at is not None
    assert not PendingEnrollmentPhoto.objects.exists()


def test_rejecting_a_face_deletes_the_vector_and_keeps_the_reason(
    occupancy, management, use_fake_embedder, gate_storage, clean_scanner
):
    enrollment = _enrol(occupancy, clean_scanner)
    reject_face(enrollment, management, "Face not clearly visible.")
    enrollment.refresh_from_db()
    assert enrollment.status == ReviewStatus.REJECTED
    assert enrollment.embedding is None
    assert enrollment.review_note == "Face not clearly visible."
    assert not PendingEnrollmentPhoto.objects.exists()


def test_rejecting_requires_a_reason(
    occupancy, management, use_fake_embedder, gate_storage, clean_scanner
):
    enrollment = _enrol(occupancy, clean_scanner)
    with pytest.raises(ReviewNotPossible):
        reject_face(enrollment, management, "   ")


def test_a_face_cannot_be_approved_once_the_photo_is_gone(
    occupancy, management, use_fake_embedder, gate_storage, clean_scanner
):
    enrollment = _enrol(occupancy, clean_scanner)
    PendingEnrollmentPhoto.objects.filter(enrollment=enrollment).delete()
    with pytest.raises(ReviewNotPossible):
        approve_face(enrollment, management)


def test_a_manager_from_another_building_cannot_decide(
    occupancy, use_fake_embedder, gate_storage, clean_scanner
):
    other_building = Building.objects.create(name="Other Building")
    outsider = ManagementMembership.objects.create(
        user=User.objects.create(email="out@example.com", display_name="Out"),
        building=other_building,
    )
    enrollment = _enrol(occupancy, clean_scanner)
    with pytest.raises(ReviewNotPermitted):
        approve_face(enrollment, outsider)


def test_revoking_an_approved_face_deletes_the_vector(
    occupancy, management, use_fake_embedder, gate_storage, clean_scanner
):
    enrollment = _enrol(occupancy, clean_scanner)
    approve_face(enrollment, management)
    revoke_face(enrollment, management)
    enrollment.refresh_from_db()
    assert enrollment.status == ReviewStatus.REJECTED
    assert enrollment.embedding is None


def test_approving_a_plate_marks_it_and_attributes_the_decision(
    occupancy, management
):
    plate = submit_plate(occupancy, "51F12345")
    approve_plate(plate, management)
    plate.refresh_from_db()
    assert plate.status == ReviewStatus.APPROVED
    assert plate.reviewed_by_id == management.user_id


def test_approving_a_plate_another_resident_already_holds_fails(
    occupancy, second_occupancy, management
):
    first = submit_plate(second_occupancy, "51F12345")
    approve_plate(first, management)
    # submit_plate refuses this earlier, so create the row directly: the point
    # is that approval is the second line of defence, not the only one.
    clash = VehiclePlate.objects.create(
        occupancy=occupancy, building=occupancy.unit.building, plate="51F12345"
    )
    with pytest.raises(ReviewNotPossible):
        approve_plate(clash, management)


def test_rejecting_a_plate_records_the_reason(occupancy, management):
    plate = submit_plate(occupancy, "51F12345")
    reject_plate(plate, management, "Not a resident vehicle.")
    plate.refresh_from_db()
    assert plate.status == ReviewStatus.REJECTED
    assert plate.review_note == "Not a resident vehicle."
```

- [ ] **Step 2: Run test to verify it fails**

Run: `set -a && . .env && set +a && .venv/bin/python -m pytest src/lamto/gate/tests/test_review.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'lamto.gate.review'`

- [ ] **Step 3: Write the implementation**

Create `src/lamto/gate/review.py`:

```python
"""Manager decisions on gate registrations.

Every decision is attributed to a named manager, which is the product's
standing rule: automation may propose, a person decides. For a face this is
not decoration — the manager comparing the pending photo against the resident
record is the ONLY identity assurance in the system. There is no liveness
detection anywhere.
"""

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from .models import PendingEnrollmentPhoto, ReviewStatus, VehiclePlate
from .photos import delete_pending_photo


class ReviewNotPermitted(PermissionDenied):
    """The membership does not manage the registration's building."""


class ReviewNotPossible(ValueError):
    """The decision cannot be recorded in the registration's current state."""


def _assert_manages(membership, building_id: int) -> None:
    if membership.building_id != building_id or not membership.active:
        raise ReviewNotPermitted("Registration belongs to another building.")


def _drop_photo(enrollment) -> None:
    photo = PendingEnrollmentPhoto.objects.filter(enrollment=enrollment).first()
    if photo is None:
        return
    delete_pending_photo(photo.storage_key, photo.provider_version_id)
    photo.delete()


def approve_face(enrollment, membership):
    _assert_manages(membership, enrollment.occupancy.unit.building_id)
    if enrollment.status != ReviewStatus.PENDING:
        raise ReviewNotPossible("Only a pending enrolment can be approved.")
    if not PendingEnrollmentPhoto.objects.filter(enrollment=enrollment).exists():
        raise ReviewNotPossible(
            "The review photo has expired; the resident must resubmit."
        )
    with transaction.atomic():
        enrollment.status = ReviewStatus.APPROVED
        enrollment.reviewed_by = membership.user
        enrollment.reviewed_at = timezone.now()
        enrollment.review_note = ""
        enrollment.save(
            update_fields=["status", "reviewed_by", "reviewed_at", "review_note"]
        )
        _drop_photo(enrollment)
    return enrollment


def reject_face(enrollment, membership, note: str):
    _assert_manages(membership, enrollment.occupancy.unit.building_id)
    if not (note or "").strip():
        raise ReviewNotPossible("A rejection reason is required.")
    if enrollment.status not in {ReviewStatus.PENDING, ReviewStatus.APPROVED}:
        raise ReviewNotPossible("This enrolment has already been closed.")
    return _close_face(enrollment, membership, note.strip())


def revoke_face(enrollment, membership):
    """Manager-initiated removal of a live enrolment."""
    _assert_manages(membership, enrollment.occupancy.unit.building_id)
    return _close_face(enrollment, membership, "Revoked by management.")


def _close_face(enrollment, membership, note: str):
    with transaction.atomic():
        enrollment.status = ReviewStatus.REJECTED
        enrollment.embedding = None
        enrollment.reviewed_by = membership.user
        enrollment.reviewed_at = timezone.now()
        enrollment.review_note = note[:255]
        enrollment.save(
            update_fields=[
                "status",
                "embedding",
                "reviewed_by",
                "reviewed_at",
                "review_note",
            ]
        )
        _drop_photo(enrollment)
    return enrollment


def approve_plate(plate, membership):
    _assert_manages(membership, plate.building_id)
    if plate.status == ReviewStatus.APPROVED:
        return plate
    clash = (
        VehiclePlate.objects.filter(
            building_id=plate.building_id,
            plate=plate.plate,
            status=ReviewStatus.APPROVED,
        )
        .exclude(pk=plate.pk)
        .exists()
    )
    if clash:
        raise ReviewNotPossible(
            "Another resident already holds this plate in this building."
        )
    plate.status = ReviewStatus.APPROVED
    plate.reviewed_by = membership.user
    plate.reviewed_at = timezone.now()
    plate.review_note = ""
    plate.save(update_fields=["status", "reviewed_by", "reviewed_at", "review_note"])
    return plate


def reject_plate(plate, membership, note: str):
    _assert_manages(membership, plate.building_id)
    if not (note or "").strip():
        raise ReviewNotPossible("A rejection reason is required.")
    plate.status = ReviewStatus.REJECTED
    plate.reviewed_by = membership.user
    plate.reviewed_at = timezone.now()
    plate.review_note = note.strip()[:255]
    plate.save(update_fields=["status", "reviewed_by", "reviewed_at", "review_note"])
    return plate


def revoke_plate_as_manager(plate, membership):
    return reject_plate(plate, membership, "Revoked by management.")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `set -a && . .env && set +a && .venv/bin/python -m pytest src/lamto/gate/tests/test_review.py -v`
Expected: PASS, 9 passed

- [ ] **Step 5: Commit**

```bash
git add src/lamto/gate/review.py src/lamto/gate/tests/test_review.py
git commit -m "feat(gate): record manager decisions and drop the review photo on decide"
```

---

### Task 7: Retention purge, the hourly command, and the ops heartbeat

**Files:**
- Create: `src/lamto/gate/retention.py`
- Create: `src/lamto/gate/management/__init__.py`, `src/lamto/gate/management/commands/__init__.py`, `src/lamto/gate/management/commands/purge_gate_data.py`
- Modify: `src/lamto/web/views/health.py` (`collect_health_snapshot`, ~line 29)
- Modify: `src/lamto/web/templates/web/staff/ops_health.html`
- Modify: `ops/deployment-checklist.md`
- Test: `src/lamto/gate/tests/test_retention.py`

**Interfaces:**
- Consumes: models (Task 2), `delete_pending_photo` (Task 5).
- Produces: `purge_expired_gate_events(now=None) -> int`, `purge_expired_enrollment_photos(now=None) -> int`, `record_purge_success(*, events: int, photos: int) -> GatePurgeHeartbeat`, `purge_is_stale(now=None) -> bool`, `PURGE_STALE_AFTER_HOURS = 2`, management command `purge_gate_data`.

Two expiries, two settings, two queries, and no shared code path. The event retention knob and the photo TTL knob must never be able to move each other.

- [ ] **Step 1: Write the failing test**

Create `src/lamto/gate/tests/test_retention.py`:

```python
import os
from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.utils import timezone

from lamto.gate.enrollment import submit_face_enrollment
from lamto.gate.models import (
    FaceEnrollment,
    GateDevice,
    GateEvent,
    GatePurgeHeartbeat,
    PendingEnrollmentPhoto,
    ReviewStatus,
)
from lamto.gate.retention import (
    purge_expired_enrollment_photos,
    purge_expired_gate_events,
    purge_is_stale,
)
from lamto.gate.tests.fakes import face_bytes

pytestmark = pytest.mark.django_db


def _device(building):
    return GateDevice.objects.create(
        building=building, label="North gate", direction=GateDevice.Direction.ENTRY
    )


def _event(building, *, age_hours: float, occupancy=None):
    device = _device(building)
    return GateEvent.objects.create(
        building=building,
        device=device,
        kind=GateEvent.Kind.FACE,
        direction=device.direction,
        occurred_at=timezone.now() - timedelta(hours=age_hours),
        matched_occupancy=occupancy,
        model_name="fake",
        model_version="1",
        match_metric="cosine",
        threshold_used=0.38,
        match_score=0.91,
    )


def test_an_event_inside_the_window_survives(building, occupancy):
    _event(building, age_hours=23, occupancy=occupancy)
    assert purge_expired_gate_events() == 0
    assert GateEvent.objects.count() == 1


def test_an_event_past_the_window_is_deleted_whole(building, occupancy):
    _event(building, age_hours=24.5, occupancy=occupancy)
    assert purge_expired_gate_events() == 1
    assert not GateEvent.objects.exists()


def test_the_practical_window_is_24_to_25_hours(building, occupancy):
    _event(building, age_hours=24.9, occupancy=occupancy)
    _event(building, age_hours=23.9, occupancy=occupancy)
    assert purge_expired_gate_events() == 1
    remaining = GateEvent.objects.get()
    assert (timezone.now() - remaining.occurred_at) < timedelta(hours=24)


def test_retention_hours_is_configurable(building, occupancy, settings):
    settings.GATE_EVENT_RETENTION_HOURS = 1
    _event(building, age_hours=2, occupancy=occupancy)
    assert purge_expired_gate_events() == 1


def test_purge_leaves_nothing_that_references_the_event(building, occupancy):
    from django.apps import apps

    _event(building, age_hours=48, occupancy=occupancy)
    purge_expired_gate_events()
    assert not GateEvent.objects.exists()
    # No related record may preserve enough to reconstruct an expired event.
    audit_event = apps.get_model("audit", "AuditEvent")
    assert not audit_event.objects.filter(action__startswith="gate.recognition").exists()


def test_expired_photo_expires_the_enrolment_and_drops_the_vector(
    occupancy, use_fake_embedder, gate_storage, clean_scanner
):
    enrollment = submit_face_enrollment(
        occupancy,
        SimpleUploadedFile("f.jpg", face_bytes("nguyen"), content_type="image/jpeg"),
        scanner=clean_scanner,
    )
    photo = PendingEnrollmentPhoto.objects.get(enrollment=enrollment)
    key = photo.storage_key
    PendingEnrollmentPhoto.objects.filter(pk=photo.pk).update(
        expires_at=timezone.now() - timedelta(minutes=1)
    )

    assert purge_expired_enrollment_photos() == 1

    enrollment.refresh_from_db()
    assert enrollment.status == ReviewStatus.EXPIRED
    assert enrollment.embedding is None
    assert not PendingEnrollmentPhoto.objects.exists()
    assert not os.path.exists(os.path.join(gate_storage, key))


def test_a_live_photo_is_left_alone(
    occupancy, use_fake_embedder, gate_storage, clean_scanner
):
    submit_face_enrollment(
        occupancy,
        SimpleUploadedFile("f.jpg", face_bytes("nguyen"), content_type="image/jpeg"),
        scanner=clean_scanner,
    )
    assert purge_expired_enrollment_photos() == 0
    assert FaceEnrollment.objects.get().status == ReviewStatus.PENDING


def test_the_two_lifecycles_do_not_share_a_knob(
    building, occupancy, use_fake_embedder, gate_storage, clean_scanner, settings
):
    settings.GATE_EVENT_RETENTION_HOURS = 1
    settings.GATE_ENROLLMENT_PHOTO_TTL_HOURS = 999
    submit_face_enrollment(
        occupancy,
        SimpleUploadedFile("f.jpg", face_bytes("nguyen"), content_type="image/jpeg"),
        scanner=clean_scanner,
    )
    _event(building, age_hours=2, occupancy=occupancy)
    assert purge_expired_gate_events() == 1
    assert purge_expired_enrollment_photos() == 0


def test_the_command_purges_and_records_a_heartbeat(building, occupancy):
    _event(building, age_hours=48, occupancy=occupancy)
    call_command("purge_gate_data")
    assert not GateEvent.objects.exists()
    heartbeat = GatePurgeHeartbeat.objects.get()
    assert heartbeat.events_deleted == 1
    assert not purge_is_stale()


def test_a_missing_heartbeat_reads_as_stale(db):
    assert purge_is_stale() is True


def test_an_old_heartbeat_reads_as_stale(db):
    GatePurgeHeartbeat.objects.create(
        last_success_at=timezone.now() - timedelta(hours=3)
    )
    assert purge_is_stale() is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `set -a && . .env && set +a && .venv/bin/python -m pytest src/lamto/gate/tests/test_retention.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'lamto.gate.retention'`

- [ ] **Step 3: Write the retention module**

Create `src/lamto/gate/retention.py`:

```python
"""Retention: the rule that keeps this subsystem from being surveillance.

Two independent expiries, deliberately never sharing a query or a setting:

* ``GateEvent`` rows older than ``GATE_EVENT_RETENTION_HOURS`` are deleted
  WHOLE. Nothing is nulled out, anonymized, or archived. The matched person,
  matched plate, raw and normalized plate text, score, model metadata, device,
  direction, and timestamps all go with the row.
* ``PendingEnrollmentPhoto`` rows past ``expires_at`` take their storage
  object, the unapproved embedding, and the enrolment's PENDING status with
  them. An unreviewed vector is never retained past the photo that justified
  it.

Because the job runs hourly, an event is eligible at ``occurred_at + 24h``
and gone at the next run: a practical window of 24-25 hours. The extra hour
is a property of hourly scheduling, not of the retention value.

No aggregate metrics are retained. The constraint that they be untraceable to
any resident, vehicle, device event, or individual timestamp leaves too little
to be worth keeping.
"""

from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import (
    GateEvent,
    GatePurgeHeartbeat,
    PendingEnrollmentPhoto,
    ReviewStatus,
)
from .photos import delete_pending_photo

PURGE_STALE_AFTER_HOURS = 2


def purge_expired_gate_events(now=None) -> int:
    now = now or timezone.now()
    cutoff = now - timedelta(hours=settings.GATE_EVENT_RETENTION_HOURS)
    deleted, _ = GateEvent.objects.filter(occurred_at__lt=cutoff).delete()
    return deleted


def purge_expired_enrollment_photos(now=None) -> int:
    now = now or timezone.now()
    expired = list(
        PendingEnrollmentPhoto.objects.filter(expires_at__lte=now).select_related(
            "enrollment"
        )
    )
    for photo in expired:
        delete_pending_photo(photo.storage_key, photo.provider_version_id)
        with transaction.atomic():
            enrollment = photo.enrollment
            if enrollment.status == ReviewStatus.PENDING:
                enrollment.status = ReviewStatus.EXPIRED
                enrollment.embedding = None
                enrollment.save(update_fields=["status", "embedding"])
            photo.delete()
    return len(expired)


def record_purge_success(*, events: int, photos: int) -> GatePurgeHeartbeat:
    heartbeat = GatePurgeHeartbeat.objects.order_by("pk").first()
    values = {
        "last_success_at": timezone.now(),
        "events_deleted": events,
        "photos_deleted": photos,
    }
    if heartbeat is None:
        return GatePurgeHeartbeat.objects.create(**values)
    for field, value in values.items():
        setattr(heartbeat, field, value)
    heartbeat.save(update_fields=list(values))
    return heartbeat


def purge_is_stale(now=None) -> bool:
    """True when the retention job has not succeeded recently.

    A missing heartbeat counts as stale: never having run is not evidence of
    health. The timestamp of a successful job run identifies nobody.
    """
    now = now or timezone.now()
    heartbeat = GatePurgeHeartbeat.objects.order_by("-last_success_at").first()
    if heartbeat is None:
        return True
    return heartbeat.last_success_at < now - timedelta(hours=PURGE_STALE_AFTER_HOURS)
```

- [ ] **Step 4: Write the management command**

```bash
mkdir -p src/lamto/gate/management/commands
touch src/lamto/gate/management/__init__.py src/lamto/gate/management/commands/__init__.py
```

Create `src/lamto/gate/management/commands/purge_gate_data.py`:

```python
"""Hourly retention job for the gate subsystem.

Run every hour. Purge failure is a retention breach, so this exits non-zero
and does NOT write the heartbeat when anything goes wrong; the ops health
panel reports a stale heartbeat within two hours.
"""

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from lamto.gate.models import GateEvent, PendingEnrollmentPhoto
from lamto.gate.retention import (
    purge_expired_enrollment_photos,
    purge_expired_gate_events,
    record_purge_success,
)


class Command(BaseCommand):
    help = (
        "Delete gate events past GATE_EVENT_RETENTION_HOURS and pending "
        "enrolment photos past GATE_ENROLLMENT_PHOTO_TTL_HOURS. Run hourly."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report candidates without deleting or recording a heartbeat.",
        )

    def handle(self, *args, **options):
        if options["dry_run"]:
            from datetime import timedelta

            from django.conf import settings

            cutoff = timezone.now() - timedelta(
                hours=settings.GATE_EVENT_RETENTION_HOURS
            )
            events = GateEvent.objects.filter(occurred_at__lt=cutoff).count()
            photos = PendingEnrollmentPhoto.objects.filter(
                expires_at__lte=timezone.now()
            ).count()
            self.stdout.write(
                f"dry_run gate_events_candidate={events} "
                f"enrollment_photos_candidate={photos}"
            )
            return

        try:
            events = purge_expired_gate_events()
            photos = purge_expired_enrollment_photos()
        except Exception as error:
            raise CommandError(f"gate retention purge failed: {error}") from error

        record_purge_success(events=events, photos=photos)
        self.stdout.write(
            f"gate_events_deleted={events} enrollment_photos_deleted={photos}"
        )
```

- [ ] **Step 5: Surface the heartbeat on the ops health panel**

In `src/lamto/web/views/health.py`, add to the imports:

```python
from lamto.gate.retention import PURGE_STALE_AFTER_HOURS, purge_is_stale
from lamto.gate.models import GatePurgeHeartbeat
```

Inside `collect_health_snapshot`, before the return, add:

```python
    gate_heartbeat = GatePurgeHeartbeat.objects.order_by("-last_success_at").first()
```

and add these keys to the returned dict:

```python
        "gate_purge_last_success_at": (
            gate_heartbeat.last_success_at if gate_heartbeat else None
        ),
        "gate_purge_stale": purge_is_stale(now),
        "gate_purge_stale_after_hours": PURGE_STALE_AFTER_HOURS,
```

In `src/lamto/web/templates/web/staff/ops_health.html`, add a row inside the existing panel list:

```html
<div class="health-row">
  <span class="health-label">{% trans "Gate retention purge" %}</span>
  {% if gate_purge_stale %}
  <span class="status-pill status-pill-mismatch">{% trans "Stale" %}</span>
  <p class="health-detail">
    {% blocktrans with hours=gate_purge_stale_after_hours %}No successful purge in the last {{ hours }} hours. Gate events may be past their retention window.{% endblocktrans %}
  </p>
  {% else %}
  <span class="status-pill status-pill-verified">{% trans "Current" %}</span>
  <p class="health-detail">{{ gate_purge_last_success_at }}</p>
  {% endif %}
</div>
```

- [ ] **Step 6: Document the cron entry**

Add to `ops/deployment-checklist.md`, in the scheduled-jobs section:

```markdown
- **Hourly:** `manage.py purge_gate_data` — gate event retention and pending
  enrolment photo TTL. This is a privacy control, not housekeeping: if it stops
  running, gate events outlive their 24-hour window. `/s/ops/health/` shows the
  purge as Stale within two hours of a missed run. A non-zero exit means the
  purge did not complete and the heartbeat was not written.
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `set -a && . .env && set +a && .venv/bin/python -m pytest src/lamto/gate/tests/test_retention.py -v`
Expected: PASS, 11 passed

- [ ] **Step 8: Run the whole gate suite**

Run: `set -a && . .env && set +a && .venv/bin/python -m pytest src/lamto/gate -v`
Expected: PASS, 47 passed

- [ ] **Step 9: Commit**

```bash
git add src/lamto/gate/retention.py src/lamto/gate/management/ \
  src/lamto/gate/tests/test_retention.py src/lamto/web/views/health.py \
  src/lamto/web/templates/web/staff/ops_health.html ops/deployment-checklist.md
git commit -m "feat(gate): purge expired events and enrolment photos hourly"
```

---

### Task 8: Reader credentials

**Files:**
- Create: `src/lamto/gate/devices.py`
- Test: `src/lamto/gate/tests/test_devices.py`

**Interfaces:**
- Consumes: models (Task 2); `assert_not_throttled`, `record_auth_failure`, `reset_auth_throttle` from `lamto.accounts.security`.
- Produces: `issue_credential(device, membership) -> tuple[GateDeviceCredential, str]`, `rotate_credential(device, membership, grace_hours=None) -> tuple[GateDeviceCredential, str]`, `revoke_credential(credential, membership) -> GateDeviceCredential`, `authenticate_device(token, ip=None) -> GateDeviceCredential`, `token_from_header(value) -> str`, errors `GateAuthenticationFailed`, `GateCredentialRevoked`, `GateCredentialExpired` (each carrying a `code`), `AUTH_SCHEME = "GateDevice"`.

The plaintext token is returned once at issue and never stored. Throttling keys on the caller's IP, not on the presented token — otherwise an attacker rotating random tokens would never trip a bucket.

- [ ] **Step 1: Write the failing test**

Create `src/lamto/gate/tests/test_devices.py`:

```python
from datetime import timedelta

import pytest
from django.core.exceptions import PermissionDenied
from django.utils import timezone

from lamto.gate.devices import (
    GateAuthenticationFailed,
    GateCredentialExpired,
    GateCredentialRevoked,
    authenticate_device,
    issue_credential,
    revoke_credential,
    rotate_credential,
    token_from_header,
)
from lamto.gate.models import GateDevice, GateDeviceCredential

pytestmark = pytest.mark.django_db


@pytest.fixture
def device(building):
    return GateDevice.objects.create(
        building=building, label="North gate", direction=GateDevice.Direction.ENTRY
    )


def test_issue_returns_a_token_that_is_not_stored(device, management):
    credential, token = issue_credential(device, management)
    assert token
    assert token not in credential.token_sha256
    assert len(credential.token_sha256) == 64
    assert authenticate_device(token).pk == credential.pk


def test_authenticate_records_the_hour_the_reader_was_last_seen(device, management):
    _, token = issue_credential(device, management)
    authenticate_device(token)
    device.refresh_from_db()
    assert device.last_seen_hour is not None
    assert device.last_seen_hour.minute == 0
    assert device.last_seen_hour.second == 0
    assert device.last_seen_hour.microsecond == 0


def test_rotation_keeps_the_old_credential_alive_during_the_grace(
    device, management, settings
):
    settings.GATE_CREDENTIAL_ROTATION_GRACE_HOURS = 24
    _, old = issue_credential(device, management)
    _, new = rotate_credential(device, management)
    assert authenticate_device(old) is not None
    assert authenticate_device(new) is not None


def test_rotation_with_zero_grace_invalidates_the_old_token_at_once(
    device, management, settings
):
    settings.GATE_CREDENTIAL_ROTATION_GRACE_HOURS = 0
    _, old = issue_credential(device, management)
    _, new = rotate_credential(device, management)
    with pytest.raises(GateCredentialExpired):
        authenticate_device(old)
    assert authenticate_device(new) is not None


def test_the_old_credential_dies_when_the_grace_elapses(device, management, settings):
    settings.GATE_CREDENTIAL_ROTATION_GRACE_HOURS = 1
    credential, old = issue_credential(device, management)
    rotate_credential(device, management)
    GateDeviceCredential.objects.filter(pk=credential.pk).update(
        expires_at=timezone.now() - timedelta(minutes=1)
    )
    with pytest.raises(GateCredentialExpired):
        authenticate_device(old)


def test_revocation_is_immediate_and_has_no_grace(device, management):
    credential, token = issue_credential(device, management)
    revoke_credential(credential, management)
    with pytest.raises(GateCredentialRevoked):
        authenticate_device(token)


def test_an_unknown_token_does_not_reveal_whether_a_device_exists(device, management):
    issue_credential(device, management)
    with pytest.raises(GateAuthenticationFailed) as caught:
        authenticate_device("not-a-real-token")
    assert caught.value.code == "gate_device_unauthenticated"
    assert not isinstance(caught.value, (GateCredentialRevoked, GateCredentialExpired))


def test_a_deactivated_device_cannot_authenticate(device, management):
    _, token = issue_credential(device, management)
    GateDevice.objects.filter(pk=device.pk).update(active=False)
    with pytest.raises(GateAuthenticationFailed):
        authenticate_device(token)


def test_repeated_failures_from_one_address_are_throttled(device, management):
    for _ in range(5):
        with pytest.raises(GateAuthenticationFailed):
            authenticate_device("wrong", ip="203.0.113.7")
    with pytest.raises(PermissionDenied):
        authenticate_device("wrong", ip="203.0.113.7")


def test_header_parsing():
    assert token_from_header("GateDevice abc123") == "abc123"
    assert token_from_header("gatedevice abc123") == "abc123"
    assert token_from_header("Token abc123") == ""
    assert token_from_header("") == ""
    assert token_from_header(None) == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `set -a && . .env && set +a && .venv/bin/python -m pytest src/lamto/gate/tests/test_devices.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'lamto.gate.devices'`

- [ ] **Step 3: Write the implementation**

Create `src/lamto/gate/devices.py`:

```python
"""Reader credentials: issue, rotate, revoke, authenticate.

Only the SHA-256 digest of a token is stored. The token itself is
high-entropy random rather than a chosen secret, so a plain digest is the
right primitive here and a password KDF is not.

Rotation and revocation are different operations on purpose. Rotation is
planned key hygiene and keeps the previous credential alive for
``GATE_CREDENTIAL_ROTATION_GRACE_HOURS`` so a device is reconfigured without
a lockout window; a grace of 0 invalidates it immediately. Revocation is for
a lost or compromised reader and takes effect on the next request, because a
grace period on a compromised device defeats the point.

The credential authenticates the DEVICE, not the read. A compromised reader
can post any plate string it likes; events record what a device claimed.
"""

import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from lamto.accounts.security import (
    assert_not_throttled,
    record_auth_failure,
    reset_auth_throttle,
)

from .models import GateDevice, GateDeviceCredential

AUTH_SCHEME = "GateDevice"
TOKEN_BYTES = 32
# Throttle on the caller's address, not the presented token: an attacker
# trying random tokens would otherwise land in a fresh bucket every attempt.
_THROTTLE_ACCOUNT = "gate_device"


class GateAuthenticationFailed(Exception):
    code = "gate_device_unauthenticated"


class GateCredentialRevoked(GateAuthenticationFailed):
    code = "gate_device_revoked"


class GateCredentialExpired(GateAuthenticationFailed):
    code = "gate_device_expired"


def _digest(token: str) -> str:
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


def token_from_header(value: str | None) -> str:
    parts = (value or "").split()
    if len(parts) != 2 or parts[0].lower() != AUTH_SCHEME.lower():
        return ""
    return parts[1]


def issue_credential(device, membership) -> tuple[GateDeviceCredential, str]:
    """Create a credential. The plaintext token is shown once and never again."""
    token = secrets.token_urlsafe(TOKEN_BYTES)
    credential = GateDeviceCredential.objects.create(
        device=device, token_sha256=_digest(token), created_by=membership.user
    )
    return credential, token


def rotate_credential(
    device, membership, *, grace_hours: int | None = None
) -> tuple[GateDeviceCredential, str]:
    grace = (
        settings.GATE_CREDENTIAL_ROTATION_GRACE_HOURS
        if grace_hours is None
        else grace_hours
    )
    expiry = timezone.now() + timedelta(hours=grace)
    with transaction.atomic():
        GateDeviceCredential.objects.filter(
            device=device, revoked_at__isnull=True
        ).filter(Q(expires_at__isnull=True) | Q(expires_at__gt=expiry)).update(
            expires_at=expiry
        )
        return issue_credential(device, membership)


def revoke_credential(credential, membership) -> GateDeviceCredential:
    credential.revoked_at = timezone.now()
    credential.revoked_by = membership.user
    credential.save(update_fields=["revoked_at", "revoked_by"])
    return credential


def authenticate_device(token: str, *, ip: str | None = None) -> GateDeviceCredential:
    """Return the valid credential, or raise. Never reveals device existence."""
    assert_not_throttled(_THROTTLE_ACCOUNT, ip)
    credential = (
        GateDeviceCredential.objects.select_related("device", "device__building")
        .filter(token_sha256=_digest(token))
        .first()
    )
    if credential is None or not credential.device.active:
        record_auth_failure(_THROTTLE_ACCOUNT, ip, kind="gate_device")
        raise GateAuthenticationFailed("Invalid gate device credential.")
    if credential.revoked_at is not None:
        record_auth_failure(_THROTTLE_ACCOUNT, ip, kind="gate_device")
        raise GateCredentialRevoked("This reader's credential was revoked.")
    if not credential.is_valid():
        record_auth_failure(_THROTTLE_ACCOUNT, ip, kind="gate_device")
        raise GateCredentialExpired("This reader's credential has expired.")

    reset_auth_throttle(_THROTTLE_ACCOUNT, ip)
    _touch_last_seen(credential.device)
    return credential


def _touch_last_seen(device) -> None:
    """Hour resolution only: enough to see a reader go dark, too coarse to
    place anyone at the gate."""
    hour = timezone.now().replace(minute=0, second=0, microsecond=0)
    if device.last_seen_hour != hour:
        GateDevice.objects.filter(pk=device.pk).update(last_seen_hour=hour)
        device.last_seen_hour = hour
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `set -a && . .env && set +a && .venv/bin/python -m pytest src/lamto/gate/tests/test_devices.py -v`
Expected: PASS, 10 passed

- [ ] **Step 5: Commit**

```bash
git add src/lamto/gate/devices.py src/lamto/gate/tests/test_devices.py
git commit -m "feat(gate): issue, rotate, revoke, and authenticate reader credentials"
```

---

### Task 9: Matching and recognition

**Files:**
- Create: `src/lamto/gate/matching.py`, `src/lamto/gate/recognition.py`
- Test: `src/lamto/gate/tests/test_matching.py`, `src/lamto/gate/tests/test_recognition.py`

**Interfaces:**
- Consumes: `normalize_plate`, `PlateFormatError` (Task 1); models (Task 2); `open_embedding`, `VECTOR_DTYPE` (Task 3); `get_embedder`, `FaceQualityError`, `FaceEmbedderUnavailable` (Task 4).
- Produces:
  - `FaceMatch(occupancy, score: float)` and `match_face(building, vector, *, model_name, model_version) -> FaceMatch`
  - `match_plate(building, normalized: str) -> VehiclePlate | None`
  - `RecognitionOutcome(matched, display_name, unit_label, direction, score, event_id)`
  - `recognize_face(credential, image_bytes) -> RecognitionOutcome`
  - `recognize_plate(credential, raw_text) -> RecognitionOutcome`

Matching is scoped to the device's building and to the probe's exact model name and version — comparing vectors across model versions is meaningless. A few hundred enrolments is a brute-force numpy scan; pgvector would be a dependency bought for nothing.

- [ ] **Step 1: Write the failing matching test**

Create `src/lamto/gate/tests/test_matching.py`:

```python
import numpy as np
import pytest

from lamto.accounts.models import Building, ResidentOccupancy, Unit, User
from lamto.gate.crypto import seal_embedding
from lamto.gate.matching import match_face, match_plate
from lamto.gate.models import FaceEnrollment, ReviewStatus, VehiclePlate
from lamto.gate.tests.fakes import FAKE_MODEL_NAME, FAKE_MODEL_VERSION, fake_vector

pytestmark = pytest.mark.django_db

MODEL = {"model_name": FAKE_MODEL_NAME, "model_version": FAKE_MODEL_VERSION}


def _approve(occupancy, seed, *, model_name=FAKE_MODEL_NAME, model_version=FAKE_MODEL_VERSION):
    return FaceEnrollment.objects.create(
        occupancy=occupancy,
        embedding=seal_embedding(fake_vector(seed)),
        model_name=model_name,
        model_version=model_version,
        status=ReviewStatus.APPROVED,
    )


def test_an_enrolled_face_matches_itself(occupancy, use_fake_embedder):
    _approve(occupancy, "nguyen")
    result = match_face(
        occupancy.unit.building, fake_vector("nguyen"), **MODEL
    )
    assert result.occupancy == occupancy
    assert result.score > 0.99


def test_a_stranger_does_not_match(occupancy, use_fake_embedder):
    _approve(occupancy, "nguyen")
    result = match_face(occupancy.unit.building, fake_vector("stranger"), **MODEL)
    assert result.occupancy is None
    assert result.score < 0.38


def test_the_score_is_returned_even_below_threshold(occupancy, use_fake_embedder):
    _approve(occupancy, "nguyen")
    result = match_face(occupancy.unit.building, fake_vector("stranger"), **MODEL)
    assert result.score is not None


def test_the_threshold_boundary_is_respected(occupancy, use_fake_embedder, settings):
    _approve(occupancy, "nguyen")
    probe = fake_vector("nguyen")
    settings.GATE_FACE_MATCH_THRESHOLD = 0.99
    assert match_face(occupancy.unit.building, probe, **MODEL).occupancy == occupancy
    settings.GATE_FACE_MATCH_THRESHOLD = 1.01
    assert match_face(occupancy.unit.building, probe, **MODEL).occupancy is None


def test_matching_is_scoped_to_the_building(occupancy, use_fake_embedder):
    _approve(occupancy, "nguyen")
    elsewhere = Building.objects.create(name="Other Building")
    result = match_face(elsewhere, fake_vector("nguyen"), **MODEL)
    assert result.occupancy is None


def test_a_different_model_version_is_never_matched(occupancy, use_fake_embedder):
    _approve(occupancy, "nguyen", model_version="2")
    result = match_face(occupancy.unit.building, fake_vector("nguyen"), **MODEL)
    assert result.occupancy is None


def test_pending_and_rejected_enrolments_are_not_matched(occupancy, use_fake_embedder):
    enrollment = _approve(occupancy, "nguyen")
    FaceEnrollment.objects.filter(pk=enrollment.pk).update(status=ReviewStatus.PENDING)
    assert match_face(occupancy.unit.building, fake_vector("nguyen"), **MODEL).occupancy is None


def test_an_inactive_occupancy_is_not_matched(occupancy, use_fake_embedder):
    _approve(occupancy, "nguyen")
    ResidentOccupancy.objects.filter(pk=occupancy.pk).update(active=False)
    assert match_face(occupancy.unit.building, fake_vector("nguyen"), **MODEL).occupancy is None


def test_the_closest_of_several_enrolments_wins(
    occupancy, second_occupancy, use_fake_embedder
):
    _approve(occupancy, "nguyen")
    _approve(second_occupancy, "tran")
    result = match_face(occupancy.unit.building, fake_vector("tran"), **MODEL)
    assert result.occupancy == second_occupancy


def test_a_zero_vector_is_refused(occupancy, use_fake_embedder):
    with pytest.raises(ValueError):
        match_face(occupancy.unit.building, np.zeros(512, dtype=np.float32), **MODEL)


def test_only_approved_plates_match(occupancy):
    plate = VehiclePlate.objects.create(
        occupancy=occupancy, building=occupancy.unit.building, plate="51F12345"
    )
    assert match_plate(occupancy.unit.building, "51F12345") is None
    VehiclePlate.objects.filter(pk=plate.pk).update(status=ReviewStatus.APPROVED)
    assert match_plate(occupancy.unit.building, "51F12345").pk == plate.pk


def test_plate_matching_is_scoped_to_the_building(occupancy):
    VehiclePlate.objects.create(
        occupancy=occupancy,
        building=occupancy.unit.building,
        plate="51F12345",
        status=ReviewStatus.APPROVED,
    )
    elsewhere = Building.objects.create(name="Other Building")
    assert match_plate(elsewhere, "51F12345") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `set -a && . .env && set +a && .venv/bin/python -m pytest src/lamto/gate/tests/test_matching.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'lamto.gate.matching'`

- [ ] **Step 3: Write the matcher**

Create `src/lamto/gate/matching.py`:

```python
"""Cosine matching against approved enrolments in one building.

Brute force over a few hundred vectors is sub-millisecond in numpy, so there
is no index and no pgvector: a similarity index bought for a pilot-sized
building is a dependency with no measurable payoff.

Two filters are load-bearing. Matching is scoped to the reader's building,
and to the probe's exact model name and version — vectors from different
models are not comparable, and silently comparing them would produce
confident nonsense.
"""

from dataclasses import dataclass

import numpy as np
from django.conf import settings

from .crypto import VECTOR_DTYPE, open_embedding
from .models import FaceEnrollment, ReviewStatus, VehiclePlate

MATCH_METRIC = "cosine"


@dataclass(frozen=True)
class FaceMatch:
    """``occupancy`` is None below threshold; ``score`` is reported either way."""

    occupancy: object | None
    score: float


def unit_vector(vector) -> np.ndarray:
    """L2-normalize so cosine similarity is a dot product. Shared with calibration."""
    array = np.asarray(vector, dtype=VECTOR_DTYPE).ravel()
    norm = float(np.linalg.norm(array))
    if norm == 0.0:
        raise ValueError("Cannot match a zero-length embedding.")
    return array / norm


def match_face(building, vector, *, model_name: str, model_version: str) -> FaceMatch:
    probe = unit_vector(vector)
    rows = FaceEnrollment.objects.filter(
        status=ReviewStatus.APPROVED,
        embedding__isnull=False,
        model_name=model_name,
        model_version=model_version,
        occupancy__active=True,
        occupancy__unit__building=building,
    ).select_related("occupancy", "occupancy__unit")

    best = None
    best_score = -1.0
    for row in rows:
        candidate = open_embedding(row.embedding)
        if candidate.shape != probe.shape:
            continue
        score = float(np.dot(probe, unit_vector(candidate)))
        if score > best_score:
            best, best_score = row.occupancy, score

    if best is None:
        return FaceMatch(occupancy=None, score=0.0)
    threshold = settings.GATE_FACE_MATCH_THRESHOLD
    return FaceMatch(
        occupancy=best if best_score >= threshold else None, score=best_score
    )


def match_plate(building, normalized: str):
    return VehiclePlate.objects.filter(
        building=building, plate=normalized, status=ReviewStatus.APPROVED
    ).select_related("occupancy", "occupancy__unit", "occupancy__user").first()
```

- [ ] **Step 4: Run the matching tests**

Run: `set -a && . .env && set +a && .venv/bin/python -m pytest src/lamto/gate/tests/test_matching.py -v`
Expected: PASS, 12 passed

- [ ] **Step 5: Write the failing recognition test**

Create `src/lamto/gate/tests/test_recognition.py`:

```python
import pytest

from lamto.gate.crypto import seal_embedding
from lamto.gate.devices import issue_credential
from lamto.gate.embedding import FaceEmbedderUnavailable, NoFaceDetected
from lamto.gate.models import (
    FaceEnrollment,
    GateDevice,
    GateEvent,
    ReviewStatus,
    VehiclePlate,
)
from lamto.gate.plates import PlateFormatError
from lamto.gate.recognition import recognize_face, recognize_plate
from lamto.gate.tests.fakes import (
    FAKE_MODEL_NAME,
    FAKE_MODEL_VERSION,
    face_bytes,
    fake_vector,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def credential(building, management):
    device = GateDevice.objects.create(
        building=building, label="North gate", direction=GateDevice.Direction.ENTRY
    )
    return issue_credential(device, management)[0]


@pytest.fixture
def enrolled(occupancy, use_fake_embedder):
    return FaceEnrollment.objects.create(
        occupancy=occupancy,
        embedding=seal_embedding(fake_vector("nguyen")),
        model_name=FAKE_MODEL_NAME,
        model_version=FAKE_MODEL_VERSION,
        status=ReviewStatus.APPROVED,
    )


def test_a_known_face_is_named_and_logged(credential, enrolled, occupancy):
    outcome = recognize_face(credential, face_bytes("nguyen"))
    assert outcome.matched is True
    assert outcome.display_name == occupancy.user.display_name
    assert outcome.unit_label == occupancy.unit.label
    assert outcome.direction == "ENTRY"

    event = GateEvent.objects.get(pk=outcome.event_id)
    assert event.kind == GateEvent.Kind.FACE
    assert event.matched_occupancy_id == occupancy.pk
    assert event.model_name == FAKE_MODEL_NAME
    assert event.model_version == FAKE_MODEL_VERSION
    assert event.match_metric == "cosine"
    assert event.threshold_used == pytest.approx(0.38)
    assert event.match_score > 0.99


def test_an_unknown_face_is_a_result_not_an_error(credential, enrolled):
    outcome = recognize_face(credential, face_bytes("stranger"))
    assert outcome.matched is False
    assert outcome.display_name == ""
    event = GateEvent.objects.get(pk=outcome.event_id)
    assert event.matched_occupancy_id is None
    assert event.match_score is not None


def test_a_failed_read_writes_no_event(credential, enrolled):
    with pytest.raises(NoFaceDetected):
        recognize_face(credential, b"NOFACE")
    assert not GateEvent.objects.exists()


def test_a_model_outage_writes_no_event(credential, enrolled, settings):
    settings.GATE_FACE_EMBEDDER = ""
    with pytest.raises(FaceEmbedderUnavailable):
        recognize_face(credential, face_bytes("nguyen"))
    assert not GateEvent.objects.exists()


def test_no_image_is_retained_on_the_event(credential, enrolled):
    outcome = recognize_face(credential, face_bytes("nguyen"))
    event = GateEvent.objects.get(pk=outcome.event_id)
    stored = {
        field.name
        for field in GateEvent._meta.get_fields()
        if hasattr(field, "attname")
    }
    assert not {"image", "photo", "snapshot", "storage_key"} & stored
    assert event.raw_plate_text == ""


def test_a_known_plate_is_named_and_logged(credential, occupancy):
    plate = VehiclePlate.objects.create(
        occupancy=occupancy,
        building=occupancy.unit.building,
        plate="51F12345",
        status=ReviewStatus.APPROVED,
    )
    outcome = recognize_plate(credential, "51F-123.45")
    assert outcome.matched is True
    assert outcome.unit_label == occupancy.unit.label
    event = GateEvent.objects.get(pk=outcome.event_id)
    assert event.kind == GateEvent.Kind.PLATE
    assert event.matched_plate_id == plate.pk
    assert event.raw_plate_text == "51F-123.45"
    assert event.normalized_plate_text == "51F12345"


def test_an_unknown_plate_is_logged_as_unrecognized(credential, occupancy):
    outcome = recognize_plate(credential, "99Z99999")
    assert outcome.matched is False
    event = GateEvent.objects.get(pk=outcome.event_id)
    assert event.matched_plate_id is None
    assert event.normalized_plate_text == "99Z99999"


def test_an_unreadable_plate_writes_no_event(credential):
    with pytest.raises(PlateFormatError):
        recognize_plate(credential, "!!")
    assert not GateEvent.objects.exists()


def test_the_event_direction_comes_from_the_device(credential, enrolled):
    GateDevice.objects.filter(pk=credential.device_id).update(
        direction=GateDevice.Direction.EXIT
    )
    credential.device.refresh_from_db()
    outcome = recognize_face(credential, face_bytes("nguyen"))
    assert outcome.direction == "EXIT"
    assert GateEvent.objects.get(pk=outcome.event_id).direction == "EXIT"
```

- [ ] **Step 6: Run test to verify it fails**

Run: `set -a && . .env && set +a && .venv/bin/python -m pytest src/lamto/gate/tests/test_recognition.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'lamto.gate.recognition'`

- [ ] **Step 7: Write the recognition module**

Create `src/lamto/gate/recognition.py`:

```python
"""Reader entry points. One capture in, one logged sighting out.

The capture image is embedded in memory and discarded within the request. No
snapshot is written at any point, and there is no field to write one to.

"Not recognized" is a RESULT and is logged as an unmatched sighting. A failed
READ is not a sighting and writes nothing: an unreadable frame, an unusable
plate string, or a model outage all raise without touching GateEvent.

This subsystem logs identity and authorizes nothing. There is no liveness
detection: a printed photo held to the reader will match. That is tolerable
only because nothing opens.
"""

from dataclasses import dataclass

from django.conf import settings
from django.utils import timezone

from .embedding import get_embedder
from .matching import MATCH_METRIC, match_face, match_plate
from .models import GateEvent
from .plates import normalize_plate


@dataclass(frozen=True)
class RecognitionOutcome:
    matched: bool
    display_name: str
    unit_label: str
    direction: str
    score: float | None
    event_id: int


def recognize_face(credential, image_bytes: bytes) -> RecognitionOutcome:
    device = credential.device
    building = device.building
    # Raises FaceQualityError or FaceEmbedderUnavailable; no event is written.
    result = get_embedder().embed(image_bytes)
    match = match_face(
        building,
        result.vector,
        model_name=result.model_name,
        model_version=result.model_version,
    )
    occupancy = match.occupancy
    event = GateEvent.objects.create(
        building=building,
        device=device,
        kind=GateEvent.Kind.FACE,
        direction=device.direction,
        occurred_at=timezone.now(),
        matched_occupancy=occupancy,
        model_name=result.model_name,
        model_version=result.model_version,
        match_metric=MATCH_METRIC,
        threshold_used=settings.GATE_FACE_MATCH_THRESHOLD,
        match_score=match.score,
    )
    return _outcome(occupancy, device, match.score, event)


def recognize_plate(credential, raw_text: str) -> RecognitionOutcome:
    device = credential.device
    building = device.building
    # Raises PlateFormatError; an unusable read is not a sighting.
    normalized = normalize_plate(raw_text)
    plate = match_plate(building, normalized)
    event = GateEvent.objects.create(
        building=building,
        device=device,
        kind=GateEvent.Kind.PLATE,
        direction=device.direction,
        occurred_at=timezone.now(),
        matched_plate=plate,
        matched_occupancy=plate.occupancy if plate else None,
        raw_plate_text=(raw_text or "")[:64],
        normalized_plate_text=normalized,
    )
    return _outcome(plate.occupancy if plate else None, device, None, event)


def _outcome(occupancy, device, score, event) -> RecognitionOutcome:
    return RecognitionOutcome(
        matched=occupancy is not None,
        display_name=occupancy.user.display_name if occupancy else "",
        unit_label=occupancy.unit.label if occupancy else "",
        direction=device.direction,
        score=score,
        event_id=event.pk,
    )
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `set -a && . .env && set +a && .venv/bin/python -m pytest src/lamto/gate/tests/test_recognition.py -v`
Expected: PASS, 9 passed

- [ ] **Step 9: Commit**

```bash
git add src/lamto/gate/matching.py src/lamto/gate/recognition.py \
  src/lamto/gate/tests/test_matching.py src/lamto/gate/tests/test_recognition.py
git commit -m "feat(gate): match faces and plates per building and log the sighting"
```

---

### Task 10: Resident registration API

**Files:**
- Create: `src/lamto/api/gate_serializers.py`, `src/lamto/api/gate_views.py`
- Modify: `src/lamto/api/problems.py` (`_PROBLEM_DESCRIPTIONS` ~line 22, new exception classes after `ClientRefConflict` ~line 66, `_EXCEPTION_CODES` ~line 75)
- Modify: `src/lamto/api/urls.py`
- Modify: `docs/api/openapi-v1.yaml` (regenerated)
- Test: `src/lamto/api/tests/test_gate_api.py`

**Interfaces:**
- Consumes: enrolment services (Task 5), models (Task 2), `resolve_api_occupancy` from `lamto.api.occupancy`.
- Produces: routes `api:gate-registrations`, `api:gate-plates`, `api:gate-plate-detail`, `api:gate-face`; problem codes `gate_no_face_detected`, `gate_multiple_faces`, `gate_face_too_small`, `gate_face_too_blurry`, `gate_face_unusable`, `gate_photo_rejected`, `gate_plate_unreadable`, `gate_plate_already_registered`, `gate_model_unavailable`, `gate_device_unauthenticated`, `gate_device_revoked`, `gate_device_expired`.

Endpoints:

| Method | Path | Result |
|---|---|---|
| GET | `/api/v1/gate/registrations` | `{"face": {...}\|null, "plates": [...]}` |
| POST | `/api/v1/gate/plates` | 201 plate |
| DELETE | `/api/v1/gate/plates/{id}` | 204 |
| POST | `/api/v1/gate/face` | 202 face (pending review) |
| DELETE | `/api/v1/gate/face` | 204 |

- [ ] **Step 1: Add the problem codes**

In `src/lamto/api/problems.py`, add these entries to `_PROBLEM_DESCRIPTIONS`:

```python
    202: "Accepted for manager review (gate face enrolment).",
    503: "A dependency is unavailable (code=gate_model_unavailable).",
```

Change the existing `409` and `422` descriptions to cover the new cases:

```python
    409: (
        "client_ref reused with different content (code=client_ref_conflict), "
        "or the plate is already registered in this building "
        "(code=gate_plate_already_registered)."
    ),
    422: (
        "Occupancy selection required "
        "(code=occupancy_selection_required); send X-LamTo-Occupancy. "
        "Or the submitted image or plate is unusable (code=gate_*)."
    ),
```

Add these exception classes after `ClientRefConflict`:

```python
class GateNoFaceDetected(exceptions.APIException):
    status_code = 422
    default_detail = "No face was detected in the image."
    default_code = "gate_no_face_detected"


class GateMultipleFaces(exceptions.APIException):
    status_code = 422
    default_detail = "More than one face was detected in the image."
    default_code = "gate_multiple_faces"


class GateFaceTooSmall(exceptions.APIException):
    status_code = 422
    default_detail = "The face in the image is too small."
    default_code = "gate_face_too_small"


class GateFaceTooBlurry(exceptions.APIException):
    status_code = 422
    default_detail = "The face in the image is too blurry."
    default_code = "gate_face_too_blurry"


class GateFaceUnusable(exceptions.APIException):
    status_code = 422
    default_detail = "The image cannot be used for enrolment."
    default_code = "gate_face_unusable"


class GatePhotoRejected(exceptions.APIException):
    status_code = 400
    default_detail = "The upload was rejected before processing."
    default_code = "gate_photo_rejected"


class GatePlateUnreadable(exceptions.APIException):
    status_code = 422
    default_detail = "The plate text could not be read."
    default_code = "gate_plate_unreadable"


class GatePlateAlreadyRegistered(exceptions.APIException):
    status_code = 409
    default_detail = "This plate is already registered in this building."
    default_code = "gate_plate_already_registered"


class GateModelUnavailable(exceptions.APIException):
    status_code = 503
    default_detail = "The face recognition model is unavailable."
    default_code = "gate_model_unavailable"


class GateDeviceUnauthenticated(exceptions.APIException):
    status_code = 401
    default_detail = "Invalid gate device credential."
    default_code = "gate_device_unauthenticated"


class GateDeviceRevoked(exceptions.APIException):
    status_code = 401
    default_detail = "This reader's credential was revoked."
    default_code = "gate_device_revoked"


class GateDeviceExpired(exceptions.APIException):
    status_code = 401
    default_detail = "This reader's credential has expired."
    default_code = "gate_device_expired"
```

Add each to `_EXCEPTION_CODES`, **before** the generic DRF entries (most specific first — the first `isinstance` match wins):

```python
    (GateNoFaceDetected, "gate_no_face_detected"),
    (GateMultipleFaces, "gate_multiple_faces"),
    (GateFaceTooSmall, "gate_face_too_small"),
    (GateFaceTooBlurry, "gate_face_too_blurry"),
    (GateFaceUnusable, "gate_face_unusable"),
    (GatePhotoRejected, "gate_photo_rejected"),
    (GatePlateUnreadable, "gate_plate_unreadable"),
    (GatePlateAlreadyRegistered, "gate_plate_already_registered"),
    (GateModelUnavailable, "gate_model_unavailable"),
    (GateDeviceRevoked, "gate_device_revoked"),
    (GateDeviceExpired, "gate_device_expired"),
    (GateDeviceUnauthenticated, "gate_device_unauthenticated"),
```

- [ ] **Step 2: Write the failing test**

Create `src/lamto/api/tests/test_gate_api.py`:

```python
import pytest
from django.urls import reverse
from knox.models import AuthToken
from rest_framework.test import APIClient

from lamto.gate.models import (
    FaceEnrollment,
    PendingEnrollmentPhoto,
    ReviewStatus,
    VehiclePlate,
)
from lamto.gate.tests.fakes import face_bytes

pytestmark = pytest.mark.django_db


@pytest.fixture
def api(occupancy):
    client = APIClient()
    _, token = AuthToken.objects.create(occupancy.user)
    client.credentials(HTTP_AUTHORIZATION=f"Token {token}")
    return client


@pytest.fixture
def no_clamav(monkeypatch):
    monkeypatch.setattr(
        "lamto.gate.enrollment.scan_with_clamav", lambda file_obj: True
    )


def test_registrations_start_empty(api, occupancy):
    response = api.get(reverse("api:gate-registrations"))
    assert response.status_code == 200
    assert response.json() == {"face": None, "plates": []}


def test_a_resident_can_register_several_plates(api, occupancy):
    first = api.post(
        reverse("api:gate-plates"), {"plate": "51F-123.45"}, format="json"
    )
    assert first.status_code == 201
    assert first.json()["plate"] == "51F12345"
    assert first.json()["status"] == "PENDING"
    api.post(reverse("api:gate-plates"), {"plate": "59X1 999.99"}, format="json")
    assert VehiclePlate.objects.filter(occupancy=occupancy).count() == 2


def test_an_unreadable_plate_returns_a_machine_code(api):
    response = api.post(reverse("api:gate-plates"), {"plate": "!!"}, format="json")
    assert response.status_code == 422
    assert response.json()["code"] == "gate_plate_unreadable"


def test_a_plate_held_by_another_resident_conflicts_without_naming_them(
    api, occupancy, second_occupancy
):
    VehiclePlate.objects.create(
        occupancy=second_occupancy,
        building=second_occupancy.unit.building,
        plate="51F12345",
        status=ReviewStatus.APPROVED,
    )
    response = api.post(
        reverse("api:gate-plates"), {"plate": "51F12345"}, format="json"
    )
    assert response.status_code == 409
    assert response.json()["code"] == "gate_plate_already_registered"
    body = response.content.decode()
    assert second_occupancy.unit.label not in body
    assert second_occupancy.user.display_name not in body


def test_a_resident_can_delete_their_plate(api, occupancy):
    created = api.post(
        reverse("api:gate-plates"), {"plate": "51F12345"}, format="json"
    ).json()
    response = api.delete(reverse("api:gate-plate-detail", args=[created["id"]]))
    assert response.status_code == 204
    assert not VehiclePlate.objects.exists()


def test_a_resident_cannot_delete_another_residents_plate(
    api, occupancy, second_occupancy
):
    other = VehiclePlate.objects.create(
        occupancy=second_occupancy,
        building=second_occupancy.unit.building,
        plate="51F12345",
    )
    response = api.delete(reverse("api:gate-plate-detail", args=[other.pk]))
    assert response.status_code == 404
    assert VehiclePlate.objects.filter(pk=other.pk).exists()


def test_submitting_a_face_is_accepted_for_review(
    api, occupancy, use_fake_embedder, gate_storage, no_clamav
):
    response = api.post(
        reverse("api:gate-face"),
        {"photo": _image(face_bytes("nguyen"))},
        format="multipart",
    )
    assert response.status_code == 202
    assert response.json()["status"] == "PENDING"
    assert FaceEnrollment.objects.filter(occupancy=occupancy).exists()


def test_an_image_with_no_face_returns_its_own_code(
    api, use_fake_embedder, gate_storage, no_clamav
):
    response = api.post(
        reverse("api:gate-face"), {"photo": _image(b"NOFACE")}, format="multipart"
    )
    assert response.status_code == 422
    assert response.json()["code"] == "gate_no_face_detected"


def test_an_image_with_two_faces_returns_its_own_code(
    api, use_fake_embedder, gate_storage, no_clamav
):
    response = api.post(
        reverse("api:gate-face"), {"photo": _image(b"MANYFACES")}, format="multipart"
    )
    assert response.status_code == 422
    assert response.json()["code"] == "gate_multiple_faces"


def test_a_model_outage_is_a_503(api, gate_storage, no_clamav, settings):
    settings.GATE_FACE_EMBEDDER = ""
    response = api.post(
        reverse("api:gate-face"),
        {"photo": _image(face_bytes("nguyen"))},
        format="multipart",
    )
    assert response.status_code == 503
    assert response.json()["code"] == "gate_model_unavailable"
    assert not FaceEnrollment.objects.exists()


def test_deleting_a_face_removes_the_enrolment(
    api, occupancy, use_fake_embedder, gate_storage, no_clamav
):
    api.post(
        reverse("api:gate-face"),
        {"photo": _image(face_bytes("nguyen"))},
        format="multipart",
    )
    response = api.delete(reverse("api:gate-face"))
    assert response.status_code == 204
    assert not FaceEnrollment.objects.exists()
    assert not PendingEnrollmentPhoto.objects.exists()


def test_the_endpoints_require_authentication():
    response = APIClient().get(reverse("api:gate-registrations"))
    assert response.status_code == 401


def _image(payload: bytes):
    from django.core.files.uploadedfile import SimpleUploadedFile

    return SimpleUploadedFile("face.jpg", payload, content_type="image/jpeg")
```

The gate fixtures (`occupancy`, `use_fake_embedder`, `gate_storage`, `second_occupancy`) live in `src/lamto/gate/tests/conftest.py` and are not visible from `src/lamto/api/tests/`. Copy that file to `src/lamto/api/tests/conftest.py` if `src/lamto/api/tests/` has no conftest, or import the fixtures explicitly:

```python
from lamto.gate.tests.conftest import (  # noqa: F401
    building,
    gate_storage,
    management,
    occupancy,
    second_occupancy,
    use_fake_embedder,
)
```

Use the import form — one definition, no drift.

- [ ] **Step 3: Run test to verify it fails**

Run: `set -a && . .env && set +a && .venv/bin/python -m pytest src/lamto/api/tests/test_gate_api.py -v`
Expected: FAIL with `django.urls.exceptions.NoReverseMatch: 'gate-registrations' is not a valid view function or pattern name`

- [ ] **Step 4: Write the serializers**

Create `src/lamto/api/gate_serializers.py`:

```python
"""Resident-facing gate registration shapes.

Status is a machine value (``PENDING``/``APPROVED``/``REJECTED``/
``EXPIRED``); the app owns the Vietnamese label. ``review_note`` is the one
free-text field a manager writes and a resident reads, so it is passed
through as entered.
"""

from rest_framework import serializers


class VehiclePlateSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    plate = serializers.CharField()
    status = serializers.CharField()
    submitted_at = serializers.DateTimeField()
    review_note = serializers.CharField(allow_blank=True)


class FaceEnrollmentSerializer(serializers.Serializer):
    status = serializers.CharField()
    submitted_at = serializers.DateTimeField()
    review_note = serializers.CharField(allow_blank=True)


class GateRegistrationsSerializer(serializers.Serializer):
    face = FaceEnrollmentSerializer(allow_null=True)
    plates = VehiclePlateSerializer(many=True)


class PlateCreateSerializer(serializers.Serializer):
    plate = serializers.CharField(
        max_length=32,
        help_text="Any spacing or punctuation; the server normalizes it.",
    )


class FaceUploadSerializer(serializers.Serializer):
    photo = serializers.FileField(
        help_text="JPEG/PNG image; scanned by ClamAV, embedded, then discarded."
    )
```

- [ ] **Step 5: Write the views**

Create `src/lamto/api/gate_views.py`:

```python
"""Resident gate registration endpoints.

Errors carry stable machine codes; every Vietnamese string the resident sees
comes from the app, keyed off ``code``. Nothing here returns a display
message intended for direct rendering.
"""

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from drf_spectacular.utils import extend_schema
from rest_framework import exceptions, parsers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from lamto.api.gate_serializers import (
    FaceEnrollmentSerializer,
    FaceUploadSerializer,
    GateRegistrationsSerializer,
    PlateCreateSerializer,
    VehiclePlateSerializer,
)
from lamto.api.occupancy import OCCUPANCY_HEADER_PARAMETER, resolve_api_occupancy
from lamto.api.problems import (
    GateFaceTooBlurry,
    GateFaceTooSmall,
    GateFaceUnusable,
    GateModelUnavailable,
    GateMultipleFaces,
    GateNoFaceDetected,
    GatePhotoRejected,
    GatePlateAlreadyRegistered,
    GatePlateUnreadable,
    problem_responses,
)
from lamto.gate.embedding import (
    FaceEmbedderUnavailable,
    FaceQualityError,
    FaceTooBlurry,
    FaceTooSmall,
    MultipleFacesDetected,
    NoFaceDetected,
)
from lamto.gate.enrollment import (
    PhotoRejected,
    PlateAlreadyRegistered,
    revoke_face_enrollment,
    revoke_plate,
    submit_face_enrollment,
    submit_plate,
)
from lamto.gate.models import FaceEnrollment, VehiclePlate
from lamto.gate.plates import PlateFormatError

_QUALITY_PROBLEMS = {
    NoFaceDetected: GateNoFaceDetected,
    MultipleFacesDetected: GateMultipleFaces,
    FaceTooSmall: GateFaceTooSmall,
    FaceTooBlurry: GateFaceTooBlurry,
}


def _raise_quality_problem(error: FaceQualityError):
    for source, problem in _QUALITY_PROBLEMS.items():
        if isinstance(error, source):
            raise problem()
    raise GateFaceUnusable()


def _plate_payload(plate) -> dict:
    return {
        "id": plate.pk,
        "plate": plate.plate,
        "status": plate.status,
        "submitted_at": plate.submitted_at,
        "review_note": plate.review_note,
    }


def _face_payload(enrollment) -> dict | None:
    if enrollment is None:
        return None
    return {
        "status": enrollment.status,
        "submitted_at": enrollment.submitted_at,
        "review_note": enrollment.review_note,
    }


class GateRegistrationsView(APIView):
    @extend_schema(
        parameters=[OCCUPANCY_HEADER_PARAMETER],
        responses={200: GateRegistrationsSerializer, **problem_responses(401, 403, 422)},
    )
    def get(self, request):
        occupancy, _ = resolve_api_occupancy(request)
        face = FaceEnrollment.objects.filter(occupancy=occupancy).first()
        plates = VehiclePlate.objects.filter(occupancy=occupancy).order_by("plate")
        return Response(
            GateRegistrationsSerializer(
                {
                    "face": _face_payload(face),
                    "plates": [_plate_payload(p) for p in plates],
                }
            ).data
        )


class GatePlateListCreateView(APIView):
    @extend_schema(
        parameters=[OCCUPANCY_HEADER_PARAMETER],
        request=PlateCreateSerializer,
        responses={
            201: VehiclePlateSerializer,
            **problem_responses(400, 401, 403, 409, 422),
        },
    )
    def post(self, request):
        occupancy, _ = resolve_api_occupancy(request)
        serializer = PlateCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            plate = submit_plate(occupancy, serializer.validated_data["plate"])
        except PlateFormatError:
            raise GatePlateUnreadable()
        except PlateAlreadyRegistered:
            raise GatePlateAlreadyRegistered()
        return Response(
            VehiclePlateSerializer(_plate_payload(plate)).data,
            status=status.HTTP_201_CREATED,
        )


class GatePlateDetailView(APIView):
    @extend_schema(
        parameters=[OCCUPANCY_HEADER_PARAMETER],
        responses={204: None, **problem_responses(401, 403, 404, 422)},
    )
    def delete(self, request, pk):
        occupancy, _ = resolve_api_occupancy(request)
        if not VehiclePlate.objects.filter(occupancy=occupancy, pk=pk).exists():
            raise exceptions.NotFound("Plate not found.")
        revoke_plate(occupancy, pk)
        return Response(status=status.HTTP_204_NO_CONTENT)


class GateFaceView(APIView):
    parser_classes = [parsers.MultiPartParser]

    @extend_schema(
        parameters=[OCCUPANCY_HEADER_PARAMETER],
        request=FaceUploadSerializer,
        responses={
            202: FaceEnrollmentSerializer,
            **problem_responses(400, 401, 403, 422, 503),
        },
    )
    def post(self, request):
        occupancy, _ = resolve_api_occupancy(request)
        serializer = FaceUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            enrollment = submit_face_enrollment(
                occupancy, serializer.validated_data["photo"]
            )
        except PhotoRejected as error:
            raise GatePhotoRejected(str(error))
        except FaceQualityError as error:
            _raise_quality_problem(error)
        except FaceEmbedderUnavailable:
            raise GateModelUnavailable()
        except DjangoPermissionDenied:
            raise exceptions.PermissionDenied("An active occupancy is required.")
        return Response(
            FaceEnrollmentSerializer(_face_payload(enrollment)).data,
            status=status.HTTP_202_ACCEPTED,
        )

    @extend_schema(
        parameters=[OCCUPANCY_HEADER_PARAMETER],
        responses={204: None, **problem_responses(401, 403, 422)},
    )
    def delete(self, request):
        occupancy, _ = resolve_api_occupancy(request)
        revoke_face_enrollment(occupancy)
        return Response(status=status.HTTP_204_NO_CONTENT)
```

- [ ] **Step 6: Wire the routes**

In `src/lamto/api/urls.py`, add the import and the paths before the `documents/<str:token>` entry:

```python
from lamto.api import gate_views
```

```python
    path("gate/registrations", gate_views.GateRegistrationsView.as_view(), name="gate-registrations"),
    path("gate/plates", gate_views.GatePlateListCreateView.as_view(), name="gate-plates"),
    path("gate/plates/<int:pk>", gate_views.GatePlateDetailView.as_view(), name="gate-plate-detail"),
    path("gate/face", gate_views.GateFaceView.as_view(), name="gate-face"),
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `set -a && . .env && set +a && .venv/bin/python -m pytest src/lamto/api/tests/test_gate_api.py -v`
Expected: PASS, 12 passed

- [ ] **Step 8: Regenerate the schema**

Run: `set -a && . .env && set +a && .venv/bin/python manage.py spectacular --file docs/api/openapi-v1.yaml`
Then: `set -a && . .env && set +a && .venv/bin/python -m pytest src/lamto/api/tests/test_openapi.py -v`
Expected: PASS — the committed schema is current.

- [ ] **Step 9: Commit**

```bash
git add src/lamto/api/gate_serializers.py src/lamto/api/gate_views.py \
  src/lamto/api/problems.py src/lamto/api/urls.py \
  src/lamto/api/tests/test_gate_api.py docs/api/openapi-v1.yaml
git commit -m "feat(api): let residents register plates and submit a face for review"
```

---

### Task 11: Reader recognition endpoints

**Files:**
- Modify: `src/lamto/api/gate_serializers.py`
- Modify: `src/lamto/api/gate_views.py`
- Modify: `src/lamto/api/urls.py`
- Modify: `docs/api/openapi-v1.yaml` (regenerated)
- Test: `src/lamto/api/tests/test_gate_recognize_api.py`

**Interfaces:**
- Consumes: `authenticate_device`, `token_from_header`, `AUTH_SCHEME`, gate auth errors (Task 8); `recognize_face`, `recognize_plate` (Task 9); `client_ip` from `lamto.accounts.security`.
- Produces: routes `api:gate-recognize-face`, `api:gate-recognize-plate`; `RecognitionOutcomeSerializer`, `PlateRecognizeSerializer`, `FaceRecognizeSerializer`.

These are the endpoints real hardware will call unchanged. They authenticate a *device*, not a user, so DRF's user-based authentication is switched off and the credential is resolved in the view: returning a non-`User` from an authentication class breaks `IsAuthenticated` in confusing ways.

- [ ] **Step 1: Write the failing test**

Create `src/lamto/api/tests/test_gate_recognize_api.py`:

```python
import pytest
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from lamto.gate.crypto import seal_embedding
from lamto.gate.devices import issue_credential, revoke_credential
from lamto.gate.models import (
    FaceEnrollment,
    GateDevice,
    GateEvent,
    ReviewStatus,
    VehiclePlate,
)
from lamto.gate.tests.conftest import (  # noqa: F401
    building,
    gate_storage,
    management,
    occupancy,
    second_occupancy,
    use_fake_embedder,
)
from lamto.gate.tests.fakes import (
    FAKE_MODEL_NAME,
    FAKE_MODEL_VERSION,
    face_bytes,
    fake_vector,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def reader(building, management):
    device = GateDevice.objects.create(
        building=building, label="North gate", direction=GateDevice.Direction.ENTRY
    )
    credential, token = issue_credential(device, management)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"GateDevice {token}")
    return {"client": client, "credential": credential, "token": token}


@pytest.fixture
def enrolled(occupancy, use_fake_embedder):
    return FaceEnrollment.objects.create(
        occupancy=occupancy,
        embedding=seal_embedding(fake_vector("nguyen")),
        model_name=FAKE_MODEL_NAME,
        model_version=FAKE_MODEL_VERSION,
        status=ReviewStatus.APPROVED,
    )


def test_a_known_face_returns_the_resident_and_unit(reader, enrolled, occupancy):
    response = reader["client"].post(
        reverse("api:gate-recognize-face"),
        {"photo": SimpleUploadedFile("f.jpg", face_bytes("nguyen"), content_type="image/jpeg")},
        format="multipart",
    )
    assert response.status_code == 200
    body = response.json()
    assert body["matched"] is True
    assert body["display_name"] == occupancy.user.display_name
    assert body["unit_label"] == occupancy.unit.label
    assert body["direction"] == "ENTRY"
    assert GateEvent.objects.count() == 1


def test_an_unknown_face_is_a_200_with_matched_false(reader, enrolled):
    response = reader["client"].post(
        reverse("api:gate-recognize-face"),
        {"photo": SimpleUploadedFile("f.jpg", face_bytes("stranger"), content_type="image/jpeg")},
        format="multipart",
    )
    assert response.status_code == 200
    assert response.json()["matched"] is False
    assert GateEvent.objects.count() == 1


def test_no_face_in_frame_is_a_422_and_logs_nothing(reader, enrolled):
    response = reader["client"].post(
        reverse("api:gate-recognize-face"),
        {"photo": SimpleUploadedFile("f.jpg", b"NOFACE", content_type="image/jpeg")},
        format="multipart",
    )
    assert response.status_code == 422
    assert response.json()["code"] == "gate_no_face_detected"
    assert not GateEvent.objects.exists()


def test_a_model_outage_is_a_503_and_logs_nothing(reader, enrolled, settings):
    settings.GATE_FACE_EMBEDDER = ""
    response = reader["client"].post(
        reverse("api:gate-recognize-face"),
        {"photo": SimpleUploadedFile("f.jpg", face_bytes("nguyen"), content_type="image/jpeg")},
        format="multipart",
    )
    assert response.status_code == 503
    assert response.json()["code"] == "gate_model_unavailable"
    assert not GateEvent.objects.exists()


def test_a_known_plate_returns_the_resident(reader, occupancy):
    VehiclePlate.objects.create(
        occupancy=occupancy,
        building=occupancy.unit.building,
        plate="51F12345",
        status=ReviewStatus.APPROVED,
    )
    response = reader["client"].post(
        reverse("api:gate-recognize-plate"), {"plate": "51F-123.45"}, format="json"
    )
    assert response.status_code == 200
    assert response.json()["matched"] is True
    assert response.json()["unit_label"] == occupancy.unit.label


def test_an_unusable_plate_read_is_a_422_and_logs_nothing(reader):
    response = reader["client"].post(
        reverse("api:gate-recognize-plate"), {"plate": "!!"}, format="json"
    )
    assert response.status_code == 422
    assert response.json()["code"] == "gate_plate_unreadable"
    assert not GateEvent.objects.exists()


def test_a_missing_credential_is_rejected(building, occupancy):
    response = APIClient().post(
        reverse("api:gate-recognize-plate"), {"plate": "51F12345"}, format="json"
    )
    assert response.status_code == 401
    assert response.json()["code"] == "gate_device_unauthenticated"


def test_an_unknown_token_does_not_reveal_device_existence(reader):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="GateDevice not-a-real-token")
    response = client.post(
        reverse("api:gate-recognize-plate"), {"plate": "51F12345"}, format="json"
    )
    assert response.status_code == 401
    assert response.json()["code"] == "gate_device_unauthenticated"


def test_a_revoked_credential_says_so(reader, management):
    revoke_credential(reader["credential"], management)
    response = reader["client"].post(
        reverse("api:gate-recognize-plate"), {"plate": "51F12345"}, format="json"
    )
    assert response.status_code == 401
    assert response.json()["code"] == "gate_device_revoked"


def test_a_resident_token_cannot_call_the_reader_endpoint(occupancy):
    from knox.models import AuthToken

    client = APIClient()
    _, token = AuthToken.objects.create(occupancy.user)
    client.credentials(HTTP_AUTHORIZATION=f"Token {token}")
    response = client.post(
        reverse("api:gate-recognize-plate"), {"plate": "51F12345"}, format="json"
    )
    assert response.status_code == 401
```

- [ ] **Step 2: Run test to verify it fails**

Run: `set -a && . .env && set +a && .venv/bin/python -m pytest src/lamto/api/tests/test_gate_recognize_api.py -v`
Expected: FAIL with `NoReverseMatch: 'gate-recognize-face' is not a valid view function or pattern name`

- [ ] **Step 3: Add the serializers**

Append to `src/lamto/api/gate_serializers.py`:

```python
class RecognitionOutcomeSerializer(serializers.Serializer):
    matched = serializers.BooleanField()
    display_name = serializers.CharField(allow_blank=True)
    unit_label = serializers.CharField(allow_blank=True)
    direction = serializers.CharField()
    score = serializers.FloatField(allow_null=True)


class PlateRecognizeSerializer(serializers.Serializer):
    plate = serializers.CharField(
        max_length=64, help_text="Plate text as the reader's OCR produced it."
    )


class FaceRecognizeSerializer(serializers.Serializer):
    photo = serializers.FileField(
        help_text="Captured frame. Embedded in memory and discarded; never stored."
    )
```

- [ ] **Step 4: Add the views**

Append to `src/lamto/api/gate_views.py` (add the imports at the top of the file):

```python
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter

from lamto.accounts.security import client_ip
from lamto.api.gate_serializers import (
    FaceRecognizeSerializer,
    PlateRecognizeSerializer,
    RecognitionOutcomeSerializer,
)
from lamto.api.problems import (
    GateDeviceExpired,
    GateDeviceRevoked,
    GateDeviceUnauthenticated,
)
from lamto.gate.devices import (
    AUTH_SCHEME,
    GateAuthenticationFailed,
    GateCredentialExpired,
    GateCredentialRevoked,
    authenticate_device,
    token_from_header,
)
from lamto.gate.recognition import recognize_face, recognize_plate
```

```python
GATE_DEVICE_HEADER = OpenApiParameter(
    name="Authorization",
    type=OpenApiTypes.STR,
    location=OpenApiParameter.HEADER,
    required=True,
    description=f"Reader credential: `{AUTH_SCHEME} <token>`. Not a user session.",
)


def _outcome_payload(outcome) -> dict:
    return {
        "matched": outcome.matched,
        "display_name": outcome.display_name,
        "unit_label": outcome.unit_label,
        "direction": outcome.direction,
        "score": outcome.score,
    }


def _credential_for(request):
    """Resolve the reader credential, or raise the right 401.

    Device auth is done here rather than in a DRF authentication class: those
    must return a ``User``, and a gate reader is not a person in the
    accountability model.
    """
    token = token_from_header(request.headers.get("Authorization"))
    try:
        return authenticate_device(token, ip=client_ip(request))
    except GateCredentialRevoked:
        raise GateDeviceRevoked()
    except GateCredentialExpired:
        raise GateDeviceExpired()
    except GateAuthenticationFailed:
        raise GateDeviceUnauthenticated()
    except DjangoPermissionDenied:
        raise exceptions.Throttled(detail="Too many attempts from this address.")


class GateRecognizeFaceView(APIView):
    authentication_classes = []
    permission_classes = []
    parser_classes = [parsers.MultiPartParser]

    @extend_schema(
        auth=[],
        parameters=[GATE_DEVICE_HEADER],
        request=FaceRecognizeSerializer,
        responses={
            200: RecognitionOutcomeSerializer,
            **problem_responses(400, 401, 422, 429, 503),
        },
    )
    def post(self, request):
        credential = _credential_for(request)
        serializer = FaceRecognizeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        image_bytes = serializer.validated_data["photo"].read()
        try:
            outcome = recognize_face(credential, image_bytes)
        except FaceQualityError as error:
            _raise_quality_problem(error)
        except FaceEmbedderUnavailable:
            raise GateModelUnavailable()
        return Response(RecognitionOutcomeSerializer(_outcome_payload(outcome)).data)


class GateRecognizePlateView(APIView):
    authentication_classes = []
    permission_classes = []

    @extend_schema(
        auth=[],
        parameters=[GATE_DEVICE_HEADER],
        request=PlateRecognizeSerializer,
        responses={
            200: RecognitionOutcomeSerializer,
            **problem_responses(400, 401, 422, 429),
        },
    )
    def post(self, request):
        credential = _credential_for(request)
        serializer = PlateRecognizeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            outcome = recognize_plate(credential, serializer.validated_data["plate"])
        except PlateFormatError:
            raise GatePlateUnreadable()
        return Response(RecognitionOutcomeSerializer(_outcome_payload(outcome)).data)
```

Add `429` to `_PROBLEM_DESCRIPTIONS` usage — it already exists in `src/lamto/api/problems.py`, so no change is needed there.

- [ ] **Step 5: Wire the routes**

In `src/lamto/api/urls.py`, add after the `gate/face` path:

```python
    path("gate/recognize/face", gate_views.GateRecognizeFaceView.as_view(), name="gate-recognize-face"),
    path("gate/recognize/plate", gate_views.GateRecognizePlateView.as_view(), name="gate-recognize-plate"),
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `set -a && . .env && set +a && .venv/bin/python -m pytest src/lamto/api/tests/test_gate_recognize_api.py -v`
Expected: PASS, 10 passed

- [ ] **Step 7: Regenerate the schema and check the whole API suite**

Run: `set -a && . .env && set +a && .venv/bin/python manage.py spectacular --file docs/api/openapi-v1.yaml`
Then: `set -a && . .env && set +a && .venv/bin/python -m pytest src/lamto/api -v`
Expected: PASS, all API tests including `test_openapi.py`

- [ ] **Step 8: Commit**

```bash
git add src/lamto/api/gate_serializers.py src/lamto/api/gate_views.py \
  src/lamto/api/urls.py src/lamto/api/tests/test_gate_recognize_api.py \
  docs/api/openapi-v1.yaml
git commit -m "feat(api): add device-authenticated face and plate recognition endpoints"
```

---

### Task 12: Management workspace

**Files:**
- Create: `src/lamto/web/views/gate.py`
- Create: `src/lamto/web/templates/web/staff/gate_queue.html`, `gate_registrations.html`, `gate_devices.html`, `gate_log.html`
- Modify: `src/lamto/web/urls.py`, `src/lamto/web/staff.py` (`nav_items_for` ~line 54)
- Test: `src/lamto/web/tests/test_gate_views.py`

**Interfaces:**
- Consumes: `require_management_context`, `staff_context` from `lamto.web.staff`; review services (Task 6); device services (Task 8); models (Task 2).
- Produces: routes `web:gate-queue`, `web:gate-face-photo`, `web:gate-face-decide`, `web:gate-plate-decide`, `web:gate-registrations`, `web:gate-devices`, `web:gate-log`.

The pending photo is served through a view, never a public URL: the private bucket is not browsable and the image must not outlive the decision.

- [ ] **Step 1: Write the failing test**

Create `src/lamto/web/tests/test_gate_views.py`:

```python
from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from lamto.gate.devices import issue_credential
from lamto.gate.enrollment import submit_face_enrollment, submit_plate
from lamto.gate.models import (
    GateDevice,
    GateDeviceCredential,
    GateEvent,
    PendingEnrollmentPhoto,
    ReviewStatus,
)
from lamto.gate.tests.conftest import (  # noqa: F401
    building,
    gate_storage,
    management,
    occupancy,
    second_occupancy,
    use_fake_embedder,
)
from lamto.gate.tests.fakes import face_bytes

pytestmark = pytest.mark.django_db


@pytest.fixture
def staff(management):
    """MFA-verified management session, matching the pattern in
    src/lamto/web/tests/test_management_workspace.py::authenticate_management."""
    import time

    from django_otp.plugins.otp_totp.models import TOTPDevice
    from django_otp.util import random_hex
    from django_otp.middleware import OTPMiddleware  # noqa: F401
    from django_otp import DEVICE_ID_SESSION_KEY

    from lamto.accounts.security import RECENT_REAUTH_KEY

    client = Client()
    management.user.set_password("secret")
    management.user.save()
    client.force_login(management.user)
    device = TOTPDevice.objects.create(
        user=management.user, name="test", confirmed=True, key=random_hex()
    )
    session = client.session
    session[DEVICE_ID_SESSION_KEY] = device.persistent_id
    session[RECENT_REAUTH_KEY] = time.time()
    session.save()
    return client


@pytest.fixture
def enrolled(occupancy, use_fake_embedder, gate_storage, monkeypatch):
    monkeypatch.setattr("lamto.gate.enrollment.scan_with_clamav", lambda f: True)
    return submit_face_enrollment(
        occupancy,
        SimpleUploadedFile("f.jpg", face_bytes("nguyen"), content_type="image/jpeg"),
    )


def test_the_queue_lists_pending_registrations(staff, enrolled, occupancy):
    submit_plate(occupancy, "51F12345")
    response = staff.get(reverse("web:gate-queue"))
    assert response.status_code == 200
    assert occupancy.unit.label in response.content.decode()
    assert "51F12345" in response.content.decode()


def test_the_queue_serves_the_pending_photo(staff, enrolled):
    response = staff.get(reverse("web:gate-face-photo", args=[enrolled.pk]))
    assert response.status_code == 200
    assert response["Content-Type"] == "image/jpeg"


def test_the_photo_is_gone_after_a_decision(staff, enrolled):
    staff.post(
        reverse("web:gate-face-decide", args=[enrolled.pk]), {"decision": "approve"}
    )
    assert not PendingEnrollmentPhoto.objects.exists()
    assert staff.get(reverse("web:gate-face-photo", args=[enrolled.pk])).status_code == 404


def test_approving_a_face_records_the_manager(staff, enrolled, management):
    staff.post(
        reverse("web:gate-face-decide", args=[enrolled.pk]), {"decision": "approve"}
    )
    enrolled.refresh_from_db()
    assert enrolled.status == ReviewStatus.APPROVED
    assert enrolled.reviewed_by_id == management.user_id


def test_rejecting_without_a_reason_is_refused(staff, enrolled):
    response = staff.post(
        reverse("web:gate-face-decide", args=[enrolled.pk]),
        {"decision": "reject", "note": "  "},
        follow=True,
    )
    enrolled.refresh_from_db()
    assert enrolled.status == ReviewStatus.PENDING
    assert response.status_code == 200


def test_a_device_credential_is_shown_once(staff, building):
    response = staff.post(
        reverse("web:gate-devices"),
        {"action": "create", "label": "North gate", "direction": "ENTRY"},
        follow=True,
    )
    body = response.content.decode()
    assert "North gate" in body
    credential = GateDeviceCredential.objects.get()
    assert credential.token_sha256 not in body


def test_rotating_keeps_the_old_credential_during_the_grace(staff, building, management):
    device = GateDevice.objects.create(
        building=building, label="North", direction=GateDevice.Direction.ENTRY
    )
    old, _ = issue_credential(device, management)
    staff.post(
        reverse("web:gate-devices"), {"action": "rotate", "device": device.pk}
    )
    old.refresh_from_db()
    assert old.revoked_at is None
    assert old.expires_at > timezone.now()


def test_the_log_is_a_rolling_window_with_no_date_filter(staff, building, occupancy):
    device = GateDevice.objects.create(
        building=building, label="North", direction=GateDevice.Direction.ENTRY
    )
    GateEvent.objects.create(
        building=building,
        device=device,
        kind=GateEvent.Kind.PLATE,
        direction=device.direction,
        occurred_at=timezone.now() - timedelta(minutes=5),
        normalized_plate_text="51F12345",
    )
    response = staff.get(reverse("web:gate-log"))
    body = response.content.decode()
    assert response.status_code == 200
    assert "51F12345" in body
    assert 'type="date"' not in body


def test_an_unrecognized_sighting_is_shown_not_hidden(staff, building):
    device = GateDevice.objects.create(
        building=building, label="North", direction=GateDevice.Direction.ENTRY
    )
    GateEvent.objects.create(
        building=building,
        device=device,
        kind=GateEvent.Kind.FACE,
        direction=device.direction,
        occurred_at=timezone.now(),
        match_score=0.1,
    )
    response = staff.get(reverse("web:gate-log"))
    assert "Unrecognized" in response.content.decode()


def test_the_pages_require_management(client, building):
    for name in ["web:gate-queue", "web:gate-registrations", "web:gate-devices", "web:gate-log"]:
        response = Client().get(reverse(name))
        assert response.status_code in (302, 403)
```

The `staff` fixture reproduces `authenticate_management` from `src/lamto/web/tests/test_management_workspace.py:22`, which is how every existing staff view test gets past `require_staff_mfa`. Do not invent a different login path.

- [ ] **Step 2: Run test to verify it fails**

Run: `set -a && . .env && set +a && .venv/bin/python -m pytest src/lamto/web/tests/test_gate_views.py -v`
Expected: FAIL with `NoReverseMatch: 'gate-queue' is not a valid view function or pattern name`

- [ ] **Step 3: Write the views**

Create `src/lamto/web/views/gate.py`:

```python
"""Management workspace for gate registrations, readers, and the live log.

The pending-photo view is the identity check. It is the only place a face
image is ever displayed, it is served through Django rather than a public
URL, and it stops working the moment a decision is recorded.
"""

from django.contrib import messages
from django.core.files.storage import storages
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET, require_http_methods

from lamto.gate.devices import issue_credential, revoke_credential, rotate_credential
from lamto.gate.models import (
    FaceEnrollment,
    GateDevice,
    GateDeviceCredential,
    GateEvent,
    PendingEnrollmentPhoto,
    ReviewStatus,
    VehiclePlate,
)
from lamto.gate.retention import purge_is_stale
from lamto.gate.review import (
    ReviewNotPossible,
    approve_face,
    approve_plate,
    reject_face,
    reject_plate,
    revoke_face,
    revoke_plate_as_manager,
)
from lamto.web.staff import require_management_context, staff_context

NAV_KEY = "gate"


@require_GET
def gate_queue(request):
    membership, memberships = require_management_context(request)
    faces = (
        FaceEnrollment.objects.filter(
            status=ReviewStatus.PENDING,
            occupancy__unit__building=membership.building,
            pending_photo__isnull=False,
        )
        .select_related("occupancy__user", "occupancy__unit", "pending_photo")
        .order_by("submitted_at")
    )
    plates = (
        VehiclePlate.objects.filter(
            status=ReviewStatus.PENDING, building=membership.building
        )
        .select_related("occupancy__user", "occupancy__unit")
        .order_by("submitted_at")
    )
    return render(
        request,
        "web/staff/gate_queue.html",
        staff_context(
            request,
            membership,
            memberships,
            nav_active=NAV_KEY,
            pending_faces=faces,
            pending_plates=plates,
        ),
    )


@require_GET
def gate_face_photo(request, pk):
    """Serve the review image. 404 once the decision deleted it."""
    membership, _ = require_management_context(request)
    photo = get_object_or_404(
        PendingEnrollmentPhoto.objects.select_related("enrollment__occupancy__unit"),
        enrollment_id=pk,
        enrollment__occupancy__unit__building=membership.building,
    )
    try:
        handle = storages["private"].open(photo.storage_key, "rb")
    except (FileNotFoundError, OSError) as error:
        raise Http404("Review photo is no longer available.") from error
    return FileResponse(handle, content_type=photo.content_type or "image/jpeg")


@require_http_methods(["POST"])
def gate_face_decide(request, pk):
    membership, _ = require_management_context(request)
    enrollment = get_object_or_404(
        FaceEnrollment.objects.select_related("occupancy__unit"),
        pk=pk,
        occupancy__unit__building=membership.building,
    )
    decision = request.POST.get("decision")
    try:
        if decision == "approve":
            approve_face(enrollment, membership)
            messages.success(request, _("Face enrolment approved."))
        elif decision == "reject":
            reject_face(enrollment, membership, request.POST.get("note", ""))
            messages.success(request, _("Face enrolment rejected."))
        elif decision == "revoke":
            revoke_face(enrollment, membership)
            messages.success(request, _("Face enrolment revoked."))
        else:
            messages.error(request, _("Unknown decision. Nothing was saved."))
    except ReviewNotPossible as error:
        messages.error(request, str(error))
    return redirect(request.POST.get("next") or "web:gate-queue")


@require_http_methods(["POST"])
def gate_plate_decide(request, pk):
    membership, _ = require_management_context(request)
    plate = get_object_or_404(VehiclePlate, pk=pk, building=membership.building)
    decision = request.POST.get("decision")
    try:
        if decision == "approve":
            approve_plate(plate, membership)
            messages.success(request, _("Plate approved."))
        elif decision == "reject":
            reject_plate(plate, membership, request.POST.get("note", ""))
            messages.success(request, _("Plate rejected."))
        elif decision == "revoke":
            revoke_plate_as_manager(plate, membership)
            messages.success(request, _("Plate revoked."))
        else:
            messages.error(request, _("Unknown decision. Nothing was saved."))
    except ReviewNotPossible as error:
        messages.error(request, str(error))
    return redirect(request.POST.get("next") or "web:gate-queue")


@require_GET
def gate_registrations(request):
    membership, memberships = require_management_context(request)
    faces = (
        FaceEnrollment.objects.filter(
            status=ReviewStatus.APPROVED,
            occupancy__unit__building=membership.building,
        )
        .select_related("occupancy__user", "occupancy__unit")
        .order_by("occupancy__unit__label")
    )
    plates = (
        VehiclePlate.objects.filter(
            status=ReviewStatus.APPROVED, building=membership.building
        )
        .select_related("occupancy__user", "occupancy__unit")
        .order_by("plate")
    )
    return render(
        request,
        "web/staff/gate_registrations.html",
        staff_context(
            request,
            membership,
            memberships,
            nav_active=NAV_KEY,
            faces=faces,
            plates=plates,
        ),
    )


@require_http_methods(["GET", "POST"])
def gate_devices(request):
    membership, memberships = require_management_context(request)
    issued_token = None
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "create":
            label = (request.POST.get("label") or "").strip()
            direction = request.POST.get("direction")
            if not label or direction not in GateDevice.Direction.values:
                messages.error(request, _("A label and a direction are required."))
            else:
                device = GateDevice.objects.create(
                    building=membership.building, label=label, direction=direction
                )
                _, issued_token = issue_credential(device, membership)
                messages.success(request, _("Reader registered."))
        elif action == "rotate":
            device = get_object_or_404(
                GateDevice, pk=request.POST.get("device"), building=membership.building
            )
            _, issued_token = rotate_credential(device, membership)
            messages.success(
                request,
                _("New credential issued. The previous one keeps working during the grace period."),
            )
        elif action == "revoke":
            credential = get_object_or_404(
                GateDeviceCredential,
                pk=request.POST.get("credential"),
                device__building=membership.building,
            )
            revoke_credential(credential, membership)
            messages.success(request, _("Credential revoked. It stops working now."))

    devices = (
        GateDevice.objects.filter(building=membership.building)
        .prefetch_related("credentials")
        .order_by("label")
    )
    return render(
        request,
        "web/staff/gate_devices.html",
        staff_context(
            request,
            membership,
            memberships,
            nav_active=NAV_KEY,
            devices=devices,
            directions=GateDevice.Direction.choices,
            issued_token=issued_token,
        ),
    )


@require_GET
def gate_log(request):
    membership, memberships = require_management_context(request)
    events = (
        GateEvent.objects.filter(building=membership.building)
        .select_related("device", "matched_occupancy__user", "matched_occupancy__unit")
        .order_by("-occurred_at")[:500]
    )
    return render(
        request,
        "web/staff/gate_log.html",
        staff_context(
            request,
            membership,
            memberships,
            nav_active=NAV_KEY,
            events=events,
            purge_stale=purge_is_stale(),
        ),
    )
```

- [ ] **Step 4: Write the templates**

Create `src/lamto/web/templates/web/staff/gate_queue.html`:

```html
{% extends "web/staff/shell.html" %}
{% load i18n %}
{% block title %}{% trans "Gate review" %} · LamTo{% endblock %}
{% block content %}
<section class="panel" aria-labelledby="gate-faces-heading">
  <div class="panel-header">
    <h2 id="gate-faces-heading">{% trans "Faces awaiting review" %}</h2>
  </div>
  <p class="health-detail">
    {% trans "Compare the photo with the resident record. This is the only identity check in the system: the app performs no liveness detection." %}
  </p>
  {% for enrollment in pending_faces %}
  <article class="task-row">
    <img src="{% url 'web:gate-face-photo' enrollment.pk %}"
         alt="{% blocktrans with name=enrollment.occupancy.user.display_name %}Enrolment photo submitted by {{ name }}{% endblocktrans %}"
         width="180" height="180">
    <div>
      <p><strong>{{ enrollment.occupancy.user.display_name }}</strong></p>
      <p>{% trans "Unit" %} {{ enrollment.occupancy.unit.label }}</p>
      <p>{% trans "Submitted" %} {{ enrollment.submitted_at }}</p>
    </div>
    <form method="post" action="{% url 'web:gate-face-decide' enrollment.pk %}">
      {% csrf_token %}
      <label for="face-note-{{ enrollment.pk }}">{% trans "Reason (required to reject)" %}</label>
      <input class="input" id="face-note-{{ enrollment.pk }}" name="note" type="text" maxlength="255">
      <button class="button button-primary" name="decision" value="approve" type="submit">{% trans "Approve" %}</button>
      <button class="button button-secondary" name="decision" value="reject" type="submit">{% trans "Reject" %}</button>
    </form>
  </article>
  {% empty %}
  <p>{% trans "No faces are waiting for review." %}</p>
  {% endfor %}
</section>

<section class="panel" aria-labelledby="gate-plates-heading">
  <div class="panel-header">
    <h2 id="gate-plates-heading">{% trans "Plates awaiting review" %}</h2>
  </div>
  {% for plate in pending_plates %}
  <article class="task-row">
    <p><strong>{{ plate.plate }}</strong></p>
    <p>{{ plate.occupancy.user.display_name }} — {% trans "Unit" %} {{ plate.occupancy.unit.label }}</p>
    <form method="post" action="{% url 'web:gate-plate-decide' plate.pk %}">
      {% csrf_token %}
      <label for="plate-note-{{ plate.pk }}">{% trans "Reason (required to reject)" %}</label>
      <input class="input" id="plate-note-{{ plate.pk }}" name="note" type="text" maxlength="255">
      <button class="button button-primary" name="decision" value="approve" type="submit">{% trans "Approve" %}</button>
      <button class="button button-secondary" name="decision" value="reject" type="submit">{% trans "Reject" %}</button>
    </form>
  </article>
  {% empty %}
  <p>{% trans "No plates are waiting for review." %}</p>
  {% endfor %}
</section>
{% endblock %}
```

Create `src/lamto/web/templates/web/staff/gate_registrations.html`:

```html
{% extends "web/staff/shell.html" %}
{% load i18n %}
{% block title %}{% trans "Gate registrations" %} · LamTo{% endblock %}
{% block content %}
<section class="panel" aria-labelledby="gate-approved-faces">
  <div class="panel-header"><h2 id="gate-approved-faces">{% trans "Approved faces" %}</h2></div>
  <table class="staff-table">
    <thead><tr>
      <th scope="col">{% trans "Resident" %}</th>
      <th scope="col">{% trans "Unit" %}</th>
      <th scope="col">{% trans "Approved by" %}</th>
      <th scope="col"><span class="visually-hidden">{% trans "Actions" %}</span></th>
    </tr></thead>
    <tbody>
    {% for enrollment in faces %}
      <tr>
        <td>{{ enrollment.occupancy.user.display_name }}</td>
        <td>{{ enrollment.occupancy.unit.label }}</td>
        <td>{{ enrollment.reviewed_by.display_name }}</td>
        <td>
          <form method="post" action="{% url 'web:gate-face-decide' enrollment.pk %}">
            {% csrf_token %}
            <input type="hidden" name="next" value="{% url 'web:gate-registrations' %}">
            <button class="button button-secondary" name="decision" value="revoke" type="submit">{% trans "Revoke" %}</button>
          </form>
        </td>
      </tr>
    {% empty %}
      <tr><td colspan="4">{% trans "No approved faces." %}</td></tr>
    {% endfor %}
    </tbody>
  </table>
</section>

<section class="panel" aria-labelledby="gate-approved-plates">
  <div class="panel-header"><h2 id="gate-approved-plates">{% trans "Approved plates" %}</h2></div>
  <table class="staff-table">
    <thead><tr>
      <th scope="col">{% trans "Plate" %}</th>
      <th scope="col">{% trans "Resident" %}</th>
      <th scope="col">{% trans "Unit" %}</th>
      <th scope="col"><span class="visually-hidden">{% trans "Actions" %}</span></th>
    </tr></thead>
    <tbody>
    {% for plate in plates %}
      <tr>
        <td>{{ plate.plate }}</td>
        <td>{{ plate.occupancy.user.display_name }}</td>
        <td>{{ plate.occupancy.unit.label }}</td>
        <td>
          <form method="post" action="{% url 'web:gate-plate-decide' plate.pk %}">
            {% csrf_token %}
            <input type="hidden" name="next" value="{% url 'web:gate-registrations' %}">
            <button class="button button-secondary" name="decision" value="revoke" type="submit">{% trans "Revoke" %}</button>
          </form>
        </td>
      </tr>
    {% empty %}
      <tr><td colspan="4">{% trans "No approved plates." %}</td></tr>
    {% endfor %}
    </tbody>
  </table>
</section>
{% endblock %}
```

Create `src/lamto/web/templates/web/staff/gate_devices.html`:

```html
{% extends "web/staff/shell.html" %}
{% load i18n %}
{% block title %}{% trans "Gate readers" %} · LamTo{% endblock %}
{% block content %}
{% if issued_token %}
<section class="panel" aria-labelledby="gate-token-heading">
  <div class="panel-header"><h2 id="gate-token-heading">{% trans "New reader credential" %}</h2></div>
  <p>{% trans "Copy this now. It is shown once and cannot be retrieved again." %}</p>
  <p class="hash-value"><code>{{ issued_token }}</code></p>
</section>
{% endif %}

<section class="panel" aria-labelledby="gate-add-reader">
  <div class="panel-header"><h2 id="gate-add-reader">{% trans "Register a reader" %}</h2></div>
  <form method="post">
    {% csrf_token %}
    <input type="hidden" name="action" value="create">
    <label for="reader-label">{% trans "Label" %}</label>
    <input class="input" id="reader-label" name="label" type="text" maxlength="120" required>
    <label for="reader-direction">{% trans "Direction" %}</label>
    <select class="input" id="reader-direction" name="direction" required>
      {% for value, label in directions %}<option value="{{ value }}">{{ label }}</option>{% endfor %}
    </select>
    <button class="button button-primary" type="submit">{% trans "Register" %}</button>
  </form>
</section>

<section class="panel" aria-labelledby="gate-readers-heading">
  <div class="panel-header"><h2 id="gate-readers-heading">{% trans "Readers" %}</h2></div>
  {% for device in devices %}
  <article class="task-row">
    <p><strong>{{ device.label }}</strong> — {{ device.get_direction_display }}</p>
    <p>{% trans "Last seen (hour)" %}: {{ device.last_seen_hour|default:"—" }}</p>
    <form method="post">
      {% csrf_token %}
      <input type="hidden" name="action" value="rotate">
      <input type="hidden" name="device" value="{{ device.pk }}">
      <button class="button button-secondary" type="submit">{% trans "Rotate credential" %}</button>
    </form>
    <ul>
      {% for credential in device.credentials.all %}
      <li>
        {% trans "Issued" %} {{ credential.created_at }}
        {% if credential.revoked_at %}<span class="status-pill status-pill-mismatch">{% trans "Revoked" %}</span>
        {% elif credential.expires_at %}<span class="status-pill status-pill-pending">{% trans "Expires" %} {{ credential.expires_at }}</span>
        {% else %}<span class="status-pill status-pill-verified">{% trans "Active" %}</span>{% endif %}
        {% if not credential.revoked_at %}
        <form method="post">
          {% csrf_token %}
          <input type="hidden" name="action" value="revoke">
          <input type="hidden" name="credential" value="{{ credential.pk }}">
          <button class="button button-secondary" type="submit">{% trans "Revoke now" %}</button>
        </form>
        {% endif %}
      </li>
      {% endfor %}
    </ul>
  </article>
  {% empty %}
  <p>{% trans "No readers registered." %}</p>
  {% endfor %}
</section>
{% endblock %}
```

Create `src/lamto/web/templates/web/staff/gate_log.html`:

```html
{% extends "web/staff/shell.html" %}
{% load i18n %}
{% block title %}{% trans "Gate activity" %} · LamTo{% endblock %}
{% block content %}
<section class="panel" aria-labelledby="gate-log-heading">
  <div class="panel-header">
    <h2 id="gate-log-heading">{% trans "Gate activity — last 24 hours" %}</h2>
  </div>
  <p class="health-detail">
    {% trans "This is a rolling view, not a history. Every entry is deleted 24 hours after it happened, so there is nothing older to search for." %}
  </p>
  {% if purge_stale %}
  <p class="status-pill status-pill-mismatch">
    {% trans "The retention job has not run recently. Entries may be older than 24 hours." %}
  </p>
  {% endif %}
  <table class="staff-table">
    <thead><tr>
      <th scope="col">{% trans "Time" %}</th>
      <th scope="col">{% trans "Reader" %}</th>
      <th scope="col">{% trans "Direction" %}</th>
      <th scope="col">{% trans "Identified" %}</th>
      <th scope="col">{% trans "Detail" %}</th>
    </tr></thead>
    <tbody>
    {% for event in events %}
      <tr>
        <td>{{ event.occurred_at }}</td>
        <td>{{ event.device.label }}</td>
        <td>{{ event.get_direction_display }}</td>
        <td>
          {% if event.matched_occupancy %}
            {{ event.matched_occupancy.user.display_name }} — {% trans "Unit" %} {{ event.matched_occupancy.unit.label }}
          {% else %}
            <span class="status-pill status-pill-pending">{% trans "Unrecognized" %}</span>
          {% endif %}
        </td>
        <td>
          {% if event.kind == "PLATE" %}{{ event.normalized_plate_text }}
          {% else %}{% trans "Face" %}{% if event.match_score %} ({{ event.match_score|floatformat:2 }}){% endif %}{% endif %}
        </td>
      </tr>
    {% empty %}
      <tr><td colspan="5">{% trans "No gate activity in the last 24 hours." %}</td></tr>
    {% endfor %}
    </tbody>
  </table>
</section>
{% endblock %}
```

- [ ] **Step 5: Wire routes and navigation**

In `src/lamto/web/urls.py`, add `gate` to the views import and these paths after the Exports block:

```python
    # Gate
    path("s/gate/", gate.gate_queue, name="gate-queue"),
    path("s/gate/face/<int:pk>/photo/", gate.gate_face_photo, name="gate-face-photo"),
    path("s/gate/face/<int:pk>/decide/", gate.gate_face_decide, name="gate-face-decide"),
    path("s/gate/plates/<int:pk>/decide/", gate.gate_plate_decide, name="gate-plate-decide"),
    path("s/gate/registrations/", gate.gate_registrations, name="gate-registrations"),
    path("s/gate/devices/", gate.gate_devices, name="gate-devices"),
    path("s/gate/log/", gate.gate_log, name="gate-log"),
```

In `src/lamto/web/staff.py`, add to the list returned by `nav_items_for`, before the Ops entry:

```python
        {"label": _("Gate"), "url_name": "web:gate-queue", "active_key": "gate"},
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `set -a && . .env && set +a && .venv/bin/python -m pytest src/lamto/web/tests/test_gate_views.py -v`
Expected: PASS, 10 passed

- [ ] **Step 7: Commit**

```bash
git add src/lamto/web/views/gate.py src/lamto/web/templates/web/staff/gate_*.html \
  src/lamto/web/urls.py src/lamto/web/staff.py src/lamto/web/tests/test_gate_views.py
git commit -m "feat(staff): review gate registrations, manage readers, watch the live log"
```

---

### Task 13: Production face embedder

**Files:**
- Modify: `src/lamto/gate/embedding.py`
- Modify: `pyproject.toml` (dependencies + `insightface` marker)
- Modify: `src/lamto/config/settings.py` (`GATE_FACE_EMBEDDER` default)
- Modify: `.env.example`, `ops/deployment-checklist.md`
- Test: `src/lamto/gate/tests/test_insightface_embedder.py`

**Interfaces:**
- Consumes: the Protocol and error classes (Task 4).
- Produces: `InsightFaceEmbedder` implementing `FaceEmbedder`, with `MODEL_NAME = "buffalo_l"` and `MODEL_VERSION` pinned to the installed insightface version.

`buffalo_l` is RetinaFace-10GF detection plus a ResNet50@WebFace600K recognition model, 326MB, and `Face.normed_embedding` is already L2-normalized — so cosine similarity is a dot product. The model files must be **baked into the deployment image**, not downloaded on first use: a model that downloads at runtime is a silent version drift and a cold-start outage.

- [ ] **Step 1: Add the dependencies**

In `pyproject.toml`, add to `dependencies`:

```toml
  "onnxruntime>=1.20,<2",
  "insightface>=0.7.3,<0.8",
  "opencv-python-headless>=4.10,<5",
```

Add to `[tool.pytest.ini_options]`:

```toml
markers = [
  "insightface: exercises the real InsightFace model; needs model files, deselected by default",
]
```

Run: `set -a && . .env && set +a && .venv/bin/python -m pip install "onnxruntime>=1.20,<2" "insightface>=0.7.3,<0.8" "opencv-python-headless>=4.10,<5"`
Expected: all three installed.

- [ ] **Step 2: Write the opt-in test**

Create `src/lamto/gate/tests/test_insightface_embedder.py`:

```python
"""Opt-in checks against the real model.

Run with: pytest -m insightface src/lamto/gate/tests/test_insightface_embedder.py

Needs the buffalo_l model files present (INSIGHTFACE_HOME) and a real face
photo at tests/fixtures/gate-face.jpg. Deselected in normal runs so CI never
downloads 326MB.
"""

from pathlib import Path

import numpy as np
import pytest

from lamto.gate.embedding import InsightFaceEmbedder, NoFaceDetected

pytestmark = pytest.mark.insightface

FIXTURE = Path(__file__).resolve().parents[4] / "tests" / "fixtures" / "gate-face.jpg"


def test_a_real_photo_yields_a_unit_length_512_vector():
    result = InsightFaceEmbedder().embed(FIXTURE.read_bytes())
    vector = np.array(result.vector)
    assert vector.shape == (512,)
    assert np.isclose(np.linalg.norm(vector), 1.0, atol=1e-4)
    assert result.model_name == "buffalo_l"
    assert result.model_version


def test_the_same_photo_embeds_identically():
    embedder = InsightFaceEmbedder()
    first = np.array(embedder.embed(FIXTURE.read_bytes()).vector)
    second = np.array(embedder.embed(FIXTURE.read_bytes()).vector)
    assert float(np.dot(first, second)) > 0.999


def test_an_undecodable_image_is_reported_as_no_face():
    with pytest.raises(NoFaceDetected):
        InsightFaceEmbedder().embed(b"not an image")
```

Add a real face photo at `tests/fixtures/gate-face.jpg` (any consenting person's clear frontal photo, or a public-domain portrait). Do not commit a resident's photo.

- [ ] **Step 3: Write the embedder**

Append to `src/lamto/gate/embedding.py`:

```python
class InsightFaceEmbedder:
    """buffalo_l: RetinaFace-10GF detection + ResNet50@WebFace600K recognition.

    ``Face.normed_embedding`` is already L2-normalized, so cosine similarity
    downstream is a plain dot product.

    The model pack is loaded once per process and cached on the class.
    onnxruntime sessions are safe for concurrent inference, so a single
    cached analysis object serves all workers in the process.

    The checks below are an IMAGE-QUALITY gate — one face, big enough, sharp
    enough. They are not liveness detection. A printed photo passes every one
    of them.
    """

    MODEL_NAME = "buffalo_l"

    _analysis = None

    @classmethod
    def _model(cls):
        if cls._analysis is None:
            try:
                from insightface.app import FaceAnalysis

                analysis = FaceAnalysis(
                    name=cls.MODEL_NAME,
                    allowed_modules=["detection", "recognition"],
                    providers=["CPUExecutionProvider"],
                )
                analysis.prepare(ctx_id=-1, det_size=(640, 640))
            except Exception as error:
                raise FaceEmbedderUnavailable(
                    f"InsightFace model could not be loaded: {error}"
                ) from error
            cls._analysis = analysis
        return cls._analysis

    @property
    def model_version(self) -> str:
        import insightface

        return f"insightface-{insightface.__version__}"

    def embed(self, image_bytes: bytes) -> EmbeddingResult:
        import cv2
        import numpy as np
        from django.conf import settings

        image = cv2.imdecode(
            np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_COLOR
        )
        if image is None:
            raise NoFaceDetected("Image could not be decoded.")

        try:
            faces = self._model().get(image)
        except FaceEmbedderUnavailable:
            raise
        except Exception as error:
            raise FaceEmbedderUnavailable(f"Face analysis failed: {error}") from error

        faces = [
            face
            for face in faces
            if float(face.det_score) >= settings.GATE_MIN_FACE_DET_SCORE
        ]
        if not faces:
            raise NoFaceDetected("No face detected in the image.")
        if len(faces) > 1:
            raise MultipleFacesDetected("More than one face detected in the image.")

        face = faces[0]
        x1, y1, x2, y2 = (int(v) for v in face.bbox)
        if min(x2 - x1, y2 - y1) < settings.GATE_MIN_FACE_PIXELS:
            raise FaceTooSmall("The face is too small in the frame.")

        crop = image[max(y1, 0) : max(y2, 0), max(x1, 0) : max(x2, 0)]
        if crop.size:
            sharpness = float(
                cv2.Laplacian(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var()
            )
            if sharpness < settings.GATE_MIN_FACE_SHARPNESS:
                raise FaceTooBlurry("The face is too blurry.")

        return EmbeddingResult(
            vector=face.normed_embedding.tolist(),
            model_name=self.MODEL_NAME,
            model_version=self.model_version,
            detection_score=float(face.det_score),
        )
```

- [ ] **Step 4: Point the setting at it**

In `src/lamto/config/settings.py`, change the `GATE_FACE_EMBEDDER` line and its comment to:

```python
GATE_FACE_EMBEDDER = os.getenv(
    "GATE_FACE_EMBEDDER", "lamto.gate.embedding.InsightFaceEmbedder"
)
```

Add to `.env.example`:

```
# Where the buffalo_l model pack lives. Bake it into the image; do not let the
# app download it at runtime.
INSIGHTFACE_HOME=/opt/insightface
```

Add to `ops/deployment-checklist.md`:

```markdown
- **Face model:** `buffalo_l` (~326MB) must be present under `INSIGHTFACE_HOME`
  in the built image. Never let the app download it on first request: that is a
  cold-start outage and an unpinned model version. Changing the model pack
  invalidates every stored embedding — residents must re-enrol, and the
  threshold must be re-calibrated (see Task 14).
```

- [ ] **Step 5: Verify the fake-backed suite still passes and the real test is deselected**

Run: `set -a && . .env && set +a && .venv/bin/python -m pytest src/lamto/gate -v`
Expected: PASS, with `test_insightface_embedder.py` items **deselected** — normal runs must not touch the model.

Run: `set -a && . .env && set +a && .venv/bin/python -m pytest -m insightface src/lamto/gate/tests/test_insightface_embedder.py -v`
Expected: PASS, 3 passed (only where model files and the fixture photo are available).

- [ ] **Step 6: Commit**

```bash
git add src/lamto/gate/embedding.py src/lamto/gate/tests/test_insightface_embedder.py \
  pyproject.toml src/lamto/config/settings.py .env.example ops/deployment-checklist.md
git commit -m "feat(gate): add the InsightFace production embedder behind the protocol"
```

---

### Task 14: Threshold calibration

**Files:**
- Create: `src/lamto/gate/calibration.py`
- Create: `src/lamto/gate/management/commands/calibrate_gate_threshold.py`
- Create: `docs/ops/gate-threshold-calibration.md` (procedure)
- Modify: `ops/pilot-runbook.md`
- Test: `src/lamto/gate/tests/test_calibration.py`

**Interfaces:**
- Consumes: `get_embedder` (Task 4), `open_embedding` (Task 3), models (Task 2).
- Produces: `score_pairs(building, probes) -> CalibrationScores`, `CalibrationScores(genuine: list[float], impostor: list[float])`, `error_rates(scores, threshold) -> tuple[float, float]` returning `(fmr, fnmr)`, `sweep(scores, start, stop, step) -> list[ThresholdRow]`, `ThresholdRow(threshold, fmr, fnmr, genuine_accepted, impostor_accepted)`, management command `calibrate_gate_threshold`.

**`GATE_FACE_MATCH_THRESHOLD = 0.38` is a starting point for an ArcFace-family model, not a validated value, and must never be what a pilot runs on.** InsightFace's own clustering tooling defaults to cosine `0.48`; `0.38` is deliberately more permissive, which trades false rejections for false matches — the wrong direction for a system that names residents. Every building's lighting, camera angle, and mounting height move the operating point. This task produces the number that replaces it.

#### Acceptance criteria

The calibration is complete only when **all** of these hold:

1. **Dataset size.** At least **20 distinct enrolled residents** from the pilot building, each with at least **5 probe captures**, giving **≥ 100 genuine comparisons** and **≥ 1,900 impostor comparisons** (every probe against every non-matching enrolment).
2. **Capture realism.** Probes are captured **at the installed reader, through the reader app**, not from phone galleries or ID photos. The set includes at least one capture per person **after dark** and at least one **in bright backlight**. Captures made anywhere other than the mounted reader do not count toward the minimum.
3. **Reported sweep.** The report tabulates, for every threshold from **0.30 to 0.60 in steps of 0.01**: FMR (share of impostor comparisons at or above the threshold) and FNMR (share of genuine comparisons below it).
4. **Operating point.** The chosen threshold satisfies **FMR = 0.0 across the entire impostor set** and **FNMR ≤ 5%**. A single impostor comparison at or above the threshold disqualifies it.
5. **Hard stop.** If no threshold in the swept range satisfies both, **face recognition does not go into the pilot.** Plate recognition ships alone and the face feature stays disabled. This is a gate, not a recommendation — a system that names the wrong resident is worse than one that names nobody.
6. **Sharpness floor.** The report includes the sharpness distribution of accepted genuine probes, and `GATE_MIN_FACE_SHARPNESS` is set **below the 5th percentile** so that real captures at the real reader are not rejected as blurry.
7. **Explicit configuration.** The pilot environment sets `GATE_FACE_MATCH_THRESHOLD` and `GATE_MIN_FACE_SHARPNESS` to the calibrated values **in its own env**. Relying on the code default is a failed acceptance criterion even if the value happens to coincide.
8. **Committed report.** `docs/ops/gate-threshold-calibration-<YYYY-MM-DD>.md` records the building, dates, model name and version, participant and probe counts, capture conditions, the full sweep table, the chosen values, and the name of the person who ran it.
9. **Re-calibration triggers.** The report states, and the runbook repeats, that calibration is invalid and must be redone when `model_name` or `model_version` changes, when a reader is physically moved or re-aimed, or when gate lighting changes.

- [ ] **Step 1: Write the failing test**

Create `src/lamto/gate/tests/test_calibration.py`:

```python
import pytest

from lamto.gate.calibration import CalibrationScores, error_rates, sweep

pytestmark = pytest.mark.django_db


def _scores():
    # Genuine scores cluster high, impostors low, with one awkward overlap.
    return CalibrationScores(
        genuine=[0.90, 0.85, 0.80, 0.55, 0.35],
        impostor=[0.10, 0.12, 0.20, 0.42],
    )


def test_error_rates_at_a_threshold():
    fmr, fnmr = error_rates(_scores(), 0.50)
    # No impostor reaches 0.50; one genuine of five (0.35) falls below it.
    assert fmr == pytest.approx(0.0)
    assert fnmr == pytest.approx(0.2)


def test_a_low_threshold_admits_an_impostor():
    fmr, _ = error_rates(_scores(), 0.40)
    assert fmr == pytest.approx(0.25)


def test_a_high_threshold_rejects_genuine_probes():
    _, fnmr = error_rates(_scores(), 0.95)
    assert fnmr == pytest.approx(1.0)


def test_the_sweep_covers_the_range_inclusively():
    rows = sweep(_scores(), 0.30, 0.60, 0.01)
    assert rows[0].threshold == pytest.approx(0.30)
    assert rows[-1].threshold == pytest.approx(0.60)
    assert len(rows) == 31


def test_the_sweep_reports_counts_alongside_rates():
    row = next(r for r in sweep(_scores(), 0.30, 0.60, 0.01) if r.threshold == pytest.approx(0.50))
    assert row.impostor_accepted == 0
    assert row.genuine_accepted == 4


def test_empty_score_sets_do_not_divide_by_zero():
    fmr, fnmr = error_rates(CalibrationScores(genuine=[], impostor=[]), 0.5)
    assert fmr == 0.0
    assert fnmr == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `set -a && . .env && set +a && .venv/bin/python -m pytest src/lamto/gate/tests/test_calibration.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'lamto.gate.calibration'`

- [ ] **Step 3: Write the calibration module**

Create `src/lamto/gate/calibration.py`:

```python
"""Threshold calibration for face matching.

GATE_FACE_MATCH_THRESHOLD ships at 0.38, which is a starting point for an
ArcFace-family model and NOT a validated production value. InsightFace's own
clustering tooling defaults to cosine 0.48; 0.38 is more permissive, trading
false rejections for false matches, which is the wrong direction for a system
that puts a resident's name on a screen. Every building moves the operating
point: lighting, camera angle, mounting height, and who is enrolled.

This module scores a labelled probe set against the building's live
enrolments and reports the error rates at each candidate threshold. The
operating point is chosen from that table, not from this file.
"""

from dataclasses import dataclass, field

import numpy as np

from .crypto import open_embedding
from .matching import unit_vector
from .models import FaceEnrollment, ReviewStatus


@dataclass
class CalibrationScores:
    genuine: list[float] = field(default_factory=list)
    impostor: list[float] = field(default_factory=list)


@dataclass(frozen=True)
class ThresholdRow:
    threshold: float
    fmr: float
    fnmr: float
    genuine_accepted: int
    impostor_accepted: int


def error_rates(scores: CalibrationScores, threshold: float) -> tuple[float, float]:
    """Return ``(fmr, fnmr)`` at ``threshold``.

    FMR is the share of impostor comparisons at or above the threshold — a
    stranger who would be given someone's name. FNMR is the share of genuine
    comparisons below it — a resident the reader fails to recognize.
    """
    impostor_accepted = sum(1 for s in scores.impostor if s >= threshold)
    genuine_rejected = sum(1 for s in scores.genuine if s < threshold)
    fmr = impostor_accepted / len(scores.impostor) if scores.impostor else 0.0
    fnmr = genuine_rejected / len(scores.genuine) if scores.genuine else 0.0
    return fmr, fnmr


def sweep(
    scores: CalibrationScores, start: float, stop: float, step: float
) -> list[ThresholdRow]:
    rows = []
    steps = int(round((stop - start) / step)) + 1
    for index in range(steps):
        threshold = round(start + index * step, 4)
        fmr, fnmr = error_rates(scores, threshold)
        rows.append(
            ThresholdRow(
                threshold=threshold,
                fmr=fmr,
                fnmr=fnmr,
                genuine_accepted=sum(1 for s in scores.genuine if s >= threshold),
                impostor_accepted=sum(1 for s in scores.impostor if s >= threshold),
            )
        )
    return rows


def score_pairs(building, probes) -> CalibrationScores:
    """Score every probe against every approved enrolment in ``building``.

    ``probes`` is an iterable of ``(occupancy_id, vector)``. Each probe
    produces one genuine comparison against its own enrolment and one
    impostor comparison against every other enrolment.
    """
    enrolments = {
        row.occupancy_id: unit_vector(open_embedding(row.embedding))
        for row in FaceEnrollment.objects.filter(
            status=ReviewStatus.APPROVED,
            embedding__isnull=False,
            occupancy__unit__building=building,
        )
    }
    scores = CalibrationScores()
    for occupancy_id, vector in probes:
        probe = unit_vector(vector)
        for enrolled_id, enrolled in enrolments.items():
            if probe.shape != enrolled.shape:
                continue
            score = float(np.dot(probe, enrolled))
            if enrolled_id == occupancy_id:
                scores.genuine.append(score)
            else:
                scores.impostor.append(score)
    return scores
```

- [ ] **Step 4: Write the command**

Create `src/lamto/gate/management/commands/calibrate_gate_threshold.py`:

```python
"""Score a labelled probe set and print the threshold sweep.

Probe directory layout — one subdirectory per enrolled occupancy id:

    probes/
      41/  capture-01.jpg  capture-02.jpg  ...
      42/  capture-01.jpg  ...

Captures must come from the installed reader, not a phone gallery. See
docs/ops/gate-threshold-calibration.md for the full procedure and the
acceptance criteria this output has to satisfy.
"""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from lamto.accounts.models import Building
from lamto.gate.calibration import score_pairs, sweep
from lamto.gate.embedding import FaceQualityError, get_embedder

START, STOP, STEP = 0.30, 0.60, 0.01


class Command(BaseCommand):
    help = (
        "Score probe captures against live enrolments and print FMR/FNMR per "
        "threshold. GATE_FACE_MATCH_THRESHOLD's default is NOT a production value."
    )

    def add_arguments(self, parser):
        parser.add_argument("--building", type=int, required=True)
        parser.add_argument(
            "--probes",
            required=True,
            help="Directory of <occupancy_id>/<image> captures from the reader.",
        )

    def handle(self, *args, **options):
        building = Building.objects.filter(pk=options["building"]).first()
        if building is None:
            raise CommandError(f"No building with id {options['building']}.")
        root = Path(options["probes"])
        if not root.is_dir():
            raise CommandError(f"{root} is not a directory.")

        embedder = get_embedder()
        probes = []
        skipped = 0
        people = 0
        for person_dir in sorted(p for p in root.iterdir() if p.is_dir()):
            try:
                occupancy_id = int(person_dir.name)
            except ValueError:
                raise CommandError(
                    f"{person_dir.name} is not an occupancy id; see the layout in --help."
                )
            people += 1
            for image in sorted(person_dir.iterdir()):
                if not image.is_file():
                    continue
                try:
                    result = embedder.embed(image.read_bytes())
                except FaceQualityError as error:
                    skipped += 1
                    self.stderr.write(f"skipped {image}: {error}")
                    continue
                probes.append((occupancy_id, result.vector))

        scores = score_pairs(building, probes)
        self.stdout.write(
            f"people={people} probes={len(probes)} skipped={skipped} "
            f"genuine={len(scores.genuine)} impostor={len(scores.impostor)}"
        )
        self.stdout.write("")
        self.stdout.write("| threshold | FMR | FNMR | genuine accepted | impostor accepted |")
        self.stdout.write("|---|---|---|---|---|")
        for row in sweep(scores, START, STOP, STEP):
            self.stdout.write(
                f"| {row.threshold:.2f} | {row.fmr:.4f} | {row.fnmr:.4f} | "
                f"{row.genuine_accepted} | {row.impostor_accepted} |"
            )

        viable = [r for r in sweep(scores, START, STOP, STEP) if r.fmr == 0.0 and r.fnmr <= 0.05]
        self.stdout.write("")
        if viable:
            best = min(viable, key=lambda r: r.fnmr)
            self.stdout.write(
                f"CANDIDATE GATE_FACE_MATCH_THRESHOLD={best.threshold:.2f} "
                f"(FMR=0, FNMR={best.fnmr:.4f})"
            )
        else:
            self.stdout.write(
                "NO VIABLE THRESHOLD: no value in 0.30-0.60 achieves FMR=0 with "
                "FNMR<=5%. Face recognition must not go into the pilot. Ship "
                "plate recognition alone."
            )
```

- [ ] **Step 5: Write the procedure document**

Create `docs/ops/gate-threshold-calibration.md` containing: the acceptance criteria list from this task verbatim; the probe-directory layout; the command invocation; instructions to capture through the mounted reader across lighting conditions; how to read the sweep table; where to record the result; and the re-calibration triggers.

Add to `ops/pilot-runbook.md`, in the pre-pilot section:

```markdown
- **Gate face threshold calibrated.** `GATE_FACE_MATCH_THRESHOLD` and
  `GATE_MIN_FACE_SHARPNESS` are set explicitly in the pilot environment from a
  committed calibration report. The shipped default of 0.38 is an unvalidated
  starting point and must never be what a pilot runs on. If no threshold
  achieves FMR=0 with FNMR<=5%, the pilot runs plate recognition only.
  Procedure: `docs/ops/gate-threshold-calibration.md`.
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `set -a && . .env && set +a && .venv/bin/python -m pytest src/lamto/gate/tests/test_calibration.py -v`
Expected: PASS, 6 passed

- [ ] **Step 7: Commit**

```bash
git add src/lamto/gate/calibration.py \
  src/lamto/gate/management/commands/calibrate_gate_threshold.py \
  src/lamto/gate/tests/test_calibration.py docs/ops/gate-threshold-calibration.md \
  ops/pilot-runbook.md
git commit -m "feat(gate): calibrate the face match threshold against real captures"
```

---

### Task 15: Resident app — vehicles and face

**Files:**
- Create: `app/lib/features/gate/gate_repository.dart`, `app/lib/features/gate/gate_registration_screen.dart`, `app/lib/features/gate/plate_text.dart`
- Modify: `app/lib/core/occupancy.dart`, `app/lib/core/failure.dart`, `app/lib/l10n/app_en.arb`, `app/lib/l10n/app_vi.arb`, `app/lib/features/account/account_screen.dart`
- Regenerate: `app/packages/lamto_api`
- Test: `app/test/gate_repository_contract_test.dart`, `app/test/gate_plate_text_test.dart`, `app/test/gate_registration_screen_test.dart`

**Interfaces:**
- Consumes: the schema routes from Tasks 10-11.
- Produces: `GateApiPaths`, `GateRepository` (abstract) with `fetchRegistrations()`, `addPlate(String)`, `deletePlate(int)`, `submitFace({required String path, required String filename})`, `deleteFace()`; `DioGateRepository`; `normalizePlateText(String)`; `gateRepositoryProvider`.

The Vietnamese copy for every new machine code lives here, not on the server. `normalizePlateText` must agree exactly with `normalize_plate` from Task 1 — same cases, same results.

- [ ] **Step 1: Regenerate the API client**

Run: `cd app && ./tool/generate_api.sh`
Expected: `packages/lamto_api` regenerated with a `GateApi` covering the five resident routes and the two reader routes.

Run: `cd app && ./tool/check_api_generated.sh`
Expected: clean — no drift.

- [ ] **Step 2: Write the failing plate-normalization test**

Create `app/test/gate_plate_text_test.dart`:

```dart
import 'package:flutter_test/flutter_test.dart';
import 'package:lamto/features/gate/plate_text.dart';

void main() {
  // These cases mirror src/lamto/gate/tests/test_plates.py exactly. The two
  // implementations must never disagree: the phone shows what the server stores.
  test('normalizes to uppercase alphanumeric', () {
    expect(normalizePlateText('51F-123.45'), '51F12345');
    expect(normalizePlateText('  51f 123 45 '), '51F12345');
    expect(normalizePlateText('29-A1 234.56'), '29A123456');
    expect(normalizePlateText('59X1-99999'), '59X199999');
    expect(normalizePlateText('51F12345'), '51F12345');
  });

  test('returns empty for input with no usable content', () {
    expect(normalizePlateText(''), '');
    expect(normalizePlateText('!!!'), '');
    expect(normalizePlateText('-.-'), '');
  });

  test('reports whether a normalized plate is a plausible length', () {
    expect(isPlausiblePlate('51F12345'), isTrue);
    expect(isPlausiblePlate('51F'), isFalse);
    expect(isPlausiblePlate('51F1234567890123'), isFalse);
  });
}
```

- [ ] **Step 3: Write the plate helper**

Create `app/lib/features/gate/plate_text.dart`:

```dart
/// Client-side plate normalization, mirroring `lamto.gate.plates`.
///
/// Only used to show the resident what the server will store as they type.
/// The server normalizes again and its result is authoritative.
library;

const int kPlateMinLength = 5;
const int kPlateMaxLength = 12;

final _nonAlnum = RegExp(r'[^A-Z0-9]');

String normalizePlateText(String raw) =>
    raw.toUpperCase().replaceAll(_nonAlnum, '');

bool isPlausiblePlate(String normalized) =>
    normalized.length >= kPlateMinLength &&
    normalized.length <= kPlateMaxLength;
```

- [ ] **Step 4: Run the plate test**

Run: `cd app && flutter test test/gate_plate_text_test.dart`
Expected: PASS, 3 tests

- [ ] **Step 5: Add the occupancy header prefix and the failure codes**

In `app/lib/core/occupancy.dart`, add to `buildingScopedPathPrefixes`:

```dart
  '/api/v1/gate/registrations',
  '/api/v1/gate/plates',
  '/api/v1/gate/face',
```

Do **not** add `/api/v1/gate/recognize` — the reader endpoints are device-authenticated and carry no occupancy.

In `app/lib/core/failure.dart`, add to `knownFailureCodes`:

```dart
  'gate_no_face_detected',
  'gate_multiple_faces',
  'gate_face_too_small',
  'gate_face_too_blurry',
  'gate_face_unusable',
  'gate_photo_rejected',
  'gate_plate_unreadable',
  'gate_plate_already_registered',
  'gate_model_unavailable',
  'gate_device_unauthenticated',
  'gate_device_revoked',
  'gate_device_expired',
```

Extend `failureMessage` with a case per code, resolving to the l10n getters added in the next step.

- [ ] **Step 6: Add the copy**

Add to `app/lib/l10n/app_en.arb`:

```json
  "gateTitle": "Vehicles & face",
  "gateSubtitle": "Register your vehicles and your face so the gate recognizes you.",
  "gatePlatesHeading": "Vehicles",
  "gateAddPlate": "Add a vehicle",
  "gatePlateLabel": "Licence plate",
  "gatePlateNormalizedHint": "Will be saved as {plate}",
  "gateFaceHeading": "Face",
  "gateFaceEnrol": "Take a photo",
  "gateFaceRetake": "Take a new photo",
  "gateFaceRemove": "Remove my face",
  "gateFacePhotoNotice": "Your photo is kept only until a manager reviews it, then it is deleted. Only a numeric code stays.",
  "gateStatusPending": "Waiting for review",
  "gateStatusApproved": "Approved",
  "gateStatusRejected": "Not approved",
  "gateStatusExpired": "Expired — please submit again",
  "errGateNoFace": "No face was found in the photo. Nothing was saved. Take another photo with your face in the frame.",
  "errGateMultipleFaces": "More than one face was found. Nothing was saved. Take a photo with only you in it.",
  "errGateFaceTooSmall": "Your face is too small in the photo. Nothing was saved. Hold the phone closer.",
  "errGateFaceTooBlurry": "The photo is too blurry. Nothing was saved. Hold still and try again.",
  "errGateFaceUnusable": "This photo cannot be used. Nothing was saved. Please take another one.",
  "errGatePhotoRejected": "This file was not accepted. Nothing was saved. Use a JPEG or PNG photo.",
  "errGatePlateUnreadable": "That does not look like a licence plate. Nothing was saved.",
  "errGatePlateTaken": "This plate is already registered in this building. Nothing was saved. Please contact building management.",
  "errGateModelUnavailable": "Face registration is unavailable right now. Nothing was saved. Please try again later.",
  "errGateDeviceUnauthenticated": "This reader is not recognized. Ask management for a new reader code.",
  "errGateDeviceRevoked": "This reader's access was revoked. Ask management for a new reader code.",
  "errGateDeviceExpired": "This reader's code has expired. Ask management for a new one."
```

Add the Vietnamese equivalents to `app/lib/l10n/app_vi.arb`. Every error string must state whether anything was saved, matching the existing `errNetwork` / `errThrottled` pattern — for example:

```json
  "errGateNoFace": "Không tìm thấy khuôn mặt trong ảnh. Chưa có gì được lưu. Hãy chụp lại với khuôn mặt trong khung hình.",
  "errGatePlateTaken": "Biển số này đã được đăng ký trong toà nhà. Chưa có gì được lưu. Vui lòng liên hệ ban quản lý."
```

Run: `cd app && flutter gen-l10n`
Expected: `app_localizations*.dart` regenerated with the new getters.

- [ ] **Step 7: Write the repository and its contract test**

Create `app/test/gate_repository_contract_test.dart`, modelled on `app/test/reports_repository_contract_test.dart`: load `docs/api/openapi-v1.yaml` from the same candidate paths and assert every constant in `GateApiPaths` appears as a path in the schema.

Create `app/lib/features/gate/gate_repository.dart`:

```dart
import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lamto_api/lamto_api.dart';

import '../../core/failure.dart';
import '../../core/providers.dart';

/// Paths used by the gate APIs — must exist in OpenAPI (contract tests).
abstract final class GateApiPaths {
  static const registrations = '/api/v1/gate/registrations';
  static const plates = '/api/v1/gate/plates';
  static const plateDetail = '/api/v1/gate/plates/{id}';
  static const face = '/api/v1/gate/face';
  static const recognizeFace = '/api/v1/gate/recognize/face';
  static const recognizePlate = '/api/v1/gate/recognize/plate';
}

abstract class GateRepository {
  Future<GateRegistrations> fetchRegistrations();
  Future<VehiclePlate> addPlate(String plate);
  Future<void> deletePlate(int id);
  Future<FaceEnrollment> submitFace({
    required String path,
    required String filename,
  });
  Future<void> deleteFace();
}

/// Thin wrapper over the generated dart-dio GateApi on the shared Dio
/// (token + X-LamTo-Occupancy interceptors already installed).
class DioGateRepository implements GateRepository {
  DioGateRepository(Dio dio) : _gate = GateApi(dio, standardSerializers);

  final GateApi _gate;

  @override
  Future<GateRegistrations> fetchRegistrations() async {
    try {
      final response = await _gate.gateRegistrationsRetrieve();
      return response.data!;
    } catch (error) {
      throw Failure.fromObject(error);
    }
  }

  @override
  Future<VehiclePlate> addPlate(String plate) async {
    try {
      final response = await _gate.gatePlatesCreate(
        plateCreateRequest: PlateCreateRequest((b) => b..plate = plate),
      );
      return response.data!;
    } catch (error) {
      throw Failure.fromObject(error);
    }
  }

  @override
  Future<void> deletePlate(int id) async {
    try {
      await _gate.gatePlatesDestroy(id: id);
    } catch (error) {
      throw Failure.fromObject(error);
    }
  }

  @override
  Future<FaceEnrollment> submitFace({
    required String path,
    required String filename,
  }) async {
    try {
      final response = await _gate.gateFaceCreate(
        photo: await MultipartFile.fromFile(path, filename: filename),
      );
      return response.data!;
    } catch (error) {
      throw Failure.fromObject(error);
    }
  }

  @override
  Future<void> deleteFace() async {
    try {
      await _gate.gateFaceDestroy();
    } catch (error) {
      throw Failure.fromObject(error);
    }
  }
}

final gateRepositoryProvider = Provider<GateRepository>(
  (ref) => DioGateRepository(ref.watch(dioProvider)),
);
```

Method names on the generated `GateApi` follow openapi-generator's `operationId` derivation. After Step 1, read `app/packages/lamto_api/lib/src/api/gate_api.dart` and use the names it actually generated; adjust the calls above to match rather than renaming the generated file.

- [ ] **Step 8: Write the screen**

Create `app/lib/features/gate/gate_registration_screen.dart`. Requirements, all testable:

- Lists plates with their status, each row showing the machine status resolved through l10n, and the `review_note` when the status is rejected.
- "Add a vehicle" opens a text field that shows `gatePlateNormalizedHint` with the live `normalizePlateText` result, and disables submit until `isPlausiblePlate` is true.
- Face section shows the current status or an enrol button, captures with `ImagePicker(source: ImageSource.camera)`, and always displays `gateFacePhotoNotice` beneath it.
- All errors render inline through `failureMessage`, not in a `SnackBar` — the existing account screen documents why (`_prefError` in `app/lib/features/account/account_screen.dart`).
- One primary action per section; touch targets at the existing 44/48 minimums.

Add an entry point to `app/lib/features/account/account_screen.dart` that navigates to it via `adaptivePageRoute`.

- [ ] **Step 9: Write the screen test**

Create `app/test/gate_registration_screen_test.dart` with a fake `GateRepository`, asserting: an empty state renders; a rejected plate shows its reason; the normalized hint updates as text is entered; submit is disabled for an implausible plate; `gate_plate_already_registered` renders the Vietnamese copy containing "Chưa có gì được lưu"; the photo-retention notice is present whenever the enrol button is.

- [ ] **Step 10: Run the app suite**

Run: `cd app && flutter analyze && flutter test`
Expected: no analyzer issues; all tests pass, including `l10n_test.dart`.

- [ ] **Step 11: Commit**

```bash
git add app/lib/features/gate app/lib/core/occupancy.dart app/lib/core/failure.dart \
  app/lib/l10n app/lib/features/account/account_screen.dart app/packages/lamto_api \
  app/test/gate_repository_contract_test.dart app/test/gate_plate_text_test.dart \
  app/test/gate_registration_screen_test.dart
git commit -m "feat(app): let residents register vehicles and enrol a face"
```

---

### Task 16: Reader mode

**Files:**
- Create: `app/lib/features/gate/reader/reader_credential_store.dart`, `app/lib/features/gate/reader/plate_ocr.dart`, `app/lib/features/gate/reader/gate_reader_screen.dart`, `app/lib/features/gate/reader/reader_repository.dart`
- Modify: `app/pubspec.yaml`, `app/lib/features/settings/` (entry point), `app/lib/l10n/*.arb`
- Test: `app/test/gate_plate_ocr_test.dart`, `app/test/gate_reader_screen_test.dart`

**Interfaces:**
- Consumes: `GateApiPaths`, `normalizePlateText`, `isPlausiblePlate` (Task 15).
- Produces: `ReaderCredentialStore` (`read()`, `write(String)`, `clear()`), `extractPlate(RecognizedText) -> String?`, `ReaderRepository` with `recognizePlate(String)` and `recognizeFace(path)`, `GateReaderScreen`.

One new dependency: `google_mlkit_text_recognition`. It replaces a server-side plate OCR pipeline entirely, and it is what real ALPR hardware does internally — the phone stage behaves like the camera it stands in for. Capture uses the existing `image_picker` rather than adding the `camera` package; a live preview is a later refinement, not a prerequisite for proving recognition.

- [ ] **Step 1: Add the dependency**

In `app/pubspec.yaml`, under `dependencies`:

```yaml
  google_mlkit_text_recognition: ^0.15.0
```

Run: `cd app && flutter pub get`
Expected: resolved.

- [ ] **Step 2: Write the failing OCR test**

Create `app/test/gate_plate_ocr_test.dart`:

```dart
import 'package:flutter_test/flutter_test.dart';
import 'package:lamto/features/gate/reader/plate_ocr.dart';

void main() {
  test('picks a plausible plate from recognized lines', () {
    expect(bestPlateFromLines(['51F-123.45']), '51F12345');
    expect(bestPlateFromLines(['GARAGE', '51F-123.45', 'EXIT']), '51F12345');
  });

  test('joins the two lines of a motorbike plate within a block', () {
    expect(bestPlateFromLines(['59X1', '999.99'], joinAdjacent: true), '59X199999');
  });

  test('returns null when nothing looks like a plate', () {
    expect(bestPlateFromLines(['WELCOME', 'HOME']), isNull);
    expect(bestPlateFromLines([]), isNull);
  });

  test('prefers a line matching the Vietnamese plate shape', () {
    expect(bestPlateFromLines(['ABCDEFGH', '51F12345']), '51F12345');
  });
}
```

- [ ] **Step 3: Write the OCR helper**

Create `app/lib/features/gate/reader/plate_ocr.dart`:

```dart
import 'package:google_mlkit_text_recognition/google_mlkit_text_recognition.dart';

import '../plate_text.dart';

/// Vietnamese plates: two province digits, one or two letters, four to six
/// digits. Used to rank OCR candidates, not to reject the server's answer.
final _plateShape = RegExp(r'^[0-9]{2}[A-Z]{1,2}[0-9]{4,6}$');

/// Best plate candidate from a set of recognized text lines.
///
/// Motorbike plates print on two lines, so adjacent lines within one block are
/// also tried joined.
String? bestPlateFromLines(List<String> lines, {bool joinAdjacent = false}) {
  final candidates = <String>[];
  for (var i = 0; i < lines.length; i++) {
    candidates.add(normalizePlateText(lines[i]));
    if (joinAdjacent && i + 1 < lines.length) {
      candidates.add(normalizePlateText('${lines[i]}${lines[i + 1]}'));
    }
  }
  final plausible = candidates.where(isPlausiblePlate).toList();
  if (plausible.isEmpty) return null;
  final shaped = plausible.where(_plateShape.hasMatch);
  return shaped.isNotEmpty ? shaped.first : null;
}

/// Read a plate from a captured image file.
Future<String?> extractPlate(String imagePath) async {
  final recognizer = TextRecognizer(script: TextRecognitionScript.latin);
  try {
    final recognized = await recognizer.processImage(
      InputImage.fromFilePath(imagePath),
    );
    for (final block in recognized.blocks) {
      final plate = bestPlateFromLines(
        block.lines.map((line) => line.text).toList(),
        joinAdjacent: true,
      );
      if (plate != null) return plate;
    }
    return null;
  } finally {
    await recognizer.close();
  }
}
```

- [ ] **Step 4: Run the OCR test**

Run: `cd app && flutter test test/gate_plate_ocr_test.dart`
Expected: PASS, 4 tests

- [ ] **Step 5: Write the credential store and reader repository**

Create `app/lib/features/gate/reader/reader_credential_store.dart` using `flutter_secure_storage` under key `gate_reader_credential`, with `read()`, `write(String)`, and `clear()`, mirroring `app/lib/core/token_store.dart`.

Create `app/lib/features/gate/reader/reader_repository.dart`: its own `Dio` built from `apiBaseUrl` with the same timeouts, **without** the resident token or occupancy interceptors, sending `Authorization: GateDevice <credential>`. It calls `GateApiPaths.recognizePlate` and `GateApiPaths.recognizeFace` and converts errors with `Failure.fromObject`.

The reader must not reuse the resident Dio: a gate phone holds a device credential, not a resident session, and mixing them would attach a resident's token to gate traffic.

- [ ] **Step 6: Write the reader screen**

Create `app/lib/features/gate/reader/gate_reader_screen.dart`. Requirements:

- Not reachable until a credential is entered; the entry point is a tile in the existing settings area, and the screen shows a credential field when the store is empty.
- Two actions: read a plate, read a face. Both capture with `ImagePicker(source: ImageSource.camera)`.
- Plate flow runs `extractPlate` on-device and posts the string; if it returns null, show "could not read a plate — try again" without calling the server.
- Face flow posts the captured file.
- The result is a large card: name and unit on a match, "Not recognized" otherwise. Both are results, not errors.
- `gate_device_revoked` and `gate_device_expired` render their own distinct copy so a guard sees a credential problem instead of a network problem.
- Direction from the server response is shown so the guard can confirm the reader is configured as they expect.

Add the l10n keys for the reader strings to both `.arb` files and run `flutter gen-l10n`.

- [ ] **Step 7: Write the screen test**

Create `app/test/gate_reader_screen_test.dart` with a fake `ReaderRepository`, asserting: the credential prompt shows when the store is empty; a match renders the name and unit; a non-match renders "Not recognized" and not an error style; `gate_device_revoked` renders the revoked copy and not the generic network copy.

- [ ] **Step 8: Run the app suite**

Run: `cd app && flutter analyze && flutter test`
Expected: no analyzer issues; all tests pass.

- [ ] **Step 9: Commit**

```bash
git add app/lib/features/gate/reader app/pubspec.yaml app/pubspec.lock app/lib/l10n \
  app/lib/features/settings app/test/gate_plate_ocr_test.dart \
  app/test/gate_reader_screen_test.dart
git commit -m "feat(app): add a credentialled gate reader mode with on-device plate OCR"
```

---

### Task 17: End-to-end acceptance

**Files:**
- Create: `tests/e2e/test_gate_recognition.py`

**Interfaces:**
- Consumes: everything above.
- Produces: the acceptance test the pilot report cites.

- [ ] **Step 1: Write the test**

Create `tests/e2e/test_gate_recognition.py`:

```python
"""Gate happy path end to end, including the part that deletes it again.

enrol -> approve -> recognize -> event exists -> clock advances -> purge ->
nothing left. The last two steps are the point: retention is a feature of this
subsystem, not an operational afterthought.
"""

from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.utils import timezone

from lamto.accounts.models import (
    Building,
    ManagementMembership,
    ResidentOccupancy,
    Unit,
    User,
)
from lamto.gate.devices import issue_credential
from lamto.gate.enrollment import submit_face_enrollment, submit_plate
from lamto.gate.models import (
    FaceEnrollment,
    GateDevice,
    GateEvent,
    PendingEnrollmentPhoto,
    ReviewStatus,
)
from lamto.gate.recognition import recognize_face, recognize_plate
from lamto.gate.review import approve_face, approve_plate
from lamto.gate.tests.fakes import face_bytes

pytestmark = pytest.mark.django_db


@pytest.fixture
def world(temp_storage, settings, monkeypatch):
    settings.GATE_FACE_EMBEDDER = "lamto.gate.tests.fakes.FakeEmbedder"
    settings.GATE_EMBEDDING_KEY = "e2e-key"
    settings.GATE_FACE_MATCH_THRESHOLD = 0.38
    monkeypatch.setattr("lamto.gate.enrollment.scan_with_clamav", lambda f: True)

    building = Building.objects.create(name="E2E Gate Building")
    unit = Unit.objects.create(building=building, label="12A")
    resident = User.objects.create(email="r@example.com", display_name="Nguyen A")
    occupancy = ResidentOccupancy.objects.create(user=resident, unit=unit)
    membership = ManagementMembership.objects.create(
        user=User.objects.create(email="m@example.com", display_name="Manager"),
        building=building,
    )
    device = GateDevice.objects.create(
        building=building, label="North gate", direction=GateDevice.Direction.ENTRY
    )
    credential, _ = issue_credential(device, membership)
    return {
        "building": building,
        "occupancy": occupancy,
        "membership": membership,
        "credential": credential,
    }


def test_enrol_approve_recognize_then_retention_removes_everything(world):
    occupancy = world["occupancy"]
    membership = world["membership"]
    credential = world["credential"]

    # Enrol.
    enrollment = submit_face_enrollment(
        occupancy,
        SimpleUploadedFile("f.jpg", face_bytes("nguyen"), content_type="image/jpeg"),
    )
    plate = submit_plate(occupancy, "51F-123.45")
    assert enrollment.status == ReviewStatus.PENDING
    assert PendingEnrollmentPhoto.objects.count() == 1

    # Approve. The review photo goes with the decision.
    approve_face(enrollment, membership)
    approve_plate(plate, membership)
    assert not PendingEnrollmentPhoto.objects.exists()
    assert FaceEnrollment.objects.get().embedding is not None

    # Recognize, both ways.
    face_outcome = recognize_face(credential, face_bytes("nguyen"))
    plate_outcome = recognize_plate(credential, "51F-123.45")
    assert face_outcome.matched is True
    assert face_outcome.display_name == "Nguyen A"
    assert face_outcome.unit_label == "12A"
    assert plate_outcome.matched is True
    assert GateEvent.objects.count() == 2

    # A stranger is logged as unrecognized, not dropped.
    stranger = recognize_face(credential, face_bytes("stranger"))
    assert stranger.matched is False
    assert GateEvent.objects.count() == 3

    # Advance past the window and run the hourly job.
    GateEvent.objects.update(occurred_at=timezone.now() - timedelta(hours=24, minutes=30))
    call_command("purge_gate_data")

    # Nothing survives.
    assert not GateEvent.objects.exists()
    # The enrolment itself is untouched: retention is about events, not people.
    assert FaceEnrollment.objects.get().status == ReviewStatus.APPROVED


def test_an_expired_review_photo_forces_a_resubmission(world):
    occupancy = world["occupancy"]
    enrollment = submit_face_enrollment(
        occupancy,
        SimpleUploadedFile("f.jpg", face_bytes("nguyen"), content_type="image/jpeg"),
    )
    PendingEnrollmentPhoto.objects.update(
        expires_at=timezone.now() - timedelta(minutes=1)
    )
    call_command("purge_gate_data")

    enrollment.refresh_from_db()
    assert enrollment.status == ReviewStatus.EXPIRED
    assert enrollment.embedding is None
    assert not PendingEnrollmentPhoto.objects.exists()
```

- [ ] **Step 2: Run the acceptance test**

Run: `set -a && . .env && set +a && .venv/bin/python -m pytest tests/e2e/test_gate_recognition.py -v`
Expected: PASS, 2 passed

- [ ] **Step 3: Run everything**

Run: `set -a && . .env && set +a && .venv/bin/python -m pytest tests src/lamto -v`
Expected: PASS across the whole suite, with the `insightface`-marked tests deselected.

Run: `cd app && flutter analyze && flutter test`
Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add tests/e2e/test_gate_recognition.py
git commit -m "test(gate): cover enrol, approve, recognize, and retention end to end"
```

---

## Sequencing Notes

Tasks 1-14 are backend and are independently shippable: at the end of Task 14 the subsystem works, is calibrated, and can be exercised with `curl` or the Django admin. Tasks 15-16 add the two Flutter surfaces and both depend on the regenerated OpenAPI client from Tasks 10-11. Task 17 closes the loop.

**Before the pilot**, Task 14's acceptance criteria must be satisfied and the calibrated values written into the pilot environment. Shipping on `GATE_FACE_MATCH_THRESHOLD=0.38` is a failed acceptance criterion, not a default.

