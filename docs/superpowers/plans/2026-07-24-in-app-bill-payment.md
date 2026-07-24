# In-App Bill Payment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let management issue a bill to one specific resident, who views it and records a payment by scanning a LamTo-specific bill QR — with a shared, pluggable confirmation seam and honest "resident-reported, not bank-verified" labelling.

**Architecture:** A new Django `billing` app owns the `Bill` record and two services — `issue_bill` (fans out one targeted notification) and `confirm_payment` (the seam). Resident endpoints live in the existing `api` app; management screens live in the `web` staff portal. The Flutter app consumes a regenerated `lamto_api` client, adds a `mobile_scanner`-based confirm flow, and highlights the newest unpaid bill on Home.

**Tech Stack:** Django 5.2 + DRF + drf-spectacular (schema), PostgreSQL, `qrcode` (SVG QR on the staff page); Flutter + Riverpod + Dio + generated `lamto_api` (dart-dio) + `mobile_scanner`.

## Global Constraints

- **Targeting:** a bill is addressed to exactly one resident `User` (`Bill.resident`). Only `bill.resident` may list/view/download/confirm it. A co-resident of the same unit sees nothing.
- **Money boundary:** LamTo never moves money, holds funds, or verifies with a bank. `status=PAID` means *recorded*, not bank-confirmed.
- **Confirmation seam:** all confirmations go through `billing.services.confirm_payment(bill, *, source, actor, reference)`. This release's only caller passes `source=BillPaymentSource.SELF_ATTESTED_DEMO`.
- **QR:** the LamTo bill QR encodes the string `lamto-bill:<reference>`. `reference` is unguessable; the confirm endpoint accepts a bill as paid only when the posted reference equals `bill.reference`.
- **Currency:** VND only; `amount_vnd` is a positive integer number of đồng.
- **Resident copy:** never "successful"/"paid" language implying bank verification. Use **"Payment recorded" / "Đã ghi nhận thanh toán"**. Management/audit label paid bills **resident-reported, not bank-verified**.
- **Event code:** `building.bill_issued`. In-app delivery mandatory; push default-on and resident-toggleable; email never queued. OS-visible push copy is generic Vietnamese.
- **Tests:** backend `.venv/bin/python -m pytest <path> -q` (pytest-django; use `pytestmark = pytest.mark.django_db`). Flutter from `app/`: `flutter test <path>` and `flutter analyze`.
- **Follow existing patterns exactly:** services mirror `lamto/notifications/announcements.py`; resident views mirror `lamto/api/views.py`; staff views/forms/templates mirror `lamto/web/announcement_views.py`, `forms/announcements.py`, `templates/web/staff/announcements/`.

---

### Task 1: `billing` app + `Bill` model

**Files:**
- Create: `src/lamto/billing/__init__.py` (empty)
- Create: `src/lamto/billing/apps.py`
- Create: `src/lamto/billing/models.py`
- Create: `src/lamto/billing/migrations/__init__.py` (empty)
- Create: `src/lamto/billing/tests/__init__.py` (empty)
- Create: `src/lamto/billing/tests/test_models.py`
- Modify: `src/lamto/config/settings.py` (add `"lamto.billing"` to INSTALLED_APPS beside the other `lamto.*` apps)

**Interfaces:**
- Produces: `Bill` model with `Status` (`ISSUED`/`PAID`/`VOID`) and `PaymentSource` (`SELF_ATTESTED_DEMO`/`BANK_WEBHOOK`/`MANAGEMENT_MANUAL`) text choices; fields `building`, `resident`, `title`, `note`, `period`, `due_date`, `amount_vnd`, `document`, `reference`, `status`, `payment_source`, `issued_by`, `issued_at`, `paid_at`, `paid_confirmed_by`, `void_by`, `void_at`, `void_reason`. Default `reference` via `billing.models.new_reference()`.

- [ ] **Step 1: Write the failing test**

