from django.urls import path
from django.views.generic import RedirectView

from lamto.web.views import exports, fund, health, proposals, requests, security, settlements, staff_common

app_name = "web"

urlpatterns = [
    path("", RedirectView.as_view(pattern_name="web:staff-home", permanent=False), name="root"),
    # Security / MFA
    path("s/security/mfa/setup/", security.mfa_setup, name="mfa-setup"),
    path("s/security/mfa/verify/", security.mfa_verify, name="mfa-verify"),
    path("s/security/mfa/revoke/<int:device_id>/", security.mfa_revoke_device, name="mfa-revoke"),
    path("s/security/reauth/", security.reauth, name="reauth"),
    # Shell
    path("s/", staff_common.staff_home, name="staff-home"),
    path("s/inbox/", staff_common.action_inbox, name="action-inbox"),
    path("s/building/", staff_common.switch_building, name="switch-building"),
    # Requests (cases + reports)
    path("s/cases/", requests.case_list, name="case-list"),
    path("s/reports/<int:pk>/", requests.report_detail, name="staff-report-detail"),
    path("s/cases/<int:pk>/", requests.case_detail, name="case-detail"),
    # Proposals
    path("s/proposals/", proposals.proposal_list, name="proposal-list"),
    path("s/proposals/new/", proposals.standalone_proposal_create, name="standalone-proposal-create"),
    path("s/proposals/<int:pk>/", proposals.proposal_detail, name="proposal-detail"),
    path("s/cases/<int:pk>/propose/", proposals.proposal_create, name="proposal-create"),
    path("s/settlements/", settlements.settlement_list, name="settlement-list"),
    path("s/settlements/record/<int:pk>/", settlements.settlement_record_transfer, name="settlement-record-transfer"),
    path("s/settlements/<int:pk>/ack/", settlements.settlement_record_ack, name="settlement-record-ack"),
    path("s/settlements/<int:pk>/", settlements.settlement_detail, name="settlement-detail"),
    # Exports
    path("s/audit/export/", exports.audit_export, name="audit-export"),
    # Fund
    path("s/fund/", fund.fund_home, name="fund-home"),
    path("s/fund/record/", fund.fund_record, name="fund-record"),
    path("s/fund/verify/<int:pk>/", fund.fund_verify, name="fund-verify"),
    # Ops
    path("s/ops/health/", health.ops_health, name="ops-health"),
    path("s/ops/metrics/", health.pilot_metrics, name="pilot-metrics"),
]
