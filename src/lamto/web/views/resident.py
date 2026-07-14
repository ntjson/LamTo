from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_http_methods

from lamto.accounts.tenancy import resolve_resident_occupancy
from lamto.finance.fund import fund_balance
from lamto.finance.models import MaintenanceFundEntry
from lamto.finance.selectors import (
    fund_period_flows,
    published_ledger_entries,
    verified_fund_entries,
)
from lamto.maintenance.models import CaseReport, IssueReport, WorkOrder
from lamto.maintenance.selectors import rateable_work_orders, resident_reports
from lamto.web.forms.resident import ResidentReportForm, WorkRatingForm
from lamto.notifications.models import NotificationDelivery
from lamto.web.forms.staff import NotificationPreferenceForm


def _integrity_display(entry):
    """Map effective integrity status to plain-language label, style, and icon."""
    status = entry.effective_integrity_status
    if status == "VERIFIED":
        return {
            "label": "Record verified",
            "css_class": "status-verified",
            "icon": "✓",
            "alert": False,
        }
    if status == "MISMATCH":
        return {
            "label": "Integrity mismatch detected",
            "css_class": "status-mismatch",
            "icon": "!",
            "alert": True,
        }
    if status == "UNAVAILABLE":
        return {
            "label": "Integrity check unavailable",
            "css_class": "status-warning",
            "icon": "!",
            "alert": False,
        }
    # UNCHECKED or unknown: published, but integrity not yet observed.
    return {
        "label": "Published — integrity not yet checked",
        "css_class": "status-info",
        "icon": "○",
        "alert": False,
    }


def _apply_integrity_display(entry):
    display = _integrity_display(entry)
    entry.integrity_label = display["label"]
    entry.integrity_class = display["css_class"]
    entry.integrity_icon = display["icon"]
    entry.integrity_alert = display["alert"]
    return entry