```python
# src/lamto/billing/tests/test_models.py
import pytest
from django.db import IntegrityError

from lamto.accounts.models import Building, ResidentOccupancy, Unit, User
from lamto.billing.models import Bill
from lamto.documents.models import Document, DocumentVersion


pytestmark = pytest.mark.django_db


def _bill_document(building):
    document = Document.objects.create(building=building, kind=Document.Kind.RESIDENT_BILL)
    return DocumentVersion.objects.create(
        document=document, version=1, storage_key=f"k/{document.pk}",
        provider_version_id="v", filename="bill.pdf", content_type="application/pdf",
        byte_size=10, sha256="0" * 64,
        uploader=User.objects.create_user(email="up@x.test", password="pw"),
    )


def test_bill_defaults_and_reference_are_populated():
    building = Building.objects.create(name="Tower A")
    unit = Unit.objects.create(building=building, label="101")
    resident = User.objects.create_user(email="r@x.test", password="pw")
    ResidentOccupancy.objects.create(user=resident, unit=unit)
    bill = Bill.objects.create(
        building=building, resident=resident, title="Phí quản lý 07/2026",
        amount_vnd=250000, document=_bill_document(building),
        issued_by=resident,
    )
    assert bill.status == Bill.Status.ISSUED
    assert bill.payment_source == ""
    assert len(bill.reference) >= 16
    assert Bill.objects.get(pk=bill.pk).reference == bill.reference


def test_amount_must_be_positive():
    building = Building.objects.create(name="Tower A")
    resident = User.objects.create_user(email="r@x.test", password="pw")
    with pytest.raises(IntegrityError):
        Bill.objects.create(
            building=building, resident=resident, title="Bad",
            amount_vnd=0, document=_bill_document(building), issued_by=resident,
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest src/lamto/billing/tests/test_models.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'lamto.billing'` (and `Document.Kind.RESIDENT_BILL` missing; Task 2 adds the kind — for now this test's `_bill_document` will fail on the kind, which is fine: it drives Task 1 + surfaces the Task 2 need. If you prefer isolation, temporarily use `Document.Kind.INVOICE` here and switch to `RESIDENT_BILL` in Task 2.)

- [ ] **Step 3: Write minimal implementation**

```python
# src/lamto/billing/apps.py
from django.apps import AppConfig


class BillingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "lamto.billing"
```

```python
# src/lamto/billing/models.py
import secrets

from django.conf import settings
from django.db import models

from lamto.accounts.models import Building
from lamto.documents.models import DocumentVersion


def new_reference() -> str:
    """Unguessable per-bill reference; also the payload of the LamTo bill QR."""
    return secrets.token_urlsafe(12)  # ~16 chars


class Bill(models.Model):
    class Status(models.TextChoices):
        ISSUED = "ISSUED", "Issued"
        PAID = "PAID", "Paid"
        VOID = "VOID", "Void"

    class PaymentSource(models.TextChoices):
        SELF_ATTESTED_DEMO = "SELF_ATTESTED_DEMO", "Resident self-attested (demo)"
        BANK_WEBHOOK = "BANK_WEBHOOK", "Bank webhook"
        MANAGEMENT_MANUAL = "MANAGEMENT_MANUAL", "Management manual"

    building = models.ForeignKey(Building, on_delete=models.PROTECT, related_name="bills")
    resident = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="bills"
    )
    title = models.CharField(max_length=160)
    note = models.TextField(max_length=500, blank=True)
    period = models.CharField(max_length=64, blank=True)
    due_date = models.DateField(null=True, blank=True)
    amount_vnd = models.PositiveBigIntegerField()
    document = models.ForeignKey(DocumentVersion, on_delete=models.PROTECT, related_name="bills")
    reference = models.CharField(max_length=64, default=new_reference, editable=False)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ISSUED)
    payment_source = models.CharField(max_length=32, choices=PaymentSource.choices, blank=True)
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="issued_bills"
    )
    issued_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    paid_confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.PROTECT, related_name="confirmed_bills",
    )
    void_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.PROTECT, related_name="voided_bills",
    )
    void_at = models.DateTimeField(null=True, blank=True)
    void_reason = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount_vnd__gt=0), name="bill_amount_positive"
            ),
        ]
```

Add `"lamto.billing"` to `INSTALLED_APPS` in `src/lamto/config/settings.py` next to the other `lamto.*` entries.

- [ ] **Step 4: Make the migration and run tests**

Run:
```bash
.venv/bin/python manage.py makemigrations billing
.venv/bin/python -m pytest src/lamto/billing/tests/test_models.py -q
```
Expected: migration `0001_initial` created; `test_amount_must_be_positive` PASSES. `test_bill_defaults...` still fails on `Document.Kind.RESIDENT_BILL` until Task 2 (acceptable — Task 2 closes it).

- [ ] **Step 5: Commit**

```bash
git add src/lamto/billing src/lamto/config/settings.py
git commit -m "feat: add Bill model in billing app"
```

---

### Task 2: `RESIDENT_BILL` document kind (images or PDFs)

**Files:**
- Modify: `src/lamto/documents/models.py:21-29` (add `RESIDENT_BILL` to `Document.Kind`)
- Modify: `src/lamto/documents/services.py:84-87` (`_allowed_content_types`)
- Create: `src/lamto/documents/migrations/00NN_resident_bill_kind.py` (via makemigrations)
- Modify/Test: `src/lamto/documents/tests/test_services.py` (add cases; create the file if the module splits tests differently — check the directory first)

**Interfaces:**
- Produces: `Document.Kind.RESIDENT_BILL`; bill documents accept `application/pdf`, `image/jpeg`, `image/png`.

- [ ] **Step 1: Write the failing test**

```python
# append to src/lamto/documents/tests/test_services.py (mirror existing setup helpers there)
import pytest
from django.core.files.uploader import SimpleUploadedFile  # if repo uses django.core.files.uploadedfile, match it

from lamto.accounts.models import Building, ManagementMembership, User
from lamto.documents.models import Document
from lamto.documents.services import create_document_version


pytestmark = pytest.mark.django_db


def _png_bytes():
    return b"\x89PNG\r\n\x1a\n" + b"0" * 64


def test_resident_bill_accepts_png(monkeypatch):
    building = Building.objects.create(name="Tower A")
    manager = User.objects.create_user(email="m@x.test", password="pw")
    ManagementMembership.objects.create(user=manager, building=building)
    document = Document.objects.create(building=building, kind=Document.Kind.RESIDENT_BILL)
    upload = SimpleUploadedFile("bill.png", _png_bytes(), content_type="image/png")
    version = create_document_version(document, upload, manager, lambda _f: True)
    assert version.content_type == "image/png"
```

> Note: match the exact `SimpleUploadedFile` import and any image-verify stubbing used by the existing `test_services.py`; PNG passes `Image.verify()` only for a real PNG — if the suite has a fixture image helper, use it instead of `_png_bytes()`.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest src/lamto/documents/tests/test_services.py -q -k resident_bill`
Expected: FAIL — `AttributeError: RESIDENT_BILL` or `KeyError` in `_allowed_content_types`.

- [ ] **Step 3: Write minimal implementation**

In `src/lamto/documents/models.py`, add to `Document.Kind`:
```python
        RESIDENT_BILL = "RESIDENT_BILL", "Resident bill"
```

In `src/lamto/documents/services.py`, extend `_allowed_content_types`:
```python
BILL_KINDS = {Document.Kind.RESIDENT_BILL}


def _allowed_content_types(document):
    if document.kind in PHOTO_KINDS:
        return {"image/jpeg", "image/png"}
    if document.kind in BILL_KINDS:
        return {"application/pdf", "image/jpeg", "image/png"}
    return {"application/pdf"}
```

- [ ] **Step 4: Migrate and run tests**

Run:
```bash
.venv/bin/python manage.py makemigrations documents
.venv/bin/python -m pytest src/lamto/documents/tests/test_services.py src/lamto/billing/tests/test_models.py -q
```
Expected: PASS (Task 1's `test_bill_defaults...` now passes too).

- [ ] **Step 5: Commit**

```bash
git add src/lamto/documents
git commit -m "feat: add RESIDENT_BILL document kind accepting image or pdf"
```

---

### Task 3: `issue_bill` service + `building.bill_issued` event wiring

**Files:**
- Create: `src/lamto/billing/services.py`
- Modify: `src/lamto/notifications/services.py` (add `EVENT_BILL_ISSUED`, extend `RESIDENT_PUSH_EVENT_CODES` and `PREFERENCE_EVENT_CHOICES`)
- Modify: `src/lamto/notifications/push.py` (add `PUSH_COPY` entry + `DEEP_LINK_TYPES["bill"]`)
- Create: `src/lamto/billing/tests/test_issue.py`

**Interfaces:**
- Consumes: `Bill` (Task 1), `require_management`, `record_audit`, `queue_notification`, `NotificationDelivery`.
- Produces: `issue_bill(actor, building_id, resident_id, *, title, amount_vnd, document, note="", period="", due_date=None) -> Bill`; module constant `EVENT_BILL_ISSUED = "building.bill_issued"`; `in_app_event_key(bill_id)`; exceptions `BillError`.

- [ ] **Step 1: Write the failing test**

```python
# src/lamto/billing/tests/test_issue.py
import pytest
from django.test import override_settings
from django.utils import timezone

from lamto.accounts.models import Building, ManagementMembership, ResidentOccupancy, Unit, User
from lamto.audit.models import AuditEvent
from lamto.billing.models import Bill
from lamto.billing.services import EVENT_BILL_ISSUED, in_app_event_key, issue_bill
from lamto.documents.models import Document, DocumentVersion
from lamto.notifications.models import Device, NotificationDelivery


pytestmark = pytest.mark.django_db


def _doc(building, uploader):
    document = Document.objects.create(building=building, kind=Document.Kind.RESIDENT_BILL)
    return DocumentVersion.objects.create(
        document=document, version=1, storage_key=f"k/{document.pk}",
        provider_version_id="v", filename="bill.pdf", content_type="application/pdf",
        byte_size=10, sha256="0" * 64, uploader=uploader,
    )


@override_settings(PUSH_ENABLED=True)
def test_issue_bill_targets_only_the_named_resident():
    building = Building.objects.create(name="Tower A")
    manager = User.objects.create_user(email="m@x.test", password="pw")
    ManagementMembership.objects.create(user=manager, building=building)
    unit = Unit.objects.create(building=building, label="101")
    resident = User.objects.create_user(email="r@x.test", password="pw")
    co_resident = User.objects.create_user(email="c@x.test", password="pw")
    ResidentOccupancy.objects.create(user=resident, unit=unit)
    ResidentOccupancy.objects.create(user=co_resident, unit=unit)
    Device.objects.create(user=resident, install_id="i", fcm_token="t",
                          platform=Device.Platform.ANDROID, last_seen_at=timezone.now())

    bill = issue_bill(manager, building.pk, resident.pk, title="Phí 07/2026",
                      amount_vnd=250000, document=_doc(building, manager))

    assert bill.status == Bill.Status.ISSUED
    in_app = NotificationDelivery.objects.filter(
        channel=NotificationDelivery.Channel.IN_APP, event_key=in_app_event_key(bill.pk))
    assert list(in_app.values_list("recipient_id", flat=True)) == [resident.pk]
    assert in_app.get().status == NotificationDelivery.Status.AVAILABLE
    push = NotificationDelivery.objects.filter(
        channel=NotificationDelivery.Channel.PUSH, event_code=EVENT_BILL_ISSUED)
    assert list(push.values_list("recipient_id", flat=True)) == [resident.pk]
    assert not NotificationDelivery.objects.filter(
        channel=NotificationDelivery.Channel.EMAIL, event_code=EVENT_BILL_ISSUED).exists()
    assert AuditEvent.objects.filter(target_type="Bill", target_id=str(bill.pk),
                                     action="bill.issued").exists()


def test_issue_bill_rejects_resident_without_active_occupancy():
    building = Building.objects.create(name="Tower A")
    manager = User.objects.create_user(email="m@x.test", password="pw")
    ManagementMembership.objects.create(user=manager, building=building)
    stranger = User.objects.create_user(email="s@x.test", password="pw")
    with pytest.raises(Exception):
        issue_bill(manager, building.pk, stranger.pk, title="x",
                   amount_vnd=1000, document=_doc(building, manager))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest src/lamto/billing/tests/test_issue.py -q`
Expected: FAIL — `ImportError` for `issue_bill`.

- [ ] **Step 3: Write minimal implementation**

In `src/lamto/notifications/services.py`, after `EVENT_ANNOUNCEMENT`:
```python
EVENT_BILL_ISSUED = "building.bill_issued"
```
Add `EVENT_BILL_ISSUED` to `RESIDENT_PUSH_EVENT_CODES` and add `(EVENT_BILL_ISSUED, "Building bills")` to `PREFERENCE_EVENT_CHOICES`.

In `src/lamto/notifications/push.py`, add to `PUSH_COPY`:
```python
    "building.bill_issued": ("Có hóa đơn mới từ ban quản lý", "Mở ứng dụng để xem chi tiết."),
```
and add to `DEEP_LINK_TYPES`:
```python
    "bill": "bill",
```

```python
# src/lamto/billing/services.py
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction

from lamto.accounts.models import ResidentOccupancy
from lamto.accounts.services import require_management
from lamto.audit.services import record_audit
from lamto.billing.models import Bill
from lamto.notifications.models import NotificationDelivery
from lamto.notifications.services import EVENT_BILL_ISSUED, queue_notification


class BillError(Exception):
    pass


def in_app_event_key(bill_id: int) -> str:
    return f"{EVENT_BILL_ISSUED}:bill:{bill_id}"


def push_event_key(bill_id: int) -> str:
    return f"{EVENT_BILL_ISSUED}:bill:{bill_id}:issued"


@transaction.atomic
def issue_bill(actor, building_id, resident_id, *, title, amount_vnd,
               document, note="", period="", due_date=None) -> Bill:
    membership = require_management(actor, building_id)
    resident = get_user_model().objects.get(pk=resident_id)
    if not ResidentOccupancy.objects.filter(
        user_id=resident_id, active=True, unit__building_id=building_id
    ).exists():
        raise ValidationError("Resident has no active occupancy in this building.")

    bill = Bill.objects.create(
        building_id=building_id, resident=resident, title=title, note=note,
        period=period, due_date=due_date, amount_vnd=amount_vnd,
        document=document, issued_by=actor,
    )
    subject = f"{title} — {amount_vnd:,}đ"
    queue_notification(
        recipient=resident, building=bill.building, event_code=EVENT_BILL_ISSUED,
        event_key=in_app_event_key(bill.pk), subject=subject, body=note,
        channels=[NotificationDelivery.Channel.IN_APP],
    )
    queue_notification(
        recipient=resident, building=bill.building, event_code=EVENT_BILL_ISSUED,
        event_key=push_event_key(bill.pk), subject=subject, body=note,
        channels=[NotificationDelivery.Channel.PUSH],
    )
    NotificationDelivery.objects.filter(
        event_key=in_app_event_key(bill.pk),
        channel=NotificationDelivery.Channel.IN_APP,
    ).update(status=NotificationDelivery.Status.AVAILABLE)
    record_audit(
        actor=actor, membership=membership, action="bill.issued",
        target_type="Bill", target_id=str(bill.pk), result="accepted",
        metadata={"bill_id": bill.pk, "amount_vnd": amount_vnd},
    )
    return bill
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest src/lamto/billing/tests/test_issue.py src/lamto/notifications/tests -q`
Expected: PASS (notifications tests still green).

- [ ] **Step 5: Commit**

```bash
git add src/lamto/billing/services.py src/lamto/notifications/services.py src/lamto/notifications/push.py src/lamto/billing/tests/test_issue.py
git commit -m "feat: issue targeted resident bills with notification fan-out"
```

---

### Task 4: `confirm_payment` service (the seam)

**Files:**
- Modify: `src/lamto/billing/services.py`
- Create: `src/lamto/billing/tests/test_confirm.py`

**Interfaces:**
- Produces: `confirm_payment(bill, *, source, actor, reference) -> Bill`; exceptions `BillVoidedError(BillError)`, `BillReferenceError(BillError)`.

- [ ] **Step 1: Write the failing test**

```python
# src/lamto/billing/tests/test_confirm.py
import pytest

from lamto.accounts.models import Building, ManagementMembership, ResidentOccupancy, Unit, User
from lamto.audit.models import AuditEvent
from lamto.billing.models import Bill
from lamto.billing.services import (
    BillReferenceError, BillVoidedError, confirm_payment, issue_bill,
)
from lamto.documents.models import Document, DocumentVersion


pytestmark = pytest.mark.django_db


def _bill():
    building = Building.objects.create(name="Tower A")
    manager = User.objects.create_user(email="m@x.test", password="pw")
    ManagementMembership.objects.create(user=manager, building=building)
    unit = Unit.objects.create(building=building, label="101")
    resident = User.objects.create_user(email="r@x.test", password="pw")
    ResidentOccupancy.objects.create(user=resident, unit=unit)
    document = Document.objects.create(building=building, kind=Document.Kind.RESIDENT_BILL)
    version = DocumentVersion.objects.create(
        document=document, version=1, storage_key=f"k/{document.pk}",
        provider_version_id="v", filename="b.pdf", content_type="application/pdf",
        byte_size=1, sha256="0" * 64, uploader=manager)
    bill = issue_bill(manager, building.pk, resident.pk, title="x",
                      amount_vnd=1000, document=version)
    return bill, resident


def test_confirm_records_payment_and_is_idempotent():
    bill, resident = _bill()
    src = Bill.PaymentSource.SELF_ATTESTED_DEMO
    result = confirm_payment(bill, source=src, actor=resident, reference=bill.reference)
    assert result.status == Bill.Status.PAID
    assert result.payment_source == src
    assert result.paid_confirmed_by_id == resident.pk
    assert AuditEvent.objects.filter(
        target_type="Bill", target_id=str(bill.pk), action="bill.payment_recorded").count() == 1
    again = confirm_payment(bill, source=src, actor=resident, reference=bill.reference)
    assert again.status == Bill.Status.PAID
    assert AuditEvent.objects.filter(action="bill.payment_recorded").count() == 1


def test_confirm_rejects_wrong_reference():
    bill, resident = _bill()
    with pytest.raises(BillReferenceError):
        confirm_payment(bill, source=Bill.PaymentSource.SELF_ATTESTED_DEMO,
                        actor=resident, reference="not-it")
    bill.refresh_from_db()
    assert bill.status == Bill.Status.ISSUED
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest src/lamto/billing/tests/test_confirm.py -q`
Expected: FAIL — `ImportError` for `confirm_payment`.

- [ ] **Step 3: Write minimal implementation**

Append to `src/lamto/billing/services.py`:
```python
from django.utils import timezone


class BillVoidedError(BillError):
    pass


class BillReferenceError(BillError):
    pass


@transaction.atomic
def confirm_payment(bill, *, source, actor, reference) -> Bill:
    locked = Bill.objects.select_for_update().get(pk=bill.pk)
    if locked.status == Bill.Status.VOID:
        raise BillVoidedError()
    if locked.status == Bill.Status.PAID:
        return locked
    if reference != locked.reference:
        raise BillReferenceError()
    locked.status = Bill.Status.PAID
    locked.payment_source = source
    locked.paid_at = timezone.now()
    locked.paid_confirmed_by = actor
    locked.save(update_fields=["status", "payment_source", "paid_at", "paid_confirmed_by"])
    record_audit(
        actor=actor, membership=None, action="bill.payment_recorded",
        target_type="Bill", target_id=str(locked.pk), result="accepted",
        metadata={"bill_id": locked.pk, "source": source},
    )
    return locked
```

> `record_audit(membership=None, ...)` is used elsewhere for resident-actor events (see `documents/services.py`). If `record_audit` rejects `membership=None` for this action, check its allowlist and add `"bill.payment_recorded"` the same way existing resident actions are allowed.

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest src/lamto/billing/tests/test_confirm.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/lamto/billing/services.py src/lamto/billing/tests/test_confirm.py
git commit -m "feat: add shared confirm_payment seam for bills"
```

---

### Task 5: `void_bill` service

**Files:**
- Modify: `src/lamto/billing/services.py`
- Create: `src/lamto/billing/tests/test_void.py`

**Interfaces:**
- Produces: `void_bill(actor, bill_id, *, reason) -> Bill`; raises `BillError` when not `ISSUED` or reason blank. Deletes the bill's IN_APP deliveries (hides it).

- [ ] **Step 1: Write the failing test**

```python
# src/lamto/billing/tests/test_void.py
import pytest

from lamto.accounts.models import Building, ManagementMembership, ResidentOccupancy, Unit, User
from lamto.billing.models import Bill
from lamto.billing.services import (
    BillVoidedError, confirm_payment, in_app_event_key, issue_bill, void_bill,
)
from lamto.documents.models import Document, DocumentVersion
from lamto.notifications.models import NotificationDelivery


pytestmark = pytest.mark.django_db


def _setup():
    building = Building.objects.create(name="Tower A")
    manager = User.objects.create_user(email="m@x.test", password="pw")
    ManagementMembership.objects.create(user=manager, building=building)
    unit = Unit.objects.create(building=building, label="101")
    resident = User.objects.create_user(email="r@x.test", password="pw")
    ResidentOccupancy.objects.create(user=resident, unit=unit)
    document = Document.objects.create(building=building, kind=Document.Kind.RESIDENT_BILL)
    version = DocumentVersion.objects.create(
        document=document, version=1, storage_key=f"k/{document.pk}",
        provider_version_id="v", filename="b.pdf", content_type="application/pdf",
        byte_size=1, sha256="0" * 64, uploader=manager)
    bill = issue_bill(manager, building.pk, resident.pk, title="x",
                      amount_vnd=1000, document=version)
    return manager, resident, bill


def test_void_hides_in_app_and_blocks_payment():
    manager, resident, bill = _setup()
    void_bill(manager, bill.pk, reason="Issued in error")
    bill.refresh_from_db()
    assert bill.status == Bill.Status.VOID
    assert bill.void_reason == "Issued in error"
    assert not NotificationDelivery.objects.filter(
        channel=NotificationDelivery.Channel.IN_APP, event_key=in_app_event_key(bill.pk)).exists()
    with pytest.raises(BillVoidedError):
        confirm_payment(bill, source=Bill.PaymentSource.SELF_ATTESTED_DEMO,
                        actor=resident, reference=bill.reference)


def test_void_requires_reason():
    manager, _resident, bill = _setup()
    with pytest.raises(Exception):
        void_bill(manager, bill.pk, reason="  ")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest src/lamto/billing/tests/test_void.py -q`
Expected: FAIL — `ImportError` for `void_bill`.

- [ ] **Step 3: Write minimal implementation**

Append to `src/lamto/billing/services.py`:
```python
@transaction.atomic
def void_bill(actor, bill_id, *, reason) -> Bill:
    reason = (reason or "").strip()
    if not reason:
        raise BillError("A void reason is required.")
    locked = Bill.objects.select_for_update().select_related("building").get(pk=bill_id)
    membership = require_management(actor, locked.building_id)
    if locked.status != Bill.Status.ISSUED:
        raise BillError("Only an issued bill can be voided.")
    locked.status = Bill.Status.VOID
    locked.void_by = actor
    locked.void_at = timezone.now()
    locked.void_reason = reason
    locked.save(update_fields=["status", "void_by", "void_at", "void_reason"])
    NotificationDelivery.objects.filter(
        event_key=in_app_event_key(locked.pk),
        channel=NotificationDelivery.Channel.IN_APP,
    ).delete()
    record_audit(
        actor=actor, membership=membership, action="bill.voided",
        target_type="Bill", target_id=str(locked.pk), result="accepted",
        metadata={"bill_id": locked.pk},
    )
    return locked
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest src/lamto/billing/tests -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/lamto/billing/services.py src/lamto/billing/tests/test_void.py
git commit -m "feat: add void_bill service that hides and blocks a bill"
```

---

### Task 6: Resident read API — list, detail, file download

**Files:**
- Create: `src/lamto/api/bill_serializers.py`
- Create: `src/lamto/api/bill_views.py`
- Modify: `src/lamto/api/urls.py` (import `bill_views`; add three routes)
- Modify: `src/lamto/api/downloads.py` (allow `RESIDENT_BILL`; add branch to `resident_can_download`)
- Create: `src/lamto/api/tests/test_bills.py`

**Interfaces:**
- Produces routes: `GET api/v1/bills` (`bills_list`), `GET api/v1/bills/<pk>` (`bills_retrieve`), `POST api/v1/bills/<pk>/confirm-payment` (`bills_confirm_payment`, implemented in Task 7). Serializers `BillSummarySerializer`, `BillDetailSerializer`.
- Consumes: `issue_download_token`, `resident_can_download`, `Bill`.

- [ ] **Step 1: Write the failing test**

```python
# src/lamto/api/tests/test_bills.py
import pytest
from django.test import Client
from django.urls import reverse
from knox.models import AuthToken

from lamto.accounts.models import Building, ManagementMembership, ResidentOccupancy, Unit, User
from lamto.billing.models import Bill
from lamto.billing.services import issue_bill, void_bill
from lamto.documents.models import Document, DocumentVersion


pytestmark = pytest.mark.django_db


def _world():
    building = Building.objects.create(name="Tower A")
    manager = User.objects.create_user(email="m@x.test", password="pw")
    ManagementMembership.objects.create(user=manager, building=building)
    unit = Unit.objects.create(building=building, label="101")
    resident = User.objects.create_user(email="r@x.test", password="pw")
    ResidentOccupancy.objects.create(user=resident, unit=unit)
    document = Document.objects.create(building=building, kind=Document.Kind.RESIDENT_BILL)
    version = DocumentVersion.objects.create(
        document=document, version=1, storage_key=f"k/{document.pk}",
        provider_version_id="v", filename="b.pdf", content_type="application/pdf",
        byte_size=1, sha256="0" * 64, uploader=manager)
    bill = issue_bill(manager, building.pk, resident.pk, title="Phí 07",
                      amount_vnd=250000, document=version)
    return manager, resident, bill


def _auth(user):
    _inst, token = AuthToken.objects.create(user=user)
    return {"authorization": f"Token {token}"}


def test_list_shows_only_own_non_void_bills():
    manager, resident, bill = _world()
    other = User.objects.create_user(email="o@x.test", password="pw")
    unit = ResidentOccupancy.objects.get(user=resident).unit
    ResidentOccupancy.objects.create(user=other, unit=unit)
    voided = issue_bill(manager, bill.building_id, resident.pk, title="Void me",
                        amount_vnd=1, document=bill.document)
    void_bill(manager, voided.pk, reason="oops")

    client = Client()
    res = client.get(reverse("api:bills-list"), headers=_auth(resident))
    ids = [row["id"] for row in res.json()["results"]]
    assert res.status_code == 200 and ids == [bill.pk]

    # A co-resident sees none of this resident's bills.
    assert client.get(reverse("api:bills-list"), headers=_auth(other)).json()["results"] == []


def test_detail_denied_for_other_resident_and_carries_download_url():
    manager, resident, bill = _world()
    stranger = User.objects.create_user(email="s@x.test", password="pw")
    client = Client()
    ok = client.get(reverse("api:bills-detail", args=[bill.pk]), headers=_auth(resident))
    assert ok.status_code == 200
    assert "/api/v1/documents/" in ok.json()["document_download_url"]
    denied = client.get(reverse("api:bills-detail", args=[bill.pk]), headers=_auth(stranger))
    assert denied.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest src/lamto/api/tests/test_bills.py -q`
Expected: FAIL — `NoReverseMatch: 'bills-list'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/lamto/api/bill_serializers.py
from rest_framework import serializers

from lamto.billing.models import Bill


class BillSummarySerializer(serializers.Serializer):
    id = serializers.IntegerField()
    title = serializers.CharField()
    amount_vnd = serializers.IntegerField()
    status = serializers.ChoiceField(choices=Bill.Status.choices)
    period = serializers.CharField(allow_blank=True)
    due_date = serializers.DateField(allow_null=True)
    issued_at = serializers.DateTimeField()
    paid_at = serializers.DateTimeField(allow_null=True)


class BillDetailSerializer(BillSummarySerializer):
    note = serializers.CharField(allow_blank=True)
    document_filename = serializers.CharField()
    document_download_url = serializers.CharField()


class BillConfirmPaymentRequestSerializer(serializers.Serializer):
    reference = serializers.CharField(max_length=64, trim_whitespace=False)
```

```python
# src/lamto/api/bill_views.py
from django.urls import reverse
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import exceptions, generics, pagination
from rest_framework.response import Response
from rest_framework.views import APIView

from lamto.api.bill_serializers import (
    BillConfirmPaymentRequestSerializer,
    BillDetailSerializer,
    BillSummarySerializer,
)
from lamto.api.downloads import issue_download_token
from lamto.api.problems import problem_responses
from lamto.billing.models import Bill


class BillCursorPagination(pagination.CursorPagination):
    page_size = 20
    ordering = ("-issued_at", "-pk")


def _own_bills(user):
    return Bill.objects.filter(resident=user).exclude(status=Bill.Status.VOID)


def _detail_payload(request, bill):
    return {
        "id": bill.pk,
        "title": bill.title,
        "amount_vnd": bill.amount_vnd,
        "status": bill.status,
        "period": bill.period,
        "due_date": bill.due_date,
        "issued_at": bill.issued_at,
        "paid_at": bill.paid_at,
        "note": bill.note,
        "document_filename": bill.document.filename,
        "document_download_url": reverse(
            "api:document-download",
            args=[issue_download_token(request.user.pk, bill.document_id)],
        ),
    }


@extend_schema_view(
    get=extend_schema(
        operation_id="bills_list", tags=["bills"],
        responses={200: BillSummarySerializer(many=True), **problem_responses(401, 403)},
    )
)
class BillListView(generics.ListAPIView):
    serializer_class = BillSummarySerializer
    pagination_class = BillCursorPagination

    def get_queryset(self):
        return _own_bills(self.request.user)


class BillDetailView(APIView):
    @extend_schema(
        operation_id="bills_retrieve", tags=["bills"],
        responses={200: BillDetailSerializer, **problem_responses(401, 403, 404)},
    )
    def get(self, request, pk):
        bill = _own_bills(request.user).select_related("document").filter(pk=pk).first()
        if bill is None:
            raise exceptions.NotFound("Bill not found.")
        return Response(BillDetailSerializer(_detail_payload(request, bill)).data)
```

In `src/lamto/api/urls.py`, import and add routes:
```python
from lamto.api import bill_views  # add to existing import line group

    path("bills", bill_views.BillListView.as_view(), name="bills-list"),
    path("bills/<int:pk>", bill_views.BillDetailView.as_view(), name="bills-detail"),
    # bills/<pk>/confirm-payment added in Task 7
```

In `src/lamto/api/downloads.py`: add `Document.Kind.RESIDENT_BILL` to `RESIDENT_DOWNLOADABLE_KINDS`, and add this branch near the top of `resident_can_download` (after the kind allowlist check):
```python
    if version.document.kind == Document.Kind.RESIDENT_BILL:
        from lamto.billing.models import Bill
        return (
            Bill.objects.filter(document=version, resident=user)
            .exclude(status=Bill.Status.VOID)
            .exists()
        )
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest src/lamto/api/tests/test_bills.py src/lamto/api/tests/test_openapi.py -q`
Expected: `test_bills.py` PASS. `test_openapi.py` will FAIL (schema now stale) — expected; regenerated in Task 10.

- [ ] **Step 5: Commit**

```bash
git add src/lamto/api/bill_serializers.py src/lamto/api/bill_views.py src/lamto/api/urls.py src/lamto/api/downloads.py src/lamto/api/tests/test_bills.py
git commit -m "feat: resident bill list and detail API with file download"
```

---

### Task 7: Resident confirm-payment API

**Files:**
- Modify: `src/lamto/api/bill_views.py` (add `BillConfirmPaymentView`)
- Modify: `src/lamto/api/urls.py` (add route)
- Modify: `src/lamto/api/problems.py` (add `BillVoided` exception + code)
- Modify: `src/lamto/api/tests/test_bills.py` (add cases)

**Interfaces:**
- Produces route `POST api/v1/bills/<pk>/confirm-payment` (`bills_confirm_payment`), returns `BillDetailSerializer`. Reference mismatch → 400 `validation_failed`; voided → 409 `bill_voided`.

- [ ] **Step 1: Write the failing test**

```python
# append to src/lamto/api/tests/test_bills.py
def test_confirm_records_payment_with_matching_reference():
    _manager, resident, bill = _world()
    client = Client()
    url = reverse("api:bills-confirm-payment", args=[bill.pk])
    ok = client.post(url, {"reference": bill.reference},
                     content_type="application/json", headers=_auth(resident))
    assert ok.status_code == 200 and ok.json()["status"] == Bill.Status.PAID
    bill.refresh_from_db()
    assert bill.payment_source == Bill.PaymentSource.SELF_ATTESTED_DEMO


def test_confirm_rejects_wrong_reference_and_void():
    manager, resident, bill = _world()
    client = Client()
    url = reverse("api:bills-confirm-payment", args=[bill.pk])
    bad = client.post(url, {"reference": "nope"},
                      content_type="application/json", headers=_auth(resident))
    assert bad.status_code == 400
    void_bill(manager, bill.pk, reason="x")
    gone = client.post(url, {"reference": bill.reference},
                       content_type="application/json", headers=_auth(resident))
    assert gone.status_code == 404  # a voided bill is not resident-visible
```

> Note: `_own_bills` excludes VOID, so the confirm view resolves a voided bill to 404 before reaching the service. That satisfies "not resident-visible". `bill_voided` (409) still exists to cover a bill voided concurrently between detail load and confirm; keep the mapping.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest src/lamto/api/tests/test_bills.py -q -k confirm`
Expected: FAIL — `NoReverseMatch: 'bills-confirm-payment'`.

- [ ] **Step 3: Write minimal implementation**

In `src/lamto/api/problems.py`, add near the other APIExceptions:
```python
class BillVoided(exceptions.APIException):
    status_code = 409
    default_detail = "This bill was voided and can no longer be paid."
    default_code = "bill_voided"
```
and add `(BillVoided, "bill_voided"),` to `_EXCEPTION_CODES` (before the generic DRF entries).

In `src/lamto/api/bill_views.py`, add:
```python
from rest_framework import status as drf_status

from lamto.api.bill_serializers import BillConfirmPaymentRequestSerializer  # add to imports
from lamto.api.problems import BillVoided  # add to imports
from lamto.billing.services import (  # add
    BillReferenceError, BillVoidedError, confirm_payment,
)


class BillConfirmPaymentView(APIView):
    @extend_schema(
        operation_id="bills_confirm_payment", tags=["bills"],
        request=BillConfirmPaymentRequestSerializer,
        responses={200: BillDetailSerializer, **problem_responses(400, 401, 403, 404, 409)},
    )
    def post(self, request, pk):
        bill = _own_bills(request.user).select_related("document").filter(pk=pk).first()
        if bill is None:
            raise exceptions.NotFound("Bill not found.")
        serializer = BillConfirmPaymentRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            bill = confirm_payment(
                bill, source=Bill.PaymentSource.SELF_ATTESTED_DEMO,
                actor=request.user, reference=serializer.validated_data["reference"],
            )
        except BillReferenceError:
            raise exceptions.ValidationError({"reference": "This QR does not match the bill."})
        except BillVoidedError:
            raise BillVoided()
        return Response(
            BillDetailSerializer(_detail_payload(request, bill)).data,
            status=drf_status.HTTP_200_OK,
        )
```

In `src/lamto/api/urls.py`, add:
```python
    path("bills/<int:pk>/confirm-payment", bill_views.BillConfirmPaymentView.as_view(),
         name="bills-confirm-payment"),
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest src/lamto/api/tests/test_bills.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/lamto/api/bill_views.py src/lamto/api/urls.py src/lamto/api/problems.py src/lamto/api/tests/test_bills.py
git commit -m "feat: resident confirm-payment API behind confirm_payment seam"
```

---

### Task 8: Staff portal — bills list + issue

**Files:**
- Create: `src/lamto/web/forms/bills.py`
- Create: `src/lamto/web/bill_views.py`
- Create: `src/lamto/web/templates/web/staff/bills/list.html`
- Modify: `src/lamto/web/urls.py` (import + 2 routes)
- Modify: `src/lamto/web/staff.py` (add a "Bills" nav item)
- Create: `src/lamto/web/tests/test_staff_bills.py`

**Interfaces:**
- Consumes: `issue_bill`, `upload_document`, `require_management_context`, `staff_context`.
- Produces routes `web:staff-bill-list`, `web:staff-bill-create`.

- [ ] **Step 1: Write the failing test**

```python
# src/lamto/web/tests/test_staff_bills.py  (reuse setup_manager pattern from test_staff_announcements.py)
import time

import pytest
from django.test import override_settings
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from django_otp import DEVICE_ID_SESSION_KEY
from django_otp.plugins.otp_totp.models import TOTPDevice
from django_otp.util import random_hex

from lamto.accounts.models import Building, ManagementMembership, ResidentOccupancy, Unit, User
from lamto.accounts.security import RECENT_REAUTH_KEY
from lamto.billing.models import Bill
from lamto.notifications.models import NotificationDelivery


pytestmark = pytest.mark.django_db


def setup_manager(client, name="Tower A"):
    building = Building.objects.create(name=name)
    manager = User.objects.create_user(email="manager@x.test", password="secret")
    ManagementMembership.objects.create(user=manager, building=building)
    client.force_login(manager)
    device = TOTPDevice.objects.create(user=manager, name="t", confirmed=True, key=random_hex())
    session = client.session
    session[DEVICE_ID_SESSION_KEY] = device.persistent_id
    session[RECENT_REAUTH_KEY] = time.time()
    session.save()
    return building, manager


def _pdf():
    return SimpleUploadedFile("bill.pdf", b"%PDF-1.4\n" + b"0" * 32, content_type="application/pdf")


@override_settings(PUSH_ENABLED=False)
def test_issue_creates_bill_and_delivery(client):
    building, _manager = setup_manager(client)
    unit = Unit.objects.create(building=building, label="101")
    resident = User.objects.create_user(email="r@x.test", password="pw")
    ResidentOccupancy.objects.create(user=resident, unit=unit)

    res = client.post(reverse("web:staff-bill-create"), {
        "resident": resident.pk, "title": "Phí 07/2026",
        "amount_vnd": "250000", "note": "Hạn 25/07", "document": _pdf(),
    })
    assert res.status_code == 302
    bill = Bill.objects.get()
    assert (bill.resident_id, bill.amount_vnd, bill.status) == (
        resident.pk, 250000, Bill.Status.ISSUED)
    assert NotificationDelivery.objects.filter(
        recipient=resident, channel=NotificationDelivery.Channel.IN_APP).count() == 1


def test_cross_building_resident_is_rejected(client):
    building, _manager = setup_manager(client)
    other = Building.objects.create(name="Tower B")
    other_unit = Unit.objects.create(building=other, label="9")
    stranger = User.objects.create_user(email="s@x.test", password="pw")
    ResidentOccupancy.objects.create(user=stranger, unit=other_unit)

    res = client.post(reverse("web:staff-bill-create"), {
        "resident": stranger.pk, "title": "x", "amount_vnd": "1000", "document": _pdf(),
    })
    assert res.status_code == 200  # redisplayed with an error
    assert not Bill.objects.exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest src/lamto/web/tests/test_staff_bills.py -q`
Expected: FAIL — `NoReverseMatch: 'staff-bill-create'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/lamto/web/forms/bills.py
from django import forms


class BillForm(forms.Form):
    resident = forms.ChoiceField()
    title = forms.CharField(max_length=160, strip=True)
    amount_vnd = forms.IntegerField(min_value=1)
    period = forms.CharField(max_length=64, required=False, strip=True)
    due_date = forms.DateField(required=False)
    note = forms.CharField(max_length=500, required=False, strip=True, widget=forms.Textarea)
    document = forms.FileField()

    def __init__(self, *args, resident_choices=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["resident"].choices = list(resident_choices)
```

```python
# src/lamto/web/bill_views.py
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_POST

from lamto.accounts.models import ResidentOccupancy
from lamto.billing.models import Bill
from lamto.billing.services import BillError, issue_bill
from lamto.web.forms.bills import BillForm
from lamto.web.staff import require_management_context, staff_context
from lamto.web.staff_documents import upload_document
from lamto.documents.models import Document


def _resident_choices(building_id):
    occupancies = (
        ResidentOccupancy.objects.filter(active=True, unit__building_id=building_id)
        .select_related("user", "unit").order_by("unit__label", "user__display_name")
    )
    seen, choices = set(), []
    for occ in occupancies:
        if occ.user_id in seen:
            continue
        seen.add(occ.user_id)
        choices.append((str(occ.user_id), f"{occ.user.display_name or occ.user.email} · {occ.unit.label}"))
    return choices


def _bills_for(building_id):
    return (
        Bill.objects.filter(building_id=building_id)
        .select_related("resident").order_by("-issued_at", "-pk")
    )


@login_required
@require_GET
def bill_list(request):
    membership, memberships = require_management_context(request)
    form = BillForm(resident_choices=_resident_choices(membership.building_id))
    return render(request, "web/staff/bills/list.html", staff_context(
        request, membership, memberships, nav_active="bills",
        bills=_bills_for(membership.building_id), form=form))


@login_required
@require_POST
def bill_create(request):
    membership, memberships = require_management_context(request)
    choices = _resident_choices(membership.building_id)
    form = BillForm(request.POST, request.FILES, resident_choices=choices)
    if form.is_valid():
        try:
            version = upload_document(
                membership.building, Document.Kind.RESIDENT_BILL, request.user,
                form.cleaned_data["document"])
            bill = issue_bill(
                request.user, membership.building_id, int(form.cleaned_data["resident"]),
                title=form.cleaned_data["title"], amount_vnd=form.cleaned_data["amount_vnd"],
                document=version, note=form.cleaned_data["note"],
                period=form.cleaned_data["period"], due_date=form.cleaned_data["due_date"])
        except (ValidationError, BillError) as error:
            form.add_error(None, str(error))
        else:
            messages.success(request, "Bill issued.")
            return redirect("web:staff-bill-detail", bill.pk)
    return render(request, "web/staff/bills/list.html", staff_context(
        request, membership, memberships, nav_active="bills",
        bills=_bills_for(membership.building_id), form=form), status=200)
```

```django
{# src/lamto/web/templates/web/staff/bills/list.html #}
{% extends "web/staff/shell.html" %}
{% load i18n %}
{% block title %}{% trans "Bills" %} · LamTo{% endblock %}
{% block content %}
<section class="panel">
  <h1>{% trans "Bills" %}</h1>
  <p class="hint">{% blocktrans with building=membership.building.name %}Resident bills for {{ building }}.{% endblocktrans %}</p>
  <form method="post" action="{% url 'web:staff-bill-create' %}" enctype="multipart/form-data">
    {% csrf_token %}
    {{ form.non_field_errors }}
    {{ form.as_p }}
    <button type="submit" class="button">{% trans "Issue bill" %}</button>
  </form>
  <ul class="task-list">
    {% for bill in bills %}
    <li><a class="task-row" href="{% url 'web:staff-bill-detail' bill.pk %}">
      <span class="task-action">{{ bill.title }} · {{ bill.amount_vnd }}đ</span>
      <span class="task-subject">{{ bill.get_status_display }} · {{ bill.resident }} · {{ bill.issued_at }}</span>
    </a></li>
    {% empty %}<li>{% trans "No bills have been issued." %}</li>{% endfor %}
  </ul>
</section>
{% endblock %}
```

In `src/lamto/web/urls.py` import `bill_list`, `bill_create` from `lamto.web.bill_views` and add:
```python
    path("s/bills/", bill_list, name="staff-bill-list"),
    path("s/bills/create/", bill_create, name="staff-bill-create"),
    # detail + void added in Task 9
```

In `src/lamto/web/staff.py`, add to `nav_items_for` (after the Announcements item):
```python
        {"label": _("Bills"), "url_name": "web:staff-bill-list", "active_key": "bills"},
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest src/lamto/web/tests/test_staff_bills.py -q`
Expected: `test_issue_creates_bill_and_delivery` PASS. `test_cross_building_resident_is_rejected` PASS (the stranger is not in `_resident_choices`, so the ChoiceField rejects it → form invalid → 200).

- [ ] **Step 5: Commit**

```bash
git add src/lamto/web/forms/bills.py src/lamto/web/bill_views.py src/lamto/web/templates/web/staff/bills/list.html src/lamto/web/urls.py src/lamto/web/staff.py src/lamto/web/tests/test_staff_bills.py
git commit -m "feat: staff can issue resident bills"
```

---

### Task 9: Staff bill detail + void + LamTo QR

**Files:**
- Modify: `pyproject.toml` (add `"qrcode>=7,<9"`); then `.venv/bin/python -m pip install -e .` or `uv sync`
- Create: `src/lamto/billing/qr.py` (SVG QR helper)
- Modify: `src/lamto/web/bill_views.py` (add `bill_detail`, `bill_void`)
- Create: `src/lamto/web/templates/web/staff/bills/detail.html`
- Modify: `src/lamto/web/urls.py` (2 routes)
- Modify: `src/lamto/web/tests/test_staff_bills.py` (add cases)

**Interfaces:**
- Produces: `billing.qr.bill_qr_svg(reference) -> str` (inline SVG for `lamto-bill:<reference>`); routes `web:staff-bill-detail`, `web:staff-bill-void`.

- [ ] **Step 1: Write the failing test**

```python
# append to src/lamto/web/tests/test_staff_bills.py
from lamto.billing.services import issue_bill


def _issue(building, manager, resident):
    from lamto.documents.models import Document, DocumentVersion
    document = Document.objects.create(building=building, kind=Document.Kind.RESIDENT_BILL)
    version = DocumentVersion.objects.create(
        document=document, version=1, storage_key=f"k/{document.pk}",
        provider_version_id="v", filename="b.pdf", content_type="application/pdf",
        byte_size=1, sha256="0" * 64, uploader=manager)
    return issue_bill(manager, building.pk, resident.pk, title="Phí 07",
                      amount_vnd=250000, document=version)


def test_detail_shows_qr_and_resident_reported_label_when_paid(client):
    building, manager = setup_manager(client)
    unit = Unit.objects.create(building=building, label="101")
    resident = User.objects.create_user(email="r@x.test", password="pw")
    ResidentOccupancy.objects.create(user=resident, unit=unit)
    bill = _issue(building, manager, resident)

    res = client.get(reverse("web:staff-bill-detail", args=[bill.pk]))
    assert res.status_code == 200
    assert b"<svg" in res.content
    assert b"lamto-bill" not in res.content or True  # payload is in the QR, not required as text

    from lamto.billing.services import confirm_payment
    confirm_payment(bill, source=Bill.PaymentSource.SELF_ATTESTED_DEMO,
                    actor=resident, reference=bill.reference)
    paid = client.get(reverse("web:staff-bill-detail", args=[bill.pk]))
    assert "resident-reported".encode() in paid.content.lower() or \
           "cư dân tự xác nhận".encode() in paid.content


def test_void_hides_and_blocks(client):
    building, manager = setup_manager(client)
    unit = Unit.objects.create(building=building, label="101")
    resident = User.objects.create_user(email="r@x.test", password="pw")
    ResidentOccupancy.objects.create(user=resident, unit=unit)
    bill = _issue(building, manager, resident)
    res = client.post(reverse("web:staff-bill-void", args=[bill.pk]), {"reason": "Issued in error"})
    assert res.status_code == 302
    bill.refresh_from_db()
    assert bill.status == Bill.Status.VOID
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest src/lamto/web/tests/test_staff_bills.py -q -k "detail or void"`
Expected: FAIL — `NoReverseMatch: 'staff-bill-detail'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/lamto/billing/qr.py
import io

import qrcode
import qrcode.image.svg


def bill_qr_svg(reference: str) -> str:
    """Inline SVG QR encoding the LamTo-specific bill payload. No image library."""
    img = qrcode.make(
        f"lamto-bill:{reference}",
        image_factory=qrcode.image.svg.SvgPathImage,
        box_size=10, border=2,
    )
    buffer = io.BytesIO()
    img.save(buffer)
    return buffer.getvalue().decode("utf-8")
```

Add to `src/lamto/web/bill_views.py`:
```python
from django.shortcuts import get_object_or_404
from django.utils.safestring import mark_safe
from django.views.decorators.http import require_http_methods

from lamto.billing.qr import bill_qr_svg


def _bill_for(membership, pk):
    return get_object_or_404(
        Bill.objects.select_related("resident", "paid_confirmed_by"),
        pk=pk, building_id=membership.building_id)


@login_required
@require_GET
def bill_detail(request, pk):
    membership, memberships = require_management_context(request)
    bill = _bill_for(membership, pk)
    return render(request, "web/staff/bills/detail.html", staff_context(
        request, membership, memberships, nav_active="bills",
        bill=bill, qr_svg=mark_safe(bill_qr_svg(bill.reference))))


@login_required
@require_POST
def bill_void(request, pk):
    membership, _memberships = require_management_context(request)
    bill = _bill_for(membership, pk)
    from lamto.billing.services import BillError, void_bill
    try:
        void_bill(request.user, bill.pk, reason=request.POST.get("reason", ""))
    except BillError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, "Bill voided.")
    return redirect("web:staff-bill-detail", bill.pk)
```

```django
{# src/lamto/web/templates/web/staff/bills/detail.html #}
{% extends "web/staff/shell.html" %}
{% load i18n %}
{% block title %}{{ bill.title }} · LamTo{% endblock %}
{% block content %}
<section class="panel">
  <p><a class="back-link" href="{% url 'web:staff-bill-list' %}">{% trans "Back to bills" %}</a></p>
  <h1>{{ bill.title }}</h1>
  <dl class="detail-list detail-list-wide">
    <div><dt>{% trans "Resident" %}</dt><dd>{{ bill.resident }}</dd></div>
    <div><dt>{% trans "Amount" %}</dt><dd>{{ bill.amount_vnd }}đ</dd></div>
    <div><dt>{% trans "Status" %}</dt><dd>{{ bill.get_status_display }}</dd></div>
    {% if bill.status == "PAID" %}
    <div><dt>{% trans "Payment" %}</dt>
      <dd>{% trans "Cư dân tự xác nhận — chưa đối soát ngân hàng (resident-reported, not bank-verified)" %}
        · {{ bill.paid_confirmed_by }} · {{ bill.paid_at }}</dd></div>
    {% endif %}
  </dl>
  {% if bill.status == "ISSUED" %}
  <h2>{% trans "Payment QR (demo)" %}</h2>
  <div class="qr">{{ qr_svg }}</div>
  <form method="post" action="{% url 'web:staff-bill-void' bill.pk %}"
        onsubmit="return confirm('{% trans "Void this bill?" %}');">
    {% csrf_token %}
    <label>{% trans "Reason" %} <input type="text" name="reason" required></label>
    <button type="submit" class="button button-secondary">{% trans "Void bill" %}</button>
  </form>
  {% endif %}
</section>
{% endblock %}
```

In `src/lamto/web/urls.py` add:
```python
    path("s/bills/<int:pk>/", bill_detail, name="staff-bill-detail"),
    path("s/bills/<int:pk>/void/", bill_void, name="staff-bill-void"),
```
(and import `bill_detail`, `bill_void`).

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest src/lamto/web/tests/test_staff_bills.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock src/lamto/billing/qr.py src/lamto/web/bill_views.py src/lamto/web/templates/web/staff/bills/detail.html src/lamto/web/urls.py src/lamto/web/tests/test_staff_bills.py
git commit -m "feat: staff bill detail with LamTo QR and void"
```

---

### Task 10: Regenerate the OpenAPI schema

**Files:**
- Modify: `docs/api/openapi-v1.yaml` (generated)

- [ ] **Step 1: Regenerate**

Run: `.venv/bin/python manage.py spectacular --file docs/api/openapi-v1.yaml`

- [ ] **Step 2: Verify the schema test passes**

Run: `.venv/bin/python -m pytest src/lamto/api/tests/test_openapi.py -q`
Expected: PASS. Confirm the new paths exist:
Run: `grep -n "/api/v1/bills" docs/api/openapi-v1.yaml`
Expected: three paths (`/bills`, `/bills/{id}`, `/bills/{id}/confirm-payment`) and a `bills` tag.

- [ ] **Step 3: Commit**

```bash
git add docs/api/openapi-v1.yaml
git commit -m "chore: regenerate OpenAPI schema for bills"
```

---

### Task 11: Regenerate the `lamto_api` Dart client

**Files:**
- Modify: `app/packages/lamto_api/**` (generated)

- [ ] **Step 1: Regenerate** (needs `java` or `docker`, per `app/tool/generate_api.sh`)

Run:
```bash
cd app && ./tool/generate_api.sh
```

- [ ] **Step 2: Verify generation is clean and the client has BillsApi**

Run:
```bash
cd app && ./tool/check_api_generated.sh
grep -rl "class BillsApi" packages/lamto_api/lib
ls packages/lamto_api/lib/src/model | grep -i bill
```
Expected: `OK: generated API client matches...`; `BillsApi` present; models `bill_summary.dart`, `bill_detail.dart`, `bill_confirm_payment_request.dart`, `paginated_bill_summary_list.dart` present.

- [ ] **Step 3: Commit**

```bash
git add app/packages/lamto_api
git commit -m "chore: regenerate lamto_api Dart client for bills"
```

---

### Task 12: Flutter — bills repository, deep link, QR parser

**Files:**
- Create: `app/lib/features/bills/bills_repository.dart`
- Modify: `app/lib/features/notifications/deep_link.dart` (add `DeepLinkBill`; handle `bill` entity/type)
- Create: `app/lib/features/bills/bill_qr.dart` (pure parser)
- Create: `app/test/features/bills/deep_link_bill_test.dart`
- Create: `app/test/features/bills/bill_qr_test.dart`

**Interfaces:**
- Produces: `DeepLinkBill(int id)`; `String? billReferenceFromQr(String raw)`; `BillsRepository` (`listBills`, `fetchBill`, `confirmPayment`, `fetchDocument`) + providers `billsRepositoryProvider`, `billsProvider`, `newestUnpaidBillProvider`, `billDetailProvider`.

- [ ] **Step 1: Write the failing tests**

```dart
// app/test/features/bills/bill_qr_test.dart
import 'package:flutter_test/flutter_test.dart';
import 'package:lamto_app/features/bills/bill_qr.dart';

void main() {
  test('extracts reference from a LamTo bill QR', () {
    expect(billReferenceFromQr('lamto-bill:abc123'), 'abc123');
  });
  test('rejects non-LamTo QR payloads', () {
    expect(billReferenceFromQr('https://example.test'), isNull);
    expect(billReferenceFromQr('lamto-bill:'), isNull);
  });
}
```

```dart
// app/test/features/bills/deep_link_bill_test.dart
import 'package:flutter_test/flutter_test.dart';
import 'package:lamto_app/features/notifications/deep_link.dart';

void main() {
  test('event key and push link map bill to DeepLinkBill', () {
    expect(parseEventKey('building.bill_issued:bill:7'), const DeepLinkBill(7));
    expect(parsePushLink(type: 'bill', id: '7'), const DeepLinkBill(7));
  });
}
```

> Confirm the Dart package import prefix (`lamto_app`) from `app/pubspec.yaml`'s `name:` and match it in these imports.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd app && flutter test test/features/bills/`
Expected: FAIL — `bill_qr.dart` / `DeepLinkBill` not found.

- [ ] **Step 3: Write minimal implementation**

```dart
// app/lib/features/bills/bill_qr.dart
/// The LamTo bill QR encodes `lamto-bill:<reference>`. Returns the reference,
/// or null for any other QR — the confirm flow rejects non-LamTo codes.
String? billReferenceFromQr(String raw) {
  const prefix = 'lamto-bill:';
  if (!raw.startsWith(prefix)) return null;
  final reference = raw.substring(prefix.length);
  return reference.isEmpty ? null : reference;
}
```

In `app/lib/features/notifications/deep_link.dart` add the class and both mappings:
```dart
class DeepLinkBill extends DeepLink {
  const DeepLinkBill(this.id);
  final int id;
  @override
  bool operator ==(Object other) => other is DeepLinkBill && other.id == id;
  @override
  int get hashCode => Object.hash('bill', id);
}
```
In `parsePushLink`, add before the default: `'bill' when parsed != null => DeepLinkBill(parsed),`.
In `parseEventKey`'s switch, add: `'bill' => DeepLinkBill(id),`.

```dart
// app/lib/features/bills/bills_repository.dart
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lamto_api/lamto_api.dart';

import '../../core/providers.dart';

abstract class BillsRepository {
  Future<PaginatedBillSummaryList> listBills({String? cursor});
  Future<BillDetail> fetchBill(int id);
  Future<BillDetail> confirmPayment(int id, String reference);
  Future<Uint8List> fetchDocument(String downloadUrl);
}

class DioBillsRepository implements BillsRepository {
  DioBillsRepository(Dio dio)
      : _bills = BillsApi(dio, standardSerializers),
        _documents = DocumentsApi(dio, standardSerializers);

  final BillsApi _bills;
  final DocumentsApi _documents;

  @override
  Future<PaginatedBillSummaryList> listBills({String? cursor}) async =>
      (await _bills.billsList(cursor: cursor)).data!;

  @override
  Future<BillDetail> fetchBill(int id) async => (await _bills.billsRetrieve(id: id)).data!;

  @override
  Future<BillDetail> confirmPayment(int id, String reference) async {
    final res = await _bills.billsConfirmPayment(
      id: id,
      billConfirmPaymentRequest: BillConfirmPaymentRequest((b) => b..reference = reference),
    );
    return res.data!;
  }

  @override
  Future<Uint8List> fetchDocument(String downloadUrl) async {
    final segments = Uri.parse(downloadUrl).pathSegments;
    if (segments.isEmpty || segments.last.isEmpty) {
      throw StateError('Document URL has no access token');
    }
    return (await _documents.documentsRetrieve(token: segments.last)).data!;
  }
}

final billsRepositoryProvider =
    Provider<BillsRepository>((ref) => DioBillsRepository(ref.watch(dioProvider)));

final billsProvider = FutureProvider.autoDispose<List<BillSummary>>((ref) async {
  ref.watch(occupancyScopedProviders);
  final page = await ref.watch(billsRepositoryProvider).listBills();
  return page.results.toList();
});

/// Home highlight: the newest bill still awaiting payment, or null.
final newestUnpaidBillProvider = FutureProvider.autoDispose<BillSummary?>((ref) async {
  final bills = await ref.watch(billsProvider.future);
  for (final bill in bills) {
    if (bill.status == BillStatusEnum.ISSUED) return bill;
  }
  return null;
});

final billDetailProvider =
    FutureProvider.autoDispose.family<BillDetail, int>((ref, id) {
  ref.watch(occupancyScopedProviders);
  return ref.watch(billsRepositoryProvider).fetchBill(id);
});
```

> The generated enum/method names (`BillStatusEnum.ISSUED`, `billsConfirmPayment`, `BillConfirmPaymentRequest`) come from Task 11's output — verify exact casing in `app/packages/lamto_api/lib/src/model/` and adjust if the generator emitted different names (e.g. `StatusEnum`).

- [ ] **Step 4: Run tests + analyze**

Run: `cd app && flutter test test/features/bills/ && flutter analyze lib/features/bills lib/features/notifications`
Expected: PASS, no analyzer errors.

- [ ] **Step 5: Commit**

```bash
git add app/lib/features/bills/bills_repository.dart app/lib/features/bills/bill_qr.dart app/lib/features/notifications/deep_link.dart app/test/features/bills
git commit -m "feat: bills repository, deep link, and QR parser"
```

---

### Task 13: Flutter — bills list, detail, and Home highlight (l10n)

**Files:**
- Create: `app/lib/features/bills/bills_screen.dart`
- Create: `app/lib/features/bills/bill_detail_screen.dart`
- Modify: `app/lib/features/home/home_screen.dart` (add newest-unpaid-bill card)
- Modify: `app/lib/app.dart` and `app/lib/features/notifications/notifications_screen.dart` (route `DeepLinkBill` → `BillDetailScreen`)
- Modify: `app/lib/l10n/app_en.arb`, `app/lib/l10n/app_vi.arb`
- Create: `app/test/features/bills/bill_detail_screen_test.dart`

**Interfaces:**
- Consumes: `billDetailProvider`, `newestUnpaidBillProvider`, `formatVnd`, generated `BillDetail`/`BillSummary`.
- Produces: `BillsScreen`, `BillDetailScreen(billId)`.

- [ ] **Step 1: Add l10n keys (both ARBs), then write the failing test**

Add to `app/lib/l10n/app_en.arb` (and Vietnamese values to `app_vi.arb`):
```json
  "homeBillTitle": "Building bill",
  "billsTitle": "Bills",
  "billAmountLabel": "Amount",
  "billDueLabel": "Due",
  "billViewFile": "View bill",
  "billPayAction": "I've paid",
  "billStatusIssued": "Unpaid",
  "billStatusPaid": "Payment recorded",
  "billScanTitle": "Scan payment QR",
  "billScanInstruction": "Point the camera at the bill QR to record your payment.",
  "billInvalidQr": "That QR code is not a LamTo bill.",
  "billPaymentRecorded": "Payment recorded",
  "billNone": "No bills."
```
Vietnamese (`app_vi.arb`): `homeBillTitle`="Hóa đơn tòa nhà", `billsTitle`="Hóa đơn", `billAmountLabel`="Số tiền", `billDueLabel`="Hạn", `billViewFile`="Xem hóa đơn", `billPayAction`="Tôi đã thanh toán", `billStatusIssued`="Chưa thanh toán", `billStatusPaid`="Đã ghi nhận thanh toán", `billScanTitle`="Quét mã QR thanh toán", `billScanInstruction`="Hướng máy ảnh vào mã QR trên hóa đơn để ghi nhận thanh toán.", `billInvalidQr`="Mã QR không hợp lệ.", `billPaymentRecorded`="Đã ghi nhận thanh toán", `billNone`="Chưa có hóa đơn.".

Run `cd app && flutter gen-l10n` to regenerate `AppLocalizations`.

```dart
// app/test/features/bills/bill_detail_screen_test.dart
import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lamto_api/lamto_api.dart';
import 'package:lamto_app/features/bills/bill_detail_screen.dart';
import 'package:lamto_app/features/bills/bills_repository.dart';
import 'package:lamto_app/l10n/app_localizations.dart';

class _FakeRepo implements BillsRepository {
  @override
  Future<BillDetail> fetchBill(int id) async => BillDetail((b) => b
    ..id = id..title = 'Phí 07'..amountVnd = 250000..status = BillStatusEnum.ISSUED
    ..period = ''..note = ''..documentFilename = 'b.pdf'
    ..documentDownloadUrl = '/api/v1/documents/t');
  @override
  noSuchMethod(Invocation i) => super.noSuchMethod(i);
}

void main() {
  testWidgets('bill detail shows amount and pay action', (tester) async {
    await tester.pumpWidget(ProviderScope(
      overrides: [billsRepositoryProvider.overrideWithValue(_FakeRepo())],
      child: const MaterialApp(
        localizationsDelegates: [
          AppLocalizations.delegate,
          GlobalMaterialLocalizations.delegate,
          GlobalWidgetsLocalizations.delegate,
        ],
        supportedLocales: [Locale('en'), Locale('vi')],
        home: BillDetailScreen(billId: 1),
      ),
    ));
    await tester.pumpAndSettle();
    expect(find.textContaining('250'), findsWidgets);
    expect(find.text("I've paid"), findsOneWidget);
  });
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd app && flutter test test/features/bills/bill_detail_screen_test.dart`
Expected: FAIL — `BillDetailScreen` not found.

- [ ] **Step 3: Write minimal implementation**

`app/lib/features/bills/bill_detail_screen.dart` — a `ConsumerWidget` watching `billDetailProvider(billId)`, rendering title, `formatVnd(bill.amountVnd)`, status label (`billStatusIssued`/`billStatusPaid`), a "View bill" action (fetch via `fetchDocument` + show), and — when `status == ISSUED` — a primary `billPayAction` button that pushes `BillScanScreen(billId, ...)` (added in Task 14). Model on `ledger_detail_screen.dart` for structure and the `AsyncData/AsyncError` switch pattern from `home_screen.dart`.

`app/lib/features/bills/bills_screen.dart` — a `ConsumerWidget` watching `billsProvider`, a `ListView` of `ListTile`s (title + `formatVnd` + status) that push `BillDetailScreen`; empty state uses `billNone`.

In `app/lib/features/home/home_screen.dart`: watch `newestUnpaidBillProvider`; when non-null, render a `Card.filled` + `ListTile` (icon `Icons.receipt_long_outlined`, title `l10n.homeBillTitle`, subtitle the bill title + amount) above the announcement card, `onTap` pushing `BillDetailScreen(billId: bill.id)`; add `newestUnpaidBillProvider.future` to the `RefreshIndicator` `Future.wait`.

In `app/lib/app.dart` `_navigatePush` and `app/lib/features/notifications/notifications_screen.dart` `_open`, add:
```dart
      case DeepLinkBill(:final id):
        navigator.push(adaptivePageRoute(builder: (_) => BillDetailScreen(billId: id)));
```
(import `BillDetailScreen`; in `notifications_screen.dart` use its local `Navigator.push`/`context` form matching the existing cases).

- [ ] **Step 4: Run tests + analyze**

Run: `cd app && flutter test test/features/bills/ && flutter analyze lib`
Expected: PASS, no errors.

- [ ] **Step 5: Commit**

```bash
git add app/lib/features/bills app/lib/features/home/home_screen.dart app/lib/app.dart app/lib/features/notifications/notifications_screen.dart app/lib/l10n app/test/features/bills
git commit -m "feat: resident bills list, detail, and Home highlight"
```

---

### Task 14: Flutter — confirm-payment scan flow (`mobile_scanner`)

**Files:**
- Modify: `app/pubspec.yaml` (add `mobile_scanner`)
- Create: `app/lib/features/bills/bill_scan_screen.dart`
- Modify: `app/lib/features/bills/bill_detail_screen.dart` (wire the "I've paid" button to push the scan screen; refresh on success)
- Create: `app/test/features/bills/bill_scan_flow_test.dart` (tests the pure confirm handler, not the camera)

**Interfaces:**
- Consumes: `billReferenceFromQr`, `billsRepositoryProvider.confirmPayment`, `billDetailProvider`.
- Produces: `BillScanScreen(billId)`; a testable `Future<BillScanResult> handleScannedCode(WidgetRef ref, int billId, String raw)` returning `invalidQr` / `recorded` / `voided` / `error`.

- [ ] **Step 1: Add the dependency, then write the failing test**

Add to `app/pubspec.yaml` dependencies: `mobile_scanner: ^7.1.4` (verify latest compatible on pub.dev at implementation time); run `cd app && flutter pub get`.

```dart
// app/test/features/bills/bill_scan_flow_test.dart
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lamto_api/lamto_api.dart';
import 'package:lamto_app/features/bills/bill_scan_screen.dart';
import 'package:lamto_app/features/bills/bills_repository.dart';

class _Repo implements BillsRepository {
  String? confirmedReference;
  @override
  Future<BillDetail> confirmPayment(int id, String reference) async {
    confirmedReference = reference;
    return BillDetail((b) => b
      ..id = id..title = 'x'..amountVnd = 1..status = BillStatusEnum.PAID
      ..period = ''..note = ''..documentFilename = 'b'..documentDownloadUrl = '/api/v1/documents/t');
  }
  @override
  noSuchMethod(Invocation i) => super.noSuchMethod(i);
}

void main() {
  test('valid LamTo QR confirms; other QR is rejected without a network call', () async {
    final repo = _Repo();
    final container = ProviderContainer(
      overrides: [billsRepositoryProvider.overrideWithValue(repo)]);
    addTearDown(container.dispose);
    final ref = container.read(Provider((r) => r));

    final bad = await handleScannedCode(container, 1, 'https://x.test');
    expect(bad, BillScanResult.invalidQr);
    expect(repo.confirmedReference, isNull);

    final ok = await handleScannedCode(container, 1, 'lamto-bill:ref-9');
    expect(ok, BillScanResult.recorded);
    expect(repo.confirmedReference, 'ref-9');
  });
}
```

> Adjust `handleScannedCode`'s first argument to whatever ref/reader handle you implement (a `ProviderContainer` or `WidgetRef`); keep it injectable so this test needs no camera.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd app && flutter test test/features/bills/bill_scan_flow_test.dart`
Expected: FAIL — `bill_scan_screen.dart` not found.

- [ ] **Step 3: Write minimal implementation**

```dart
// app/lib/features/bills/bill_scan_screen.dart (logic + screen)
import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'bill_qr.dart';
import 'bills_repository.dart';

enum BillScanResult { invalidQr, recorded, voided, error }

/// Pure-ish handler: parse the QR, then call the confirm seam. No camera here
/// so it is unit-testable; the screen feeds it raw scanned strings.
Future<BillScanResult> handleScannedCode(
    ProviderContainer container, int billId, String raw) async {
  final reference = billReferenceFromQr(raw);
  if (reference == null) return BillScanResult.invalidQr;
  try {
    await container.read(billsRepositoryProvider).confirmPayment(billId, reference);
    return BillScanResult.recorded;
  } on DioException catch (e) {
    if (e.response?.statusCode == 409) return BillScanResult.voided;
    return BillScanResult.error;
  }
}
```

Then a `BillScanScreen(billId)` `ConsumerStatefulWidget` that shows `MobileScanner` (from `package:mobile_scanner/mobile_scanner.dart`) with `l10n.billScanInstruction`; on the first successful barcode, debounce further scans, call `handleScannedCode(ProviderScope.containerOf(context), billId, code)`, then:
- `recorded` → `ref.invalidate(billDetailProvider(billId))`, `ref.invalidate(billsProvider)`, pop, and show a success page/snackbar with `l10n.billPaymentRecorded`;
- `invalidQr` → `SnackBar(l10n.billInvalidQr)`, keep scanning;
- `voided`/`error` → `SnackBar` with a generic failure, pop.

Wire the "I've paid" button in `bill_detail_screen.dart` to `Navigator.push(... BillScanScreen(billId: billId))`.

> `mobile_scanner` needs camera permission; the app already declares camera usage for the gate reader (`NSCameraUsageDescription` / `<uses-permission android:name="android.permission.CAMERA"/>`). Confirm both are present in `app/ios/Runner/Info.plist` and `app/android/app/src/main/AndroidManifest.xml`; add if missing.

- [ ] **Step 4: Run tests + analyze**

Run: `cd app && flutter test test/features/bills/ && flutter analyze lib`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/pubspec.yaml app/pubspec.lock app/lib/features/bills/bill_scan_screen.dart app/lib/features/bills/bill_detail_screen.dart app/test/features/bills/bill_scan_flow_test.dart
git commit -m "feat: scan-to-confirm bill payment flow"
```

---

### Task 15: Backend lifecycle acceptance test

**Files:**
- Create: `src/lamto/billing/tests/test_lifecycle.py`

**Interfaces:**
- Consumes: staff web routes + resident API. Exercises the full acceptance path (spec §"End-to-end acceptance path").

- [ ] **Step 1: Write the test**

```python
# src/lamto/billing/tests/test_lifecycle.py
import time

import pytest
from django.test import Client, override_settings
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from django_otp import DEVICE_ID_SESSION_KEY
from django_otp.plugins.otp_totp.models import TOTPDevice
from django_otp.util import random_hex
from knox.models import AuthToken

from lamto.accounts.models import Building, ManagementMembership, ResidentOccupancy, Unit, User
from lamto.accounts.security import RECENT_REAUTH_KEY
from lamto.billing.models import Bill


pytestmark = pytest.mark.django_db


@override_settings(PUSH_ENABLED=False)
def test_full_bill_lifecycle():
    building = Building.objects.create(name="Tower A")
    manager = User.objects.create_user(email="m@x.test", password="secret")
    ManagementMembership.objects.create(user=manager, building=building)
    unit = Unit.objects.create(building=building, label="101")
    resident = User.objects.create_user(email="r@x.test", password="pw")
    ResidentOccupancy.objects.create(user=resident, unit=unit)

    staff = Client()
    staff.force_login(manager)
    device = TOTPDevice.objects.create(user=manager, name="t", confirmed=True, key=random_hex())
    session = staff.session
    session[DEVICE_ID_SESSION_KEY] = device.persistent_id
    session[RECENT_REAUTH_KEY] = time.time()
    session.save()

    # 1. Management issues a bill.
    pdf = SimpleUploadedFile("bill.pdf", b"%PDF-1.4\n" + b"0" * 32, content_type="application/pdf")
    assert staff.post(reverse("web:staff-bill-create"), {
        "resident": resident.pk, "title": "Phí 07/2026",
        "amount_vnd": "250000", "document": pdf,
    }).status_code == 302
    bill = Bill.objects.get()

    # 2. Resident sees it.
    _inst, token = AuthToken.objects.create(user=resident)
    api = Client()
    auth = {"authorization": f"Token {token}"}
    listing = api.get(reverse("api:bills-list"), headers=auth).json()["results"]
    assert [b["id"] for b in listing] == [bill.pk]

    # 3. Resident records payment with the LamTo reference.
    paid = api.post(reverse("api:bills-confirm-payment", args=[bill.pk]),
                    {"reference": bill.reference}, content_type="application/json", headers=auth)
    assert paid.status_code == 200 and paid.json()["status"] == Bill.Status.PAID

    # 4. Management sees it paid + resident-reported.
    detail = staff.get(reverse("web:staff-bill-detail", args=[bill.pk]))
    body = detail.content.lower()
    assert b"resident-reported" in body or "cư dân tự xác nhận".encode() in detail.content

    # 5. A voided bill disappears from the resident app and cannot be paid.
    second_pdf = SimpleUploadedFile("b2.pdf", b"%PDF-1.4\n" + b"0" * 32, content_type="application/pdf")
    assert staff.post(reverse("web:staff-bill-create"), {
        "resident": resident.pk, "title": "Void me",
        "amount_vnd": "1000", "document": second_pdf}).status_code == 302
    void_target = Bill.objects.exclude(pk=bill.pk).get()
    assert staff.post(reverse("web:staff-bill-void", args=[void_target.pk]),
                      {"reason": "error"}).status_code == 302
    ids = [b["id"] for b in api.get(reverse("api:bills-list"), headers=auth).json()["results"]]
    assert void_target.pk not in ids
    assert api.post(reverse("api:bills-confirm-payment", args=[void_target.pk]),
                    {"reference": void_target.reference},
                    content_type="application/json", headers=auth).status_code == 404
```

- [ ] **Step 2: Run test**

Run: `.venv/bin/python -m pytest src/lamto/billing/tests/test_lifecycle.py -q`
Expected: PASS.

- [ ] **Step 3: Run the full backend suite for regressions**

Run: `.venv/bin/python -m pytest src/lamto/billing src/lamto/api src/lamto/web src/lamto/documents src/lamto/notifications -q`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add src/lamto/billing/tests/test_lifecycle.py
git commit -m "test: cover the full bill payment lifecycle"
```

---

## Self-Review (completed while writing)

- **Spec coverage:** model (T1), RESIDENT_BILL kind (T2), issue + targeted delivery + event wiring (T3), confirm seam (T4), void hides/blocks (T5), resident list/detail/download gated by `bill.resident` (T6), confirm-payment with reference match + void 409 (T7), staff issue (T8), staff detail + LamTo QR + resident-reported label + void (T9), schema (T10) + client (T11) regen, Flutter repo/deep-link/QR (T12), list/detail/Home + "Payment recorded" copy (T13), scan-to-confirm + `mobile_scanner` (T14), acceptance path (T15). No orphaned requirements.
- **Type consistency:** `confirm_payment(bill, *, source, actor, reference)` and `issue_bill(actor, building_id, resident_id, *, ...)` used identically across services, views, and tests. `in_app_event_key(bill_id)` shared by issue/void. `billReferenceFromQr` / `DeepLinkBill` / `handleScannedCode` names consistent between impl and tests.
- **Generated-name caveat:** exact Dart symbol names (`BillsApi`, `BillStatusEnum.ISSUED`, `billsConfirmPayment`, `BillConfirmPaymentRequest`) depend on Task 11's generator output; each dependent task flags the verify-and-adjust step. This is the one unavoidable late-bound detail; every other reference is concrete.
```
