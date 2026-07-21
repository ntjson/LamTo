"""Management workspace: triage, cases, work orders, proposals."""

import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods

from lamto.accounts.security import require_recent_auth
from lamto.audit.services import record_audit
from lamto.documents.models import Document, DocumentVersion
from lamto.evidence.canonical import payload_hash
from lamto.evidence.models import EvidenceType
from lamto.evidence.signatures import build_evidence_typed_data
from lamto.finance.models import (
    PaymentVerification,
    Proposal,
    PublicationSnapshot,
    PublishedLedgerEntry,
)
from lamto.accounts.models import SignerWallet
from lamto.finance.proposals import (
    ZERO_HASH,
    build_proposal_evidence_payload,
    create_proposal,
    submit_proposal_version,
    spending_proposal_cases,
)
from lamto.maintenance.models import IssueReport, MaintenanceCase, TriageSuggestion
from lamto.maintenance.cases import (
    TERMINAL_STATUSES, complete_case_work, decline_report, publish_progress,
    request_information, start_case_work,
)
from lamto.web.forms.staff import (
    ConfirmTriageForm,
    DeclineReportForm,
    InfoRequestForm,
    CreateProposalForm,
    ProgressUpdateForm,
    PreparePublicationForm,
    SignProposalForm,
)
from lamto.web.staff import require_management_context, staff_context
from lamto.web.views.staff_common import (
    accountability_chain_for,
    prepare_record_list,
    set_sign_confirmation,
    signed_action_failure,
)
from lamto.web.staff_signing import new_event_id, upload_document_pair


@login_required
@require_GET
def case_list(request):
    membership, memberships = require_management_context(request)
    building_id = membership.building_id
    # Active cases filter by urgency (same ?status= chip pattern as work list).
    from lamto.maintenance.ai import URGENCIES

    status = request.GET.get("status") or ""
    urgency_groups = {"routine": ("LOW", "MEDIUM"), "urgent": ("HIGH",)}
    valid_status = status in URGENCIES
    active_group = status if status in urgency_groups else next(
        (group for group, values in urgency_groups.items() if status in values), ""
    )
    from django.db.models import Count

    report_list = prepare_record_list(
        request,
        IssueReport.objects.filter(
            unit__building_id=building_id,
            status__in=[
                IssueReport.Status.SUBMITTED,
                IssueReport.Status.IN_REVIEW,
                IssueReport.Status.NEEDS_INFO,
            ],
        ),
        search_fields=("text", "location_path_snapshot"),
        sorts=(("", "Newest first", ("-created_at",)),),
        page_param="rpage",
    )
    cases_qs = (
        MaintenanceCase.objects.filter(building_id=building_id, active=True)
        .select_related("location")
        .annotate(work_count=Count("updates"))
    )
    if status in urgency_groups:
        cases_qs = cases_qs.filter(urgency__in=urgency_groups[status])
    elif valid_status:
        cases_qs = cases_qs.filter(urgency=status)
    case_list = prepare_record_list(
        request,
        cases_qs,
        search_fields=("category", "department", "location__name"),
        sorts=(
            ("", "Newest first", ("-created_at",)),
            ("deadline", "Deadline soonest", ("deadline_at",)),
        ),
    )
    urgency_labels = {
        "LOW": "Low",
        "MEDIUM": "Medium",
        "HIGH": "High",
    }
    from lamto.web.views.staff_common import deadline_tone

    report_items = [
        {
            "url": f"/s/reports/{r.pk}/",
            "title": r.text,
            "status": r.get_status_display(),
            "deadline": None,
            "deadline_tone": "neutral",
            "next_action": "Confirm triage",
        }
        for r in report_list["page"].object_list
    ]
    case_items = [
        {
            "url": f"/s/cases/{c.pk}/",
            "title": f"Case #{c.pk} · {c.category} · {c.location.name}",
            "status": urgency_labels.get(c.urgency, c.urgency.title()),
            "deadline": c.deadline_at,
            "deadline_tone": deadline_tone(c.deadline_at),
            "next_action": (
                "Create work order" if c.work_count == 0 else "Follow work in progress"
            ),
        }
        for c in case_list["page"].object_list
    ]
    filters = [
        {"label": label, "value": value, "active": value == active_group}
        for value, label in (("routine", "Routine"), ("urgent", "Urgent"))
    ]
    return render(
        request,
        "web/staff/case_detail.html",
        staff_context(
            request,
            membership,
            memberships,
            nav_active="cases",
            list_mode=True,
            report_items=report_items,
            report_list=report_list,
            case_items=case_items,
            case_list=case_list,
            search_label="Search reports and cases",
            filters=filters,
            filters_active=valid_status or status in urgency_groups,
            filter_param="status",
        ),
    )


