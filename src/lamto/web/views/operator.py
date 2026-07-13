"""Operator workspace: triage, cases, work orders, proposals."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods

from lamto.accounts.capabilities import PROPOSAL_CREATE, REPORT_TRIAGE, WORK_ASSIGN
from lamto.audit.services import record_audit
from lamto.maintenance.models import IssueReport, MaintenanceCase, WorkOrder
from lamto.web.forms.staff import ConfirmTriageForm, CreateWorkOrderForm
from lamto.web.staff import require_staff_capability, resolve_active_membership, staff_context


@login_required
@require_GET
def case_list(request):
    membership, memberships = require_staff_capability(request, REPORT_TRIAGE)
    building_id = membership.organization.building_id
    open_reports = (
        IssueReport.objects.filter(unit__building_id=building_id, status=IssueReport.Status.OPEN)
        .order_by("-created_at")[:100]
    )
    cases = (
        MaintenanceCase.objects.filter(building_id=building_id, active=True)
        .order_by("-created_at")[:100]
    )
    return render(
        request,
        "web/staff/case_detail.html",
        staff_context(
            request,
            membership,
            memberships,
            nav_active="cases",
            list_mode=True,
            open_reports=open_reports,
            cases=cases,
        ),
    )


@login_required
@require_http_methods(["GET", "POST"])
def case_detail(request, pk):
    membership, memberships = resolve_active_membership(request)
    building_id = membership.organization.building_id

    # pk may be IssueReport or MaintenanceCase
    report = IssueReport.objects.filter(pk=pk, unit__building_id=building_id).first()
    case = None
    if report is None:
        case = get_object_or_404(MaintenanceCase, pk=pk, building_id=building_id)
        report = case.reports.order_by("pk").first()
    else:
        link = report.case_reports.filter(case__active=True).select_related("case").first()
        if link is not None:
            case = link.case

    form = None
    work_form = None
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "confirm_triage":
            require_staff_capability(request, REPORT_TRIAGE)
            form = ConfirmTriageForm(
                request.POST, building_id=building_id
            )
            if form.is_valid() and report is not None:
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
                    messages.success(request, "Triage confirmed.")
                    return redirect("web:case-detail", pk=case.pk)
        elif action == "create_work_order" and case is not None:
            require_staff_capability(request, WORK_ASSIGN)
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
                    messages.success(request, f"Work order #{wo.pk} created.")
                    return redirect("web:work-order-detail", pk=wo.pk)

    if form is None:
        form = ConfirmTriageForm(building_id=building_id)
    if work_form is None and case is not None:
        work_form = CreateWorkOrderForm(building_id=building_id)

    work_orders = []
    if case is not None:
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
            form=form,
            work_form=work_form,
            work_orders=work_orders,
            list_mode=False,
        ),
    )


@login_required
@require_GET
def proposal_list(request):
    from lamto.accounts.capabilities import PROPOSAL_APPROVE
    from lamto.finance.models import Proposal

    membership, memberships = resolve_active_membership(request)
    caps = set(
        membership.capabilitygrant_set.values_list("code", flat=True)
    )
    if PROPOSAL_CREATE not in caps and PROPOSAL_APPROVE not in caps:
        record_audit(
            request.user,
            membership,
            "workspace.proposal.list",
            "OrganizationMembership",
            str(membership.pk),
            "denied",
            {},
        )
        raise PermissionDenied("proposal access")

    building_id = membership.organization.building_id
    proposals = (
        Proposal.objects.filter(work_order__case__building_id=building_id)
        .select_related("current_version", "work_order")
        .order_by("-created_at")[:100]
    )
    return render(
        request,
        "web/staff/proposal_detail.html",
        staff_context(
            request,
            membership,
            memberships,
            nav_active="proposals",
            list_mode=True,
            proposals=proposals,
        ),
    )


@login_required
@require_http_methods(["GET", "POST"])
def proposal_detail(request, pk):
    from lamto.accounts.capabilities import PROPOSAL_APPROVE
    from lamto.finance.models import Proposal
    from lamto.web.forms.staff import ProposalDecisionForm

    membership, memberships = resolve_active_membership(request)
    caps = set(membership.capabilitygrant_set.values_list("code", flat=True))
    if PROPOSAL_CREATE not in caps and PROPOSAL_APPROVE not in caps:
        raise PermissionDenied("proposal access")

    proposal = get_object_or_404(
        Proposal.objects.select_related(
            "current_version", "work_order__case", "creator_membership"
        ),
        pk=pk,
        work_order__case__building_id=membership.organization.building_id,
    )
    form = ProposalDecisionForm(request.POST or None)
    if request.method == "POST" and form.is_valid() and PROPOSAL_APPROVE in caps:
        version = proposal.current_version
        try:
            form.save(version, membership)
        except (ValidationError, PermissionDenied) as error:
            if isinstance(error, ValidationError):
                form.add_error(None, error)
            else:
                raise
        else:
            messages.success(request, "Decision recorded.")
            return redirect("web:proposal-detail", pk=proposal.pk)

    return render(
        request,
        "web/staff/proposal_detail.html",
        staff_context(
            request,
            membership,
            memberships,
            nav_active="proposals",
            list_mode=False,
            proposal=proposal,
            version=proposal.current_version,
            form=form if PROPOSAL_APPROVE in caps else None,
            can_approve=PROPOSAL_APPROVE in caps,
        ),
    )
