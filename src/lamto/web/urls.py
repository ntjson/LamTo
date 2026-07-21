from django.urls import path

from lamto.web.views import auditor, board, fund, maintenance, operator, resident
from lamto.web.views import exports, health, security, staff_common

app_name = "web"

urlpatterns = [
    # Resident
    path("", resident.home, name="resident-home"),
    path("r/", resident.home, name="resident-home-alias"),
    path("r/report/new/", resident.report_create, name="report-create"),
    path("r/reports/", resident.report_list, name="report-list"),
    path("r/reports/<int:pk>/", resident.report_detail, name="report-detail"),
    path("r/work/<int:pk>/rate/", resident.work_rate, name="work-rate"),
    path("r/ledger/", resident.ledger_list, name="ledger-list"),
    path("r/ledger/<int:pk>/", resident.ledger_detail, name="ledger-detail"),
    path("r/account/", resident.account, name="account"),
    path("r/occupancy/", resident.switch_occupancy, name="switch-occupancy"),
    path("offline/", resident.offline, name="offline"),
    path("manifest.webmanifest", resident.manifest, name="manifest"),
    path("service-worker.js", resident.service_worker, name="service-worker"),
    # Security / MFA
    path("s/security/mfa/setup/", security.mfa_setup, name="mfa-setup"),
    path("s/security/mfa/verify/", security.mfa_verify, name="mfa-verify"),
    path("s/security/mfa/revoke/<int:device_id>/", security.mfa_revoke_device, name="mfa-revoke"),
    path("s/security/reauth/", security.reauth, name="reauth"),
    # Staff shell
    path("s/", staff_common.staff_home, name="staff-home"),
    path("s/inbox/", staff_common.action_inbox, name="action-inbox"),
    path("s/building/", staff_common.switch_building, name="switch-building"),
    # Operator / shared case & proposal — distinct routes for report vs case PKs
    path("s/cases/", operator.case_list, name="case-list"),
    path("s/reports/<int:pk>/", operator.report_detail, name="staff-report-detail"),
    path("s/cases/<int:pk>/", operator.case_detail, name="case-detail"),
    path("s/proposals/", operator.proposal_list, name="proposal-list"),
    path("s/proposals/<int:pk>/", operator.proposal_detail, name="proposal-detail"),
    # Maintenance / work
    path("s/work/", maintenance.work_order_list, name="work-order-list"),
    path("s/work/<int:pk>/", maintenance.work_order_detail, name="work-order-detail"),
    path("s/work/<int:pk>/propose/", operator.proposal_create, name="proposal-create"),
    path("s/work/<int:pk>/accept/", board.accept_work, name="work-accept"),
    # Board payments — distinct routes for acceptance record vs payment verify
    path("s/payments/", board.payment_list, name="payment-list"),
    path("s/payments/record/", board.payment_record, name="payment-record"),
    path(
        "s/payments/record/<int:pk>/",
        board.payment_record_detail,
        name="payment-record-detail",
    ),
    path(
        "s/payments/verify/<int:pk>/",
        board.payment_verify_detail,
        name="payment-verify-detail",
    ),
    # Auditor
    path("s/audit/", auditor.audit_search, name="audit-search"),
    path("s/audit/export/", exports.audit_export, name="audit-export"),
    # Fund ops (record/verify handlers filled in Tasks 4–5)
    path("s/fund/", fund.fund_home, name="fund-home"),
    path("s/fund/record/", fund.fund_record, name="fund-record"),
    path("s/fund/verify/<int:pk>/", fund.fund_verify, name="fund-verify"),

    # Ops health / pilot metrics (tech admin)
    path("s/ops/health/", health.ops_health, name="ops-health"),
    path("s/ops/metrics/", health.pilot_metrics, name="pilot-metrics"),
]
