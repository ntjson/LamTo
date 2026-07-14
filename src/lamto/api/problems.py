"""RFC 9457 problem+json errors with stable machine codes (spec 3.1).

`detail` is developer English; the Flutter client owns all Vietnamese
user-facing copy keyed off `code`. Never include stack traces or internal
identifiers in responses.
"""

from http import HTTPStatus

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.http import Http404
from rest_framework import exceptions
from rest_framework.views import exception_handler as drf_exception_handler

PROBLEM_CONTENT_TYPE = "application/problem+json"


class OccupancySelectionRequired(exceptions.APIException):
    """Multiple active occupancies and no X-LamTo-Occupancy header (spec 3.4)."""

    status_code = 422
    default_detail = (
        "Multiple active occupancies; select one with the X-LamTo-Occupancy header."
    )
    default_code = "occupancy_selection_required"


# Most specific classes first: the first isinstance() match wins.
_EXCEPTION_CODES = (
    (OccupancySelectionRequired, "occupancy_selection_required"),
    (exceptions.NotAuthenticated, "not_authenticated"),
    (exceptions.AuthenticationFailed, "authentication_failed"),
    (exceptions.PermissionDenied, "permission_denied"),
    (exceptions.NotFound, "not_found"),
    (exceptions.MethodNotAllowed, "method_not_allowed"),
    (exceptions.Throttled, "throttled"),
    (exceptions.ParseError, "validation_failed"),
    (exceptions.UnsupportedMediaType, "validation_failed"),
    (exceptions.ValidationError, "validation_failed"),
    (Http404, "not_found"),
    (DjangoPermissionDenied, "permission_denied"),
)


def _field_errors(detail):
    """Preserve DRF's per-field error structure while exposing machine codes."""
    if isinstance(detail, dict):
        return {key: _field_errors(value) for key, value in detail.items()}
    if isinstance(detail, list):
        return [_field_errors(item) for item in detail]
    return {"message": str(detail), "code": getattr(detail, "code", "invalid")}


def problem_exception_handler(exc, context):
    response = drf_exception_handler(exc, context)
    if response is None:
        # Not an API exception: let Django's standard 500 path handle it.
        return None
    code = next(
        (code for klass, code in _EXCEPTION_CODES if isinstance(exc, klass)), "error"
    )
    problem = {
        "type": "about:blank",
        "title": HTTPStatus(response.status_code).phrase,
        "status": response.status_code,
        "code": code,
    }
    if isinstance(exc, exceptions.ValidationError):
        problem["detail"] = "Request validation failed."
        problem["errors"] = _field_errors(exc.detail)
    elif isinstance(exc, exceptions.APIException):
        problem["detail"] = str(exc.detail)
    elif isinstance(exc, Http404):
        problem["detail"] = "Not found."
    else:  # django.core.exceptions.PermissionDenied
        problem["detail"] = "Permission denied."
    response.data = problem
    # DRF keeps an explicitly set content_type through finalize_response.
    response.content_type = PROBLEM_CONTENT_TYPE
    return response
