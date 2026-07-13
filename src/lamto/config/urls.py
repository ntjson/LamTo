"""
URL configuration for config project.
"""
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from lamto.web.views.security import SecureLoginView, secure_logout

urlpatterns = [
    path("admin/", admin.site.urls),
    path(
        "accounts/login/",
        SecureLoginView.as_view(template_name="web/resident/login.html"),
        name="login",
    ),
    path(
        "accounts/logout/",
        secure_logout,
        name="logout",
    ),
    path("", include("lamto.web.urls")),
]
