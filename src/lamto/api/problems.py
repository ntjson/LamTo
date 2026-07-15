"""RFC 9457 problem+json errors with stable machine codes (spec 3.1).

`detail` is developer English; the Flutter client owns all Vietnamese
user-facing copy keyed off `code`. Never include stack traces or internal
identifiers in responses.
"""

from http import HTTPStatus

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.http import Http404
from drf_spectacular.utils import OpenApiResponse
from rest_framework import exceptions
from rest_framework.views import exception_handler as drf_exception_handler

from lamto.api.serializers import ProblemSerializer

PROBLEM_CONTENT_TYPE = "application/problem+json"

# OpenAPI media type for documented problem responses (clarification 3).
_PROBLEM_DESCRIPTIONS = {
    400: "Validation failed (code=validation_failed).",
    401: (
        "Authentication required or failed "
        "(code=not_authenticated or authentication_failed)."
    ),
    403: "Permission denied (code=permission_denied).",
    404: "Resource not found (code=not_found).",
    409: "client_ref reused with different content (code=client_ref_conflict).",
    422: (
        "Occupancy selection required "
        "(code=occupancy_selection_required); send X-LamTo-Occupancy."
    ),
    429: "Too many authentication attempts (code=throttled).",
}


def problem_responses(*status_codes: int) -> dict:
    """Map HTTP statuses to reusable RFC 9457 Problem OpenAPI responses.

    Keys use the ``application/problem+json`` media type so the committed
    schema documents the wire content type the exception handler sets.
    """
    responses = {}
    for status in status_codes:
        try:
            description = _PROBLEM_DESCRIPTIONS[status]
        except KeyError as exc:
            raise ValueError(f"no Problem description for status {status}") from exc
        responses[(status, PROBLEM_CONTENT_TYPE)] = OpenApiResponse(
            response=ProblemSerializer,
            description=description,
        )
    return responses


class OccupancySelectionRequired(exceptions.APIException):
    """Multiple active occupancies and no X-LamTo-Occupancy header (spec 3.4)."""

    status_code = 422
    default_detail = (
        "Multiple active occupancies; select one with the X-LamTo-Occupancy header."
    )
    default_code = "occupancy_selection_required"


class ClientRefConflict(exceptions.APIException):
    """POST /reports retried with the same client_ref but different content (spec 3.5)."""

    status_code = 409
    default_detail = "client_ref reused with different content."
    default_code = "client_ref_conflict"


# Most specific classes first: the first isinstance() match wins.
_EXCEPTION_CODES = (
    (OccupancySelectionRequired, "occupancy_selection_required"),
    (ClientRefConflict, "client_ref_conflict"),
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
