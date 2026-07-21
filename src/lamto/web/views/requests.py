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
)
from lamto.maintenance.models import IssueReport, MaintenanceCase, WorkOrder
from lamto.web.forms.staff import (
    ConfirmTriageForm,
    CreateProposalForm,
    CreateWorkOrderForm,
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
        .annotate(work_count=Count("work_orders"))
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
            work_orders=[],
            list_mode=False,
            mode="report",
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
        if action == "create_work_order":
            require_management_context(request)
            work_form = CreateWorkOrderForm(request.POST, building_id=building_id)
            if work_form.is_valid():
                try:
                    wo = work_form.save(case, request.user)
                except (ValidationError, PermissionDenied) as error:
                    if isinstance(error, ValidationError):
                        work_form.add_error(None, error)
                    else:
                        raise
                else:
                    messages.success(
                        request,
                        f"Work order #{wo.pk} created. The assignee can now start work.",
                    )
                    return redirect("web:work-order-detail", pk=wo.pk)

    if work_form is None:
        work_form = CreateWorkOrderForm(building_id=building_id)

    work_orders = list(case.work_orders.order_by("-created_at"))

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
            work_orders=work_orders,
            list_mode=False,
            mode="case",
        ),
    )
