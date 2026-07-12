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
        while location is not None:
            names.append(location.name)
            location = location.parent
        return " / ".join([self.building.name, *reversed(names)])


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
