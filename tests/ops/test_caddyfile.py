"""ops/Caddyfile, run for real against a stand-in for gunicorn.

Needs a ``caddy`` binary (on PATH, or named by CADDY_BIN); skipped otherwise.
"""

from __future__ import annotations

import http.client
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CADDYFILE = REPO_ROOT / "ops" / "Caddyfile"
DEMO_DIR = REPO_ROOT / "ops" / "demo"
CADDY = os.getenv("CADDY_BIN") or shutil.which("caddy")

pytestmark = pytest.mark.skipif(CADDY is None, reason="caddy binary not available")


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class EchoUpstream(BaseHTTPRequestHandler):
    """Stands in for gunicorn: answers with the headers it was sent."""

    def do_GET(self):
        body = json.dumps(dict(self.headers.items()) | {"path": self.path}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_POST = do_GET

    def log_message(self, *args):
        pass


def _front_door(root, extra_env=None):
    """Caddy in front of a stand-in gunicorn, serving the site under `root`."""
    app = root / "app"
    (app / "assets").mkdir(parents=True)
    (app / "index.html").write_text("<html>resident app</html>")
    (app / "main.dart.js").write_text("console.log('plain')")
    (app / "main.dart.js.gz").write_bytes(b"GZ-BYTES")
    (app / "main.dart.js.br").write_bytes(b"BR-BYTES")
    (app / "module.wasm").write_bytes(b"\0asm")
    (app / "module.wasm.br").write_bytes(b"BR-WASM")
    static = root / "static" / "web"
    static.mkdir(parents=True)
    (static / "staff.css").write_text("body { color: red; }")

    upstream_port = free_port()
    upstream = ThreadingHTTPServer(("127.0.0.1", upstream_port), EchoUpstream)
    threading.Thread(target=upstream.serve_forever, daemon=True).start()

    caddy_port = free_port()
    caddy = subprocess.Popen(
        [CADDY, "run", "--config", str(CADDYFILE), "--adapter", "caddyfile"],
        env={
            **os.environ,
            "CADDY_PORT": str(caddy_port),
            "GUNICORN_PORT": str(upstream_port),
            "STATIC_ROOT": str(root / "static"),
            "APP_WEB_ROOT": str(app),
            "XDG_DATA_HOME": str(root / "caddy-data"),
            **(extra_env or {}),
        },
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            try:
                socket.create_connection(("127.0.0.1", caddy_port), timeout=0.2).close()
                break
            except OSError:
                time.sleep(0.1)
        else:
            pytest.fail("caddy did not start listening")
        yield caddy_port
    finally:
        caddy.terminate()
        caddy.wait(timeout=10)
        upstream.shutdown()


@pytest.fixture(scope="module")
def front_door(tmp_path_factory):
    yield from _front_door(tmp_path_factory.mktemp("front-door"))


@pytest.fixture(scope="module")
def demo_front_door(tmp_path_factory):
    """The same front door set up the way ops/demo/up.sh sets it up."""
    root = tmp_path_factory.mktemp("demo-front-door")
    kit = root / "kit"
    subprocess.run(
        [sys.executable, "-I", str(DEMO_DIR / "demo_up.py"), "kit-site",
         str(REPO_ROOT / "ops" / "demo-kit" / "files"), str(kit)],
        check=True, capture_output=True,
    )
    yield from _front_door(
        root,
        {
            "CADDY_EXTRA_ROUTES": str(DEMO_DIR / "demo-kit.caddy"),
            "DEMO_KIT_ROOT": str(kit),
        },
    )


def request(port, path, headers=None, method="GET"):
    """A raw request: no transparent decompression, no redirect following."""
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    connection.request(method, path, headers=headers or {})
    response = connection.getresponse()
    body = response.read()
    headers = {k.lower(): v for k, v in response.getheaders()}
    connection.close()
    return response.status, headers, body


def upstream_saw(port, path="/", headers=None):
    status, _, body = request(port, path, headers)
    assert status == 200
    return {k.lower(): v for k, v in json.loads(body).items()}


class TestResidentAppUnderApp:
    def test_app_root_serves_the_index_page(self, front_door):
        status, _, body = request(front_door, "/app/")
        assert status == 200
        assert b"resident app" in body

    def test_unknown_path_below_app_falls_back_to_the_index_page(self, front_door):
        status, _, body = request(front_door, "/app/reports/42/photos")
        assert status == 200
        assert b"resident app" in body

    def test_app_without_a_trailing_slash_redirects_to_it(self, front_door):
        status, headers, _ = request(front_door, "/app")
        assert status in (301, 308)
        assert headers["location"] == "/app/"

    def test_wasm_is_served_as_application_wasm(self, front_door):
        _, headers, _ = request(front_door, "/app/module.wasm")
        assert headers["content-type"] == "application/wasm"

    def test_precompressed_wasm_keeps_the_wasm_type(self, front_door):
        _, headers, body = request(
            front_door, "/app/module.wasm", {"Accept-Encoding": "br"}
        )
        assert body == b"BR-WASM"
        assert headers["content-type"] == "application/wasm"
        assert headers["content-encoding"] == "br"

    def test_brotli_copy_is_served_when_the_client_accepts_it(self, front_door):
        _, headers, body = request(
            front_door, "/app/main.dart.js", {"Accept-Encoding": "gzip, br"}
        )
        assert body == b"BR-BYTES"
        assert headers["content-encoding"] == "br"

    def test_gzip_copy_is_served_when_only_gzip_is_accepted(self, front_door):
        _, headers, body = request(
            front_door, "/app/main.dart.js", {"Accept-Encoding": "gzip"}
        )
        assert body == b"GZ-BYTES"
        assert headers["content-encoding"] == "gzip"

    def test_plain_file_is_served_to_a_client_accepting_nothing(self, front_door):
        _, headers, body = request(front_door, "/app/main.dart.js")
        assert body == b"console.log('plain')"
        assert "content-encoding" not in headers

    @pytest.mark.parametrize(
        "path", ["/app/", "/app/main.dart.js", "/app/module.wasm", "/app/no/such/route"]
    )
    def test_every_file_revalidates(self, front_door, path):
        _, headers, _ = request(front_door, path)
        assert headers["cache-control"] == "no-cache"
        assert "etag" in headers

    def test_a_matching_etag_revalidates_to_not_modified(self, front_door):
        _, headers, _ = request(front_door, "/app/main.dart.js")
        status, _, _ = request(
            front_door, "/app/main.dart.js", {"If-None-Match": headers["etag"]}
        )
        assert status == 304


class TestStaticAssets:
    def test_collected_assets_are_served_from_the_static_root(self, front_door):
        status, headers, body = request(front_door, "/static/web/staff.css")
        assert status == 200
        assert body == b"body { color: red; }"
        assert headers["content-type"].startswith("text/css")

    def test_a_missing_asset_is_not_proxied_to_django(self, front_door):
        status, _, _ = request(front_door, "/static/web/nope.css")
        assert status == 404


class TestProxyToGunicorn:
    def test_other_paths_reach_the_upstream_unchanged(self, front_door):
        seen = upstream_saw(front_door, "/s/cases/?page=2")
        assert seen["path"] == "/s/cases/?page=2"

    def test_the_host_the_browser_used_reaches_django(self, front_door):
        seen = upstream_saw(front_door, "/", {"Host": "quiet-fox.trycloudflare.com"})
        assert seen["host"] == "quiet-fox.trycloudflare.com"

    def test_post_is_proxied(self, front_door):
        status, _, body = request(front_door, "/s/login/", method="POST")
        assert status == 200
        assert json.loads(body)["path"] == "/s/login/"

    def test_https_from_cloudflared_is_passed_through(self, front_door):
        seen = upstream_saw(front_door, headers={"X-Forwarded-Proto": "https"})
        assert seen["x-forwarded-proto"] == "https"

    def test_client_address_comes_from_the_cloudflare_connecting_ip(self, front_door):
        seen = upstream_saw(front_door, headers={"CF-Connecting-IP": "203.0.113.9"})
        assert seen["x-forwarded-for"] == "203.0.113.9"

    def test_a_forwarded_for_sent_by_the_client_is_replaced_not_trusted(
        self, front_door
    ):
        seen = upstream_saw(
            front_door,
            headers={
                "X-Forwarded-For": "198.51.100.7, 10.0.0.1",
                "CF-Connecting-IP": "203.0.113.9",
            },
        )
        assert seen["x-forwarded-for"] == "203.0.113.9"

    def test_a_forwarded_for_alone_is_never_the_client_address(self, front_door):
        seen = upstream_saw(front_door, headers={"X-Forwarded-For": "198.51.100.7"})
        assert "198.51.100.7" not in seen["x-forwarded-for"]


KIT_PDF = "bao-gia-sua-thang-may-mau.pdf"


class TestDemoKit:
    def test_the_kit_is_not_served_outside_the_demo_setup(self, front_door):
        # Without the demo's extra routes the path is just another Django URL.
        assert upstream_saw(front_door, f"/demo-kit/{KIT_PDF}")["path"] == f"/demo-kit/{KIT_PDF}"

    def test_the_index_page_is_vietnamese_and_lists_the_files(self, demo_front_door):
        status, headers, body = request(demo_front_door, "/demo-kit/")
        assert status == 200
        assert headers["content-type"].startswith("text/html")
        page = body.decode("utf-8")
        assert '<html lang="vi">' in page
        assert f'href="{KIT_PDF}"' in page

    def test_a_kit_pdf_is_served_as_a_pdf(self, demo_front_door):
        status, headers, body = request(demo_front_door, f"/demo-kit/{KIT_PDF}")
        assert status == 200
        assert headers["content-type"] == "application/pdf"
        assert body == (REPO_ROOT / "ops" / "demo-kit" / "files" / KIT_PDF).read_bytes()

    def test_the_kit_without_a_trailing_slash_redirects_to_it(self, demo_front_door):
        status, headers, _ = request(demo_front_door, "/demo-kit")
        assert status in (301, 308)
        assert headers["location"] == "/demo-kit/"

    def test_a_file_not_in_the_kit_is_not_found(self, demo_front_door):
        status, _, _ = request(demo_front_door, "/demo-kit/nope.pdf")
        assert status == 404

    def test_the_rest_of_the_site_still_reaches_django(self, demo_front_door):
        assert upstream_saw(demo_front_door, "/s/")["path"] == "/s/"
