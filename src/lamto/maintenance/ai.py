"""Live AI triage contract.

POST ``AI_TRIAGE_URL`` with bearer authentication and this JSON body (photos are
never included): ``report_id``, ``text``, ``location_path_snapshot``, and
``candidates`` (each candidate has ``id``, ``text``, and
``location_path_snapshot``). A successful response is exactly:

``{"category": str, "interpreted_location": str, "urgency": "LOW"|"MEDIUM"|"HIGH", "confidence_percent": int, "requires_manual_review": bool, "duplicate_report_ids": [int], "department": str, "deadline_minutes": int, "missing_information": [str], "provider_request_id": str}``.
"""

import json
import time
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .candidates import find_duplicate_candidates
from .models import IssueReport, TriageJob, TriageSuggestion


class TriageValidationError(ValueError):
    pass


RESPONSE_KEYS = {
    "category",
    "interpreted_location",
    "urgency",
    "confidence_percent",
    "requires_manual_review",
    "duplicate_report_ids",
    "department",
    "deadline_minutes",
    "missing_information",
    "provider_request_id",
}
URGENCIES = {"LOW", "MEDIUM", "HIGH"}


def _claim_triage_job(job_id=None):
    with transaction.atomic():
        jobs = TriageJob.objects.select_for_update(skip_locked=True).select_related(
            "report__unit", "report__selected_location"
        ).filter(status=TriageJob.Status.PENDING)
        if job_id is not None:
            jobs = jobs.filter(pk=job_id)
        job = jobs.order_by("pk").first()
        if job is None:
            return None
        job.status = TriageJob.Status.PROCESSING
        job.started_at = timezone.now()
        job.failure_reason = ""
        job.save(update_fields=["status", "started_at", "failure_reason"])
        return job


def _endpoint_url():
    url = settings.AI_TRIAGE_URL
    parsed = urlsplit(url)
    if not parsed.scheme or not parsed.netloc:
        raise TriageValidationError("AI_TRIAGE_URL must be an absolute URL")
    if parsed.scheme != "https" and not (
        parsed.scheme == "http" and settings.AI_TRIAGE_ALLOW_HTTP
    ):
        raise TriageValidationError("AI_TRIAGE_URL must use HTTPS outside local/test mode")
    if not settings.AI_TRIAGE_TOKEN:
        raise TriageValidationError("AI_TRIAGE_TOKEN is required")
    return url


def _valid_string(value):
    return type(value) is str and bool(value)


def _validate_response(payload, candidate_ids):
    if type(payload) is not dict or set(payload) != RESPONSE_KEYS:
        raise TriageValidationError("response keys do not match the contract")
    if not all(_valid_string(payload[key]) for key in ("category", "interpreted_location", "department", "provider_request_id")):
        raise TriageValidationError("response strings must be non-empty strings")
    if payload["urgency"] not in URGENCIES:
        raise TriageValidationError("response urgency is invalid")
    if type(payload["confidence_percent"]) is not int or not 0 <= payload["confidence_percent"] <= 100:
        raise TriageValidationError("response confidence_percent is invalid")
    if type(payload["requires_manual_review"]) is not bool:
        raise TriageValidationError("response requires_manual_review is invalid")
    duplicate_ids = payload["duplicate_report_ids"]
    if type(duplicate_ids) is not list or any(type(report_id) is not int for report_id in duplicate_ids):
        raise TriageValidationError("response duplicate_report_ids is invalid")
    if not set(duplicate_ids).issubset(candidate_ids):
        raise TriageValidationError("response duplicate_report_ids were not supplied as candidates")
    if type(payload["deadline_minutes"]) is not int or payload["deadline_minutes"] <= 0:
        raise TriageValidationError("response deadline_minutes is invalid")
    missing = payload["missing_information"]
    if type(missing) is not list or any(not _valid_string(item) for item in missing):
        raise TriageValidationError("response missing_information is invalid")
    return payload


def _manual(job, reason):
    job.status = TriageJob.Status.NEEDS_MANUAL
    job.failure_reason = reason[:255]
    job.completed_at = timezone.now()
    job.save(update_fields=["status", "failure_reason", "completed_at"])
    IssueReport.objects.filter(
        pk=job.report_id, status=IssueReport.Status.SUBMITTED
    ).update(status=IssueReport.Status.IN_REVIEW)
    return job


def _process_claimed_job(job):
    started = time.perf_counter()
    try:
        candidates = list(find_duplicate_candidates(job.report))
        candidate_ids = {candidate.pk for candidate in candidates}
        body = {
            "report_id": job.report_id,
            "text": job.report.text,
            "location_path_snapshot": job.report.location_path_snapshot,
            "candidates": [
                {
                    "id": candidate.pk,
                    "text": candidate.text,
                    "location_path_snapshot": candidate.location_path_snapshot,
                }
                for candidate in candidates
            ],
        }
        request = Request(
            _endpoint_url(),
            data=json.dumps(body).encode(),
            headers={
                "Authorization": f"Bearer {settings.AI_TRIAGE_TOKEN}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        with urlopen(request, timeout=settings.AI_TRIAGE_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read())
        payload = _validate_response(payload, candidate_ids)
    except (URLError, TimeoutError, OSError) as error:
        return _manual(job, f"transport: {error}")
    except json.JSONDecodeError as error:
        return _manual(job, f"invalid JSON: {error}")
    except (TriageValidationError, ValueError, TypeError) as error:
        return _manual(job, f"schema: {error}")

    if payload["requires_manual_review"]:
        return _manual(job, "provider requested manual review")
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    TriageSuggestion.objects.create(
        job=job,
        category=payload["category"],
        interpreted_location=payload["interpreted_location"],
        urgency=payload["urgency"],
        confidence_percent=payload["confidence_percent"],
        duplicate_report_ids=payload["duplicate_report_ids"],
        department=payload["department"],
        deadline_minutes=payload["deadline_minutes"],
        missing_information=payload["missing_information"],
        raw_response=payload,
        provider_request_id=payload["provider_request_id"],
        validation_metadata={"candidate_ids": sorted(candidate_ids)},
        elapsed_ms=elapsed_ms,
    )
    job.status = TriageJob.Status.SUCCEEDED
    job.completed_at = timezone.now()
    job.save(update_fields=["status", "completed_at"])
    IssueReport.objects.filter(
        pk=job.report_id, status=IssueReport.Status.SUBMITTED
    ).update(status=IssueReport.Status.IN_REVIEW)
    return job


def process_triage_job(job_id) -> TriageJob:
    job = _claim_triage_job(job_id)
    if job is None:
        return TriageJob.objects.get(pk=job_id)
    return _process_claimed_job(job)
