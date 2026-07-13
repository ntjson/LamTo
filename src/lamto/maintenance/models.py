from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from lamto.accounts.models import Building, Unit
from lamto.documents.models import DocumentVersion


class BuildingLocation(models.Model):
    building = models.ForeignKey(Building, on_delete=models.PROTECT)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT)
    name = models.CharField(max_length=200)
    active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["building", "parent", "name"],
                name="location_sibling_name_once",
                nulls_distinct=False,
            )
        ]

    def clean(self):
        super().clean()
        if self.parent_id and self.parent.building_id != self.building_id:
            raise ValidationError({"parent": "Parent location must belong to the same building."})

    @property
    def path_label(self):
        names = []
        location = self
        seen_locations = set()
        for _ in range(100):
            if location is None:
                return " / ".join([self.building.name, *reversed(names)])
            if location.pk in seen_locations:
                raise ValidationError("Location hierarchy contains a cycle.")
            seen_locations.add(location.pk)
            names.append(location.name)
            location = location.parent
        raise ValidationError("Location hierarchy exceeds the maximum depth.")


class IssueReport(models.Model):
    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        RESOLVED = "RESOLVED", "Resolved"

    reporter = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT)
    text = models.TextField()
    selected_location = models.ForeignKey(BuildingLocation, on_delete=models.PROTECT)
    location_path_snapshot = models.CharField(max_length=1000)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN)
    created_at = models.DateTimeField(auto_now_add=True)


class ReportPhoto(models.Model):
    report = models.ForeignKey(IssueReport, on_delete=models.PROTECT, related_name="photos")
    version = models.ForeignKey(DocumentVersion, on_delete=models.PROTECT)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["report", "version"], name="report_photo_once")
        ]


class TriageJob(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        PROCESSING = "PROCESSING", "Processing"
        SUCCEEDED = "SUCCEEDED", "Succeeded"
        NEEDS_MANUAL = "NEEDS_MANUAL", "Needs manual triage"

    report = models.OneToOneField(IssueReport, on_delete=models.PROTECT, related_name="triage_job")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    failure_reason = models.CharField(max_length=255, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)


class TriageSuggestion(models.Model):
    job = models.OneToOneField(TriageJob, on_delete=models.PROTECT, related_name="suggestion")
    category = models.CharField(max_length=128)
    interpreted_location = models.CharField(max_length=1000)
    urgency = models.CharField(max_length=16)
    confidence_percent = models.PositiveSmallIntegerField()
    duplicate_report_ids = models.JSONField(default=list)
    department = models.CharField(max_length=128)
    deadline_minutes = models.PositiveIntegerField()
    raw_response = models.JSONField()
    provider_request_id = models.CharField(max_length=255)
    validation_metadata = models.JSONField(default=dict)
    elapsed_ms = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)


class TriageDecision(models.Model):
    report = models.OneToOneField(IssueReport, on_delete=models.PROTECT, related_name="triage_decision")
    suggestion = models.ForeignKey(TriageSuggestion, null=True, blank=True, on_delete=models.PROTECT)
    operator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    category = models.CharField(max_length=128)
    urgency = models.CharField(max_length=16)
    location = models.ForeignKey(BuildingLocation, on_delete=models.PROTECT)
    department = models.CharField(max_length=128)
    deadline_minutes = models.PositiveIntegerField()
    differences = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)


class MaintenanceCase(models.Model):
    decision = models.OneToOneField(TriageDecision, on_delete=models.PROTECT, related_name="case")
    building = models.ForeignKey(Building, on_delete=models.PROTECT)
    category = models.CharField(max_length=128)
    urgency = models.CharField(max_length=16)
    location = models.ForeignKey(BuildingLocation, on_delete=models.PROTECT)
    department = models.CharField(max_length=128)
    deadline_at = models.DateTimeField()
    active = models.BooleanField(default=True)
    reports = models.ManyToManyField(IssueReport, through="CaseReport", related_name="maintenance_cases")
    created_at = models.DateTimeField(auto_now_add=True)


class CaseReport(models.Model):
    case = models.ForeignKey(MaintenanceCase, on_delete=models.PROTECT, related_name="case_reports")
    report = models.ForeignKey(IssueReport, on_delete=models.PROTECT, related_name="case_reports")
    grouped_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["case", "report"], name="case_report_once")
        ]


class WorkOrder(models.Model):
    class Status(models.TextChoices):
        ASSIGNED = "ASSIGNED", "Assigned"
        IN_PROGRESS = "IN_PROGRESS", "In progress"
        AWAITING_ACCEPTANCE = "AWAITING_ACCEPTANCE", "Awaiting acceptance"
        ACCEPTED = "ACCEPTED", "Accepted"
        CLOSED = "CLOSED", "Closed"
        CANCELLED = "CANCELLED", "Cancelled"

    class AuthorizationStatus(models.TextChoices):
        NOT_REQUIRED = "NOT_REQUIRED", "Not required"
        PENDING = "PENDING", "Pending"
        AUTHORIZED = "AUTHORIZED", "Authorized"

    case = models.ForeignKey(MaintenanceCase, on_delete=models.PROTECT, related_name="work_orders")
    assignee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    priority = models.CharField(max_length=16)
    deadline_at = models.DateTimeField()
    requires_spending = models.BooleanField()
    authorization_status = models.CharField(
        max_length=16, choices=AuthorizationStatus.choices, default=AuthorizationStatus.NOT_REQUIRED
    )
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.ASSIGNED)
    emergency = models.BooleanField(default=False)
    drill = models.BooleanField(default=False)
    cause = models.TextField(blank=True)
    result = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)


class AppendOnlyModel(models.Model):
    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValueError("Work updates are append-only.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("Work updates are append-only.")


class WorkUpdate(AppendOnlyModel):
    work_order = models.ForeignKey(WorkOrder, on_delete=models.PROTECT, related_name="updates")
    cause = models.TextField()
    result = models.TextField()
    evidence = models.ManyToManyField(DocumentVersion, through="WorkUpdateEvidence", related_name="work_updates")
    created_at = models.DateTimeField(auto_now_add=True)


class WorkUpdateEvidence(AppendOnlyModel):
    class Kind(models.TextChoices):
        BEFORE = "BEFORE", "Before"
        AFTER = "AFTER", "After"

    update = models.ForeignKey(WorkUpdate, on_delete=models.PROTECT, related_name="evidence_links")
    version = models.ForeignKey(DocumentVersion, on_delete=models.PROTECT)
    kind = models.CharField(max_length=8, choices=Kind.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["update", "version"], name="work_update_evidence_once")
        ]
