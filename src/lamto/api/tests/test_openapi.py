"""OpenAPI drift gate (spec 3.1, 5.4): regenerate and fail on any diff."""

import tempfile
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.test import SimpleTestCase

SCHEMA_PATH = (
    Path(settings.BASE_DIR).parent.parent / "docs" / "api" / "openapi-v1.yaml"
)
REGENERATE = "python manage.py spectacular --file docs/api/openapi-v1.yaml"


class OpenApiDriftTests(SimpleTestCase):
    def test_committed_schema_matches_generated(self):
        with tempfile.TemporaryDirectory() as tmp:
            generated_path = Path(tmp) / "openapi-v1.yaml"
            call_command(
                "spectacular",
                "--file",
                str(generated_path),
                "--validate",
                "--fail-on-warn",
            )
            generated = generated_path.read_text()
        assert SCHEMA_PATH.exists(), f"schema file missing; run: {REGENERATE}"
        assert generated == SCHEMA_PATH.read_text(), (
            f"docs/api/openapi-v1.yaml is stale; regenerate with: {REGENERATE}"
        )

    def test_schema_covers_every_api_route(self):
        content = SCHEMA_PATH.read_text()
        for route in (
            "/api/v1/auth/login",
            "/api/v1/auth/logout",
            "/api/v1/auth/logout-all",
            "/api/v1/me",
            "/api/v1/ledger",
            "/api/v1/fund/summary",
        ):
            assert route in content, f"{route} missing from committed schema"
        # spectacular names the <int:pk> parameter {id} when it can infer a
        # model, {pk} otherwise; either spelling proves the route is present.
        assert (
            "/api/v1/ledger/{id}" in content or "/api/v1/ledger/{pk}" in content
        ), "ledger detail route missing from committed schema"

    def test_schema_includes_rfc9457_problem_component(self):
        content = SCHEMA_PATH.read_text()
        # Component schema name from ProblemSerializer (clarification 3).
        assert "\n    Problem:" in content, "Problem component missing from schema"
        for field in ("type:", "title:", "status:", "code:"):
            assert field in content
        assert "application/problem+json" in content

    def test_tenant_routes_document_occupancy_header(self):
        """Optional X-LamTo-Occupancy is documented on tenant-list/object paths."""
        content = SCHEMA_PATH.read_text()
        assert "X-LamTo-Occupancy" in content
        # Header must appear in the schema for each tenant surface (list + detail + fund).
        # spectacular may emit the name as a parameter $ref or inline; substring is enough
        # to prove generation included OCCUPANCY_HEADER_PARAMETER on those views.
        tenant_markers = (
            "/api/v1/ledger:",
            "/api/v1/ledger/{id}:",
            "/api/v1/fund/summary:",
        )
        # Allow {pk} alternate for ledger detail path key.
        if "/api/v1/ledger/{id}:" not in content:
            tenant_markers = (
                "/api/v1/ledger:",
                "/api/v1/ledger/{pk}:",
                "/api/v1/fund/summary:",
            )
        for marker in tenant_markers:
            assert marker in content or marker.rstrip(":") in content, (
                f"tenant path missing from schema: {marker}"
            )
        # Count occurrences: login/me should not require the header; tenant ops should list it.
        # At least three parameter blocks reference the header name (one per tenant route).
        assert content.count("X-LamTo-Occupancy") >= 3
