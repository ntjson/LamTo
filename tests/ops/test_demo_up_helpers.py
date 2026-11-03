"""ops/demo/demo_up.py: the small helpers `up.sh` leans on."""

from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path

import pytest

from tests.ops.test_demo_smoke import FakeClamAV

REPO_ROOT = Path(__file__).resolve().parents[2]
HELPER = REPO_ROOT / "ops" / "demo" / "demo_up.py"
KIT_FILES = REPO_ROOT / "ops" / "demo-kit" / "files"


def run(*args, timeout=60):
    return subprocess.run(
        [sys.executable, "-I", str(HELPER), *args], capture_output=True, text=True, timeout=timeout
    )


class TestTunnelAddress:
    def test_the_quick_tunnels_name_is_read_from_cloudflareds_log(self, tmp_path):
        log = tmp_path / "cloudflared.log"
        log.write_text(
            "INF Requesting new quick Tunnel on trycloudflare.com...\n"
            "INF |  https://quiet-fox-0a1b.trycloudflare.com  |\n"
        )

        result = run("tunnel-address", str(log), "--timeout", "1")

        assert result.stdout.strip() == "https://quiet-fox-0a1b.trycloudflare.com"

    def test_cloudflares_own_api_host_is_not_the_tunnel(self, tmp_path):
        log = tmp_path / "cloudflared.log"
        log.write_text(
            "ERR failed to request https://api.trycloudflare.com/tunnel: timeout\n"
            "INF https://calm-owl.trycloudflare.com\n"
        )

        assert run("tunnel-address", str(log), "--timeout", "1").stdout.strip() == (
            "https://calm-owl.trycloudflare.com"
        )

    def test_no_address_in_time_is_a_failure(self, tmp_path):
        log = tmp_path / "cloudflared.log"
        log.write_text("INF starting\n")

        assert run("tunnel-address", str(log), "--timeout", "1").returncode != 0


class TestKitSite:
    def test_the_kit_is_copied_with_a_vietnamese_index_listing_every_file(self, tmp_path):
        result = run("kit-site", str(KIT_FILES), str(tmp_path / "kit"))

        assert result.returncode == 0, result.stderr
        index = (tmp_path / "kit" / "index.html").read_text(encoding="utf-8")
        assert '<html lang="vi">' in index
        for pdf in KIT_FILES.glob("*.pdf"):
            assert f'href="{pdf.name}"' in index
            assert (tmp_path / "kit" / pdf.name).read_bytes() == pdf.read_bytes()
        assert "Báo giá sửa thang máy" in index

    def test_a_file_removed_from_the_kit_leaves_the_site(self, tmp_path):
        site = tmp_path / "kit"
        site.mkdir()
        (site / "old.pdf").write_bytes(b"%PDF old")

        run("kit-site", str(KIT_FILES), str(site))

        assert not (site / "old.pdf").exists()


class TestWaitForClamav:
    def test_returns_as_soon_as_clamav_answers(self):
        clamav = FakeClamAV()
        clamav.start()
        try:
            assert run("wait-clamav", f"127.0.0.1:{clamav.port}", "--timeout", "5").returncode == 0
        finally:
            clamav.server.close()

    def test_gives_up_after_the_timeout_when_nothing_answers(self):
        import socket

        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]

        assert run("wait-clamav", f"127.0.0.1:{port}", "--timeout", "1").returncode != 0

    def test_a_listener_that_does_not_speak_clamd_is_not_clamav(self):
        import socket

        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen(4)

        def accept():
            while True:
                try:
                    connection, _ = server.accept()
                except OSError:
                    return
                connection.close()

        threading.Thread(target=accept, daemon=True).start()
        try:
            port = server.getsockname()[1]
            assert run("wait-clamav", f"127.0.0.1:{port}", "--timeout", "1").returncode != 0
        finally:
            server.close()


class TestPortsFree:
    def test_a_port_with_a_listener_is_reported(self):
        import socket

        with socket.socket() as server:
            server.bind(("127.0.0.1", 0))
            server.listen(1)
            port = server.getsockname()[1]
            result = run("ports-free", str(port))

        assert result.returncode != 0
        assert str(port) in result.stderr

    def test_free_ports_pass(self):
        import socket

        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]

        assert run("ports-free", str(port)).returncode == 0


class TestShowAddress:
    def test_the_address_and_a_qr_code_for_the_app_are_drawn(self):
        result = run("show-address", "https://quiet-fox.trycloudflare.com")

        assert result.returncode == 0, result.stderr
        assert "https://quiet-fox.trycloudflare.com/app/" in result.stdout
        assert "https://quiet-fox.trycloudflare.com/s/" in result.stdout
        assert "https://quiet-fox.trycloudflare.com/demo-kit/" in result.stdout
        # Block characters of the drawn code.
        assert any(ch in result.stdout for ch in "█▀▄")
