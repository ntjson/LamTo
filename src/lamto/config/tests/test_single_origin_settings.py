"""Settings the single-origin deployment (Caddy + gunicorn) is configured by."""

import json
import os
import runpy
import subprocess
import sys
from pathlib import Path

from django.test import SimpleTestCase

from lamto.documents import scanner

REPO_ROOT = Path(__file__).resolve().parents[4]


def read_setting(name, **env):
    """Import settings in a fresh interpreter, with *env* layered over ours."""
    environment = {**os.environ, **env}
    for key, value in list(environment.items()):
        if value is None:
            del environment[key]
    code = (
        "import json; from lamto.config import settings; "
        f"print(json.dumps(getattr(settings, {name!r}, None)))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


class StaticRootTests(SimpleTestCase):
    def test_static_root_is_read_from_the_environment(self):
        self.assertEqual(
            read_setting("STATIC_ROOT", STATIC_ROOT="/srv/lamto/static"),
            "/srv/lamto/static",
        )

    def test_static_root_is_unset_without_the_environment(self):
        self.assertIsNone(read_setting("STATIC_ROOT", STATIC_ROOT=None))


class QuickTunnelHostTests(SimpleTestCase):
    def test_tunnel_domain_is_allowed_through_the_environment_alone(self):
        hosts = read_setting(
            "ALLOWED_HOSTS",
            ALLOWED_HOSTS="localhost,127.0.0.1,quiet-fox-1234.trycloudflare.com",
        )
        self.assertIn("quiet-fox-1234.trycloudflare.com", hosts)


class GunicornConfigTests(SimpleTestCase):
    def load(self):
        return runpy.run_path(str(REPO_ROOT / "ops" / "gunicorn.conf.py"))

    def test_binds_loopback_only(self):
        self.assertTrue(self.load()["bind"].startswith("127.0.0.1:"))

    def test_request_timeout_is_comfortably_above_the_clamav_scan_timeout(self):
        timeout = self.load()["timeout"]
        self.assertGreaterEqual(timeout, 3 * scanner.SCAN_TIMEOUT_SECONDS)
