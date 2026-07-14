"""Resident API v1 (spec 3). Staff get no API in Phase 0/1."""

from django.urls import path

from lamto.api import views

app_name = "api"

urlpatterns = [
    path("auth/login", views.LoginView.as_view(), name="auth-login"),
    path("auth/logout", views.LogoutView.as_view(), name="auth-logout"),
    path("auth/logout-all", views.LogoutAllView.as_view(), name="auth-logout-all"),
    path("me", views.MeView.as_view(), name="me"),
]
