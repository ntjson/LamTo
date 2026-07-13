from django.urls import path

from lamto.web.views import resident

app_name = "web"

urlpatterns = [
    path("", resident.home, name="resident-home"),
    path("r/", resident.home, name="resident-home-alias"),
    path("r/report/new/", resident.report_create, name="report-create"),
    path("r/reports/", resident.report_list, name="report-list"),
    path("r/reports/<int:pk>/", resident.report_detail, name="report-detail"),
    path("r/work/<int:pk>/rate/", resident.work_rate, name="work-rate"),
    path("r/ledger/", resident.ledger_list, name="ledger-list"),
    path("r/ledger/<int:pk>/", resident.ledger_detail, name="ledger-detail"),
    path("r/account/", resident.account, name="account"),
    path("offline/", resident.offline, name="offline"),
    path("manifest.webmanifest", resident.manifest, name="manifest"),
    path("service-worker.js", resident.service_worker, name="service-worker"),
]
