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
            "/api/v1/reports",
        ):
            assert route in content, f"{route} missing from committed schema"
        # spectacular names the <int:pk> parameter {id} when it can infer a
        # model, {pk} otherwise; either spelling proves the route is present.
        assert (
            "/api/v1/ledger/{id}" in content or "/api/v1/ledger/{pk}" in content
        ), "ledger detail route missing from committed schema"
        assert (
            "/api/v1/reports/{id}" in content or "/api/v1/reports/{pk}" in content
        ), "report detail route missing from committed schema"
        assert (
            "/api/v1/reports/{id}/photos" in content
            or "/api/v1/reports/{pk}/photos" in content
        ), "report photos upload route missing from committed schema"
        assert (
            "/api/v1/work/{id}/rating" in content
            or "/api/v1/work/{pk}/rating" in content
        ), "work rating route missing from committed schema"


    def test_schema_includes_rfc9457_problem_component(self):
        content = SCHEMA_PATH.read_text()
        # Component schema name from ProblemSerializer (clarification 3).
        assert "\n    Problem:" in content, "Problem component missing from schema"
        for field in ("type:", "title:", "status:", "code:"):
            assert field in content
        assert "application/problem+json" in content

    def test_tenant_routes_document_occupancy_header(self):
        """Optional X-LamTo-Occupancy is a header parameter on each tenant path."""
        import yaml

        schema = yaml.safe_load(SCHEMA_PATH.read_text())
        paths = schema["paths"]
        detail_key = (
            "/api/v1/ledger/{id}"
            if "/api/v1/ledger/{id}" in paths
            else "/api/v1/ledger/{pk}"
        )
        tenant_gets = (
            paths["/api/v1/ledger"]["get"],
            paths[detail_key]["get"],
            paths["/api/v1/fund/summary"]["get"],
        )
        for operation in tenant_gets:
            names = {
                (param.get("name") if isinstance(param, dict) else None)
                for param in operation.get("parameters", [])
            }
            assert "X-LamTo-Occupancy" in names, (
                f"X-LamTo-Occupancy header missing from {operation.get('operationId')}"
            )
        # Non-tenant routes must not require the occupancy header.
        login_params = paths["/api/v1/auth/login"]["post"].get("parameters") or []
        login_names = {
            (p.get("name") if isinstance(p, dict) else None) for p in login_params
        }
        assert "X-LamTo-Occupancy" not in login_names
