"""Resident API v1 (spec 3). Staff get no API in Phase 0/1."""

from django.urls import path

from lamto.api import views

app_name = "api"

urlpatterns = [
    path("auth/login", views.LoginView.as_view(), name="auth-login"),
    path("auth/logout", views.LogoutView.as_view(), name="auth-logout"),
    path("auth/logout-all", views.LogoutAllView.as_view(), name="auth-logout-all"),
    path("me", views.MeView.as_view(), name="me"),
    path("ledger", views.LedgerListView.as_view(), name="ledger-list"),
    path("ledger/<int:pk>", views.LedgerDetailView.as_view(), name="ledger-detail"),
    path("fund/summary", views.FundSummaryView.as_view(), name="fund-summary"),
    path("reports", views.ReportListCreateView.as_view(), name="reports"),
    path("reports/<int:pk>", views.ReportDetailView.as_view(), name="report-detail"),
    path("reports/<int:pk>/photos", views.ReportPhotoUploadView.as_view(), name="report-photos"),
    path("work/<int:pk>/rating", views.WorkRatingView.as_view(), name="work-rating"),
    path("locations", views.LocationListView.as_view(), name="locations"),
    path("notifications", views.NotificationListView.as_view(), name="notifications"),
    path(
        "notifications/<int:pk>/read",
        views.NotificationReadView.as_view(),
        name="notification-read",
    ),
    path("documents/<str:token>", views.DocumentDownloadView.as_view(), name="document-download"),
]
