"""Resident API v1 (spec 3). Staff get no API in Phase 0/1."""

from django.urls import path

from lamto.api import views, gate_views

app_name = "api"

urlpatterns = [
    path("auth/login", views.LoginView.as_view(), name="auth-login"),
    path("auth/logout", views.LogoutView.as_view(), name="auth-logout"),
    path("auth/logout-all", views.LogoutAllView.as_view(), name="auth-logout-all"),
    path("me", views.MeView.as_view(), name="me"),
    path(
        "me/notification-preferences",
        views.MeNotificationPreferencesView.as_view(),
        name="me-notification-preferences",
    ),
    path("ledger", views.LedgerListView.as_view(), name="ledger-list"),
    path("ledger/<int:pk>", views.LedgerDetailView.as_view(), name="ledger-detail"),
    path("fund/summary", views.FundSummaryView.as_view(), name="fund-summary"),
    path("fund/series", views.FundSeriesView.as_view(), name="fund-series"),
    path("reports", views.ReportListCreateView.as_view(), name="reports"),
    path("reports/<int:pk>", views.ReportDetailView.as_view(), name="report-detail"),
    path("reports/<int:pk>/info-reply", views.ReportInfoReplyView.as_view(), name="report-info-reply"),
    path("reports/<int:pk>/photos", views.ReportPhotoUploadView.as_view(), name="report-photos"),
    path("cases/<int:pk>/rating", views.CaseRatingView.as_view(), name="case-rating"),
    path("proposals", views.ProposalListView.as_view(), name="proposal-list"),
    path("proposals/<int:pk>", views.ProposalDetailView.as_view(), name="proposal-detail"),
    path("proposals/<int:pk>/rating", views.ProposalRatingView.as_view(), name="proposal-rating"),
    path("locations", views.LocationListView.as_view(), name="locations"),
    path("notifications", views.NotificationListView.as_view(), name="notifications"),
    path(
        "notifications/<int:pk>/read",
        views.NotificationReadView.as_view(),
        name="notification-read",
    ),
    path("devices", views.DeviceRegisterView.as_view(), name="devices"),
    path(
        "devices/<str:install_id>",
        views.DeviceDeleteView.as_view(),
        name="device-delete",
    ),
    path("documents/<str:token>", views.DocumentDownloadView.as_view(), name="document-download"),
    path("gate/registrations", gate_views.GateRegistrationsView.as_view(), name="gate-registrations"),
    path("gate/plates", gate_views.GatePlateListCreateView.as_view(), name="gate-plates"),
    path("gate/plates/<int:pk>", gate_views.GatePlateDetailView.as_view(), name="gate-plate-detail"),
    path("gate/face", gate_views.GateFaceView.as_view(), name="gate-face"),
    path("gate/recognize/face", gate_views.GateRecognizeFaceView.as_view(), name="gate-recognize-face"),
    path("gate/recognize/plate", gate_views.GateRecognizePlateView.as_view(), name="gate-recognize-plate"),
]