@login_required
@require_GET
def home(request):
    occupancy, _occupancies = resolve_resident_occupancy(request)
    building = occupancy.unit.building
    balance = fund_balance(building.pk, verified_only=True)
    opening = (
        verified_fund_entries(building.pk)
        .filter(entry_type=MaintenanceFundEntry.EntryType.OPENING_BALANCE)
        .order_by("recorded_at", "pk")
        .first()
    )
    inflows, outflows = fund_period_flows(building.pk)
    active_reports = resident_reports(request.user).filter(status=IssueReport.Status.OPEN)[
        :10
    ]
    recent_spending = list(published_ledger_entries(building.pk)[:5])
    for entry in recent_spending:
        _apply_integrity_display(entry)
    return render(
        request,
        "web/resident/home.html",
        {
            "occupancy": occupancy,
            "building": building,
            "balance": balance,
            "opening_balance": opening.amount_vnd if opening else None,
            "period_inflows": inflows,
            "period_outflows": outflows,
            "active_reports": active_reports,
            "recent_spending": recent_spending,
            "nav_active": "home",
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def report_create(request):
    occupancy, _occupancies = resolve_resident_occupancy(request)
    form = ResidentReportForm(
        request.POST or None,
        request.FILES or None,
        resident=request.user,
        occupancy=occupancy,
    )
    if request.method == "POST" and form.is_valid():
        photos = request.FILES.getlist("photos")
        try:
            report = form.save(files=photos)
        except (ValidationError, PermissionDenied) as error:
            if isinstance(error, ValidationError):
                form.add_error(None, error)
            else:
                raise
        else:
            messages.success(request, "Report submitted.")
            return redirect("web:report-detail", pk=report.pk)
    return render(
        request,
        "web/resident/report_form.html",
        {
            "form": form,
            "occupancy": occupancy,
            "nav_active": "report",
        },
    )


@login_required
@require_GET
def report_list(request):
    occupancy, _occupancies = resolve_resident_occupancy(request)
    reports = resident_reports(request.user)
    return render(
        request,
        "web/resident/report_list.html",
        {
            "reports": reports,
            "occupancy": occupancy,
            "nav_active": "issues",
        },
    )


@login_required
@require_GET
def report_detail(request, pk):
    occupancy, _occupancies = resolve_resident_occupancy(request)
    report = get_object_or_404(
        IssueReport.objects.select_related("unit", "selected_location"),
        pk=pk,
        reporter=request.user,
    )
    rateable = rateable_work_orders(request.user, report)
    return render(
        request,
        "web/resident/report_detail.html",
        {
            "report": report,
            "rateable_work_orders": rateable,
            "occupancy": occupancy,
            "nav_active": "issues",
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def work_rate(request, pk):
    occupancy, _occupancies = resolve_resident_occupancy(request)
    work_order = get_object_or_404(
        WorkOrder.objects.select_related("case"),
        pk=pk,
    )
    owns = CaseReport.objects.filter(
        case_id=work_order.case_id, report__reporter=request.user
    ).exists()
    if not owns:
        raise PermissionDenied("You can only rate work linked to your reports.")
    form = WorkRatingForm(
        request.POST or None,
        resident=request.user,
        work_order=work_order,
    )
    if request.method == "POST" and form.is_valid():
        try:
            form.save()
        except (ValidationError, PermissionDenied) as error:
            if isinstance(error, ValidationError):
                form.add_error(None, error)
            else:
                raise
        else:
            messages.success(request, "Thank you for your rating.")
            report = (
                CaseReport.objects.filter(
                    case_id=work_order.case_id, report__reporter=request.user
                )
                .select_related("report")
                .first()
            )
            if report is not None:
                return redirect("web:report-detail", pk=report.report_id)
            return redirect("web:report-list")
    return render(
        request,
        "web/resident/work_rating_form.html",
        {
            "form": form,
            "work_order": work_order,
            "occupancy": occupancy,
            "nav_active": "issues",
        },
    )


@login_required
@require_GET
def ledger_list(request):
    occupancy, _occupancies = resolve_resident_occupancy(request)
    entries = list(published_ledger_entries(occupancy.unit.building_id)[:100])
    for entry in entries:
        _apply_integrity_display(entry)
    return render(
        request,
        "web/resident/ledger_list.html",
        {
            "entries": entries,
            "occupancy": occupancy,
            "nav_active": "ledger",
        },
    )


@login_required
@require_GET
def ledger_detail(request, pk):
    occupancy, _occupancies = resolve_resident_occupancy(request)
    entry = (
        published_ledger_entries(occupancy.unit.building_id)
        .filter(pk=pk)
        .first()
    )
    if entry is None:
        raise Http404("Published ledger entry not found.")
    payload = entry.snapshot.resident_payload or {}
    version = entry.proposal.current_version
    verification = getattr(entry.payment, "verification", None)
    redacted_docs = []
    acceptance = getattr(entry.work_order, "acceptance", None)
    if acceptance is not None:
        for label, version_obj in (
            ("Invoice (redacted)", acceptance.invoice_redacted),
            ("Acceptance report (redacted)", acceptance.acceptance_redacted),
        ):
            if version_obj is not None:
                redacted_docs.append(
                    {
                        "label": label,
                        "filename": version_obj.filename,
                        "sha256": version_obj.sha256,
                    }
                )
    proof_redacted = entry.payment.proof_redacted
    if proof_redacted is not None:
        redacted_docs.append(
            {
                "label": "Payment proof (redacted)",
                "filename": proof_redacted.filename,
                "sha256": proof_redacted.sha256,
            }
        )
    corrections = [
        correction
        for correction in entry.corrections.all()
        if correction.is_resident_visible
    ]
    tx_ids = []
    for event in (
        entry.snapshot.outbox_event,
        getattr(verification, "outbox_event", None) if verification else None,
        entry.payment.outbox_event,
    ):
        if event is not None and event.transaction_hash:
            tx_ids.append(event.transaction_hash)
    emergency = payload.get("emergency")
    integrity = _integrity_display(entry)
    return render(
        request,
        "web/resident/ledger_detail.html",
        {
            "entry": entry,
            "payload": payload,
            "proposed_amount": (
                version.amount_vnd if version is not None else payload.get("proposed_amount_vnd")
            ),
            "approvals": payload.get("approvals") or {},
            "verification": verification,
            "redacted_docs": redacted_docs,
            "corrections": corrections,
            "transaction_ids": tx_ids,
            "emergency": emergency,
            "integrity_label": integrity["label"],
            "integrity_class": integrity["css_class"],
            "integrity_icon": integrity["icon"],
            "integrity_alert": integrity["alert"],
            "integrity_status": entry.effective_integrity_status,
            "occupancy": occupancy,
            "nav_active": "ledger",
        },
    )


@login_required
@require_http_methods(["POST"])
def switch_occupancy(request):
    occupancy_id = request.POST.get("occupancy")
    if occupancy_id is None:
        raise Http404("occupancy is required")
    resolve_resident_occupancy(request, occupancy_id=occupancy_id)
    next_url = request.POST.get("next") or ""
    if not url_has_allowed_host_and_scheme(
        next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        next_url = ""
    return redirect(next_url or "web:resident-home")


@login_required
@require_http_methods(["GET", "POST"])
def account(request):
    occupancy, occupancies = resolve_resident_occupancy(request)
    pref_form = NotificationPreferenceForm(request.POST or None, user=request.user)
    if request.method == "POST" and request.POST.get("action") == "prefs" and pref_form.is_valid():
        pref_form.save()
        messages.success(request, "Notification preferences saved.")
        return redirect("web:account")
    notices = (
        NotificationDelivery.objects.filter(
            recipient=request.user,
            channel=NotificationDelivery.Channel.IN_APP,
            status=NotificationDelivery.Status.AVAILABLE,
        )
        .order_by("-created_at")[:20]
    )
    return render(
        request,
        "web/resident/account.html",
        {
            "occupancy": occupancy,
            "occupancies": occupancies,
            "user_obj": request.user,
            "nav_active": "account",
            "pref_form": pref_form,
            "notices": notices,
        },
    )


@require_GET
def offline(request):
    return render(request, "web/resident/offline.html", {"nav_active": None})


@require_GET
def manifest(request):
    from django.contrib.staticfiles.finders import find
    from django.contrib.staticfiles.storage import staticfiles_storage

    path = find("web/manifest.webmanifest")
    if path is None:
        raise Http404("Manifest not found.")
    with open(path, "rb") as handle:
        content = handle.read()
    return HttpResponse(content, content_type="application/manifest+json")


@require_GET
def service_worker(request):
    from django.contrib.staticfiles.finders import find

    path = find("web/service-worker.js")
    if path is None:
        raise Http404("Service worker not found.")
    with open(path, "rb") as handle:
        content = handle.read()
    response = HttpResponse(content, content_type="application/javascript")
    response["Service-Worker-Allowed"] = "/"
    return response