@login_required
@require_http_methods(["GET", "POST"])
def report_detail(request, pk):
    """Staff triage surface for IssueReport pk only (not MaintenanceCase)."""
    membership, memberships = require_management_context(request)
    building_id = membership.building_id
    report = get_object_or_404(IssueReport, pk=pk, unit__building_id=building_id)

    link = report.case_reports.filter(case__active=True).select_related("case").first()
    if link is not None:
        return redirect("web:case-detail", pk=link.case_id)

    form = ConfirmTriageForm(request.POST or None, building_id=building_id)
    info_form = InfoRequestForm(request.POST or None)
    decline_form = DeclineReportForm(request.POST or None)
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "confirm_triage":
            require_management_context(request)
            if form.is_valid():
                try:
                    case = form.save(report, request.user)
                except (ValidationError, PermissionDenied) as error:
                    if isinstance(error, ValidationError):
                        form.add_error(None, error)
                    else:
                        raise
                else:
                    record_audit(
                        request.user,
                        membership,
                        "workspace.triage.confirm",
                        "MaintenanceCase",
                        str(case.pk),
                        "accepted",
                    )
                    messages.success(
                        request,
                        "Triage confirmed. Create a work order to assign the repair.",
                    )
                    return redirect("web:case-detail", pk=case.pk)
        elif action == "request_info" and info_form.is_valid():
            try:
                request_information(report, request.user, info_form.cleaned_data["message"])
            except ValidationError as error:
                messages.error(request, "; ".join(error.messages))
            else:
                messages.success(request, "Information requested.")
            return redirect("web:staff-report-detail", pk=report.pk)
        elif action == "decline" and decline_form.is_valid():
            try:
                decline_report(report, request.user, decline_form.cleaned_data["reason"])
            except ValidationError as error:
                messages.error(request, "; ".join(error.messages))
            else:
                messages.success(request, "Request declined.")
            return redirect("web:staff-report-detail", pk=report.pk)

    return render(
        request,
        "web/staff/case_detail.html",
        staff_context(
            request,
            membership,
            memberships,
            nav_active="cases",
            report=report,
            case=None,
            form=form,
            work_form=None,
            legacy_items=[],
            list_mode=False,
            mode="report",
            info_form=info_form,
            decline_form=decline_form,
            terminal=report.status in TERMINAL_STATUSES,
            open_info_request=report.info_requests.filter(resolved_at__isnull=True).first(),
            suggestion=TriageSuggestion.objects.filter(job__report=report).first(),
        ),
    )


@login_required
@require_http_methods(["GET", "POST"])
def case_detail(request, pk):
    """MaintenanceCase pk only (not IssueReport)."""
    membership, memberships = require_management_context(request)
    building_id = membership.building_id
    case = get_object_or_404(MaintenanceCase, pk=pk, building_id=building_id)
    report = case.reports.order_by("pk").first()

    work_form = None
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "start_work":
            try:
                start_case_work(case, request.user)
            except (ValidationError, PermissionDenied) as error:
                messages.error(request, "; ".join(getattr(error, "messages", [str(error)])))
            else:
                messages.success(request, "Case work started.")
            return redirect("web:case-detail", pk=case.pk)
        if action in {"publish_progress", "complete_work"}:
            work_form = ProgressUpdateForm(request.POST, building_id=building_id, uploader_id=request.user.pk)
            if work_form.is_valid():
                try:
                    service = complete_case_work if action == "complete_work" else publish_progress
                    service(case, request.user, work_form.cleaned_data["cause"],
                            work_form.cleaned_data["result"],
                            list(work_form.cleaned_data["before_versions"]),
                            list(work_form.cleaned_data["after_versions"]))
                except (ValidationError, PermissionDenied) as error:
                    if isinstance(error, ValidationError):
                        work_form.add_error(None, error)
                    else:
                        raise
                else:
                    messages.success(request, "Case work completed." if action == "complete_work" else "Progress published.")
                    return redirect("web:case-detail", pk=case.pk)

    if work_form is None:
        work_form = ProgressUpdateForm(building_id=building_id, uploader_id=request.user.pk)

    return render(
        request,
        "web/staff/case_detail.html",
        staff_context(
            request,
            membership,
            memberships,
            nav_active="cases",
            report=report,
            case=case,
            form=None,
            work_form=work_form,
            legacy_items=[],
            updates=case.updates.order_by("-created_at"),
            ratings=case.completion_ratings.select_related("resident").order_by("created_at"),
            can_create_proposal=(
                not hasattr(case, "proposal")
                and spending_proposal_cases().filter(pk=case.pk).exists()
            ),
            list_mode=False,
            mode="case",
        ),
    )
