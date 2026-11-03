"""Helpers for ops/demo/up.sh. Standard library plus `qrcode`, run with `python -I`.

    demo_up.py ports-free PORT...
    demo_up.py wait-clamav HOST:PORT [--timeout SECONDS]
    demo_up.py kit-site SOURCE_DIR DEST_DIR
    demo_up.py tunnel-address LOG_FILE [--timeout SECONDS]
    demo_up.py smoke BASE_URL --app-root DIR --static-root DIR --kit-dir DIR
                    --clamav HOST:PORT --worker-pid PID
    demo_up.py show-address BASE_URL

Each prints what it found on stdout and exits non-zero, with a reason on stderr,
when the demo is not ready.
"""

from __future__ import annotations

import argparse
import html
import http.client
import json
import os
import re
import socket
import struct
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

USER_AGENT = "lamto-demo-smoke/1"
SCAN_TIMEOUT_SECONDS = 20

# The kit's files as the visitor sees them, in the order the index lists them.
# Anything else in the folder is listed after these under its file name.
KIT_DESCRIPTIONS = {
    "bao-gia-sua-thang-may-mau.pdf": (
        "Báo giá sửa thang máy",
        "Báo giá của Công ty TNHH Thang máy Mẫu — dùng khi tạo đề xuất xử lý.",
    ),
    "chung-tu-thanh-toan-mau.pdf": (
        "Chứng từ chuyển khoản",
        "Chứng từ chuyển khoản mẫu — dùng khi ghi nhận thanh toán.",
    ),
    "thong-bao-tam-ngung-thang-may.pdf": (
        "Thông báo tạm ngưng thang máy",
        "Thông báo để in ra, dán trong thang máy và chụp ảnh khi gửi phản ánh.",
    ),
}
# The three files the smoke check loads and has ClamAV scan: the quotation, the
# Transfer proof and the out-of-service notice.
KIT_FILES = tuple(KIT_DESCRIPTIONS)


# ---------------------------------------------------------------------------
# ClamAV


def _split_address(address: str) -> tuple[str, int]:
    host, _, port = address.rpartition(":")
    return host, int(port)


def clamav_ping(host: str, port: int, timeout: float = 3) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout) as connection:
            connection.sendall(b"zPING\0")
            return connection.recv(64).rstrip(b"\0\n") == b"PONG"
    except OSError:
        return False


def wait_for_clamav(host: str, port: int, timeout: float, interval: float = 2) -> bool:
    deadline = time.monotonic() + timeout
    while True:
        if clamav_ping(host, port):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(interval)


def clamav_scan(host: str, port: int, data: bytes) -> str:
    """The verdict clamd gives for `data`, e.g. 'stream: OK'."""
    with socket.create_connection((host, port), timeout=SCAN_TIMEOUT_SECONDS) as connection:
        connection.sendall(b"zINSTREAM\0")
        for start in range(0, len(data), 8192):
            chunk = data[start : start + 8192]
            connection.sendall(struct.pack("!I", len(chunk)) + chunk)
        connection.sendall(struct.pack("!I", 0))
        response = b""
        while not response.endswith(b"\0"):
            part = connection.recv(4096)
            if not part:
                break
            response += part
    return response.rstrip(b"\0\n").decode("utf-8", "replace")


# ---------------------------------------------------------------------------
# The kit, served at /demo-kit/


def kit_index_html(names: list[str]) -> str:
    ordered = [n for n in KIT_DESCRIPTIONS if n in names]
    ordered += sorted(n for n in names if n not in KIT_DESCRIPTIONS)
    items = []
    for name in ordered:
        title, note = KIT_DESCRIPTIONS.get(name, (name, ""))
        items.append(
            f'    <li><a href="{html.escape(urllib.parse.quote(name))}">{html.escape(title)}</a>'
            f" <small>({html.escape(name)})</small>"
            + (f"<br><span>{html.escape(note)}</span>" if note else "")
            + "</li>"
        )
    body = "\n".join(items)
    return f"""<!doctype html>
<html lang="vi">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Bộ tài liệu mẫu — LamTo</title>
  <style>
    body {{ font-family: system-ui, sans-serif; max-width: 40rem; margin: 2rem auto; padding: 0 1rem; line-height: 1.5; }}
    li {{ margin-bottom: 1rem; }}
    span, small {{ color: #555; }}
  </style>
</head>
<body>
  <h1>Bộ tài liệu mẫu</h1>
  <p>Các tài liệu dưới đây là dữ liệu giả lập, chuẩn bị sẵn để bạn thử luồng xử lý một phản ánh
  từ đầu đến cuối. Bấm vào tên để mở hoặc tải về.</p>
  <ul>
{body}
  </ul>
</body>
</html>
"""


def build_kit_site(source: Path, dest: Path) -> list[str]:
    """Copy the kit's PDFs into `dest` with a Vietnamese index.html beside them."""
    pdfs = sorted(source.glob("*.pdf"))
    if not pdfs:
        raise SystemExit(f"No PDFs in {source}.")
    dest.mkdir(parents=True, exist_ok=True)
    for stale in dest.iterdir():
        if stale.is_file():
            stale.unlink()
    for pdf in pdfs:
        (dest / pdf.name).write_bytes(pdf.read_bytes())
    names = [pdf.name for pdf in pdfs]
    (dest / "index.html").write_text(kit_index_html(names), encoding="utf-8")
    return names


# ---------------------------------------------------------------------------
# The tunnel


_TUNNEL_URL = re.compile(r"https://([a-z0-9]+(?:-[a-z0-9]+)*)\.trycloudflare\.com")


def find_tunnel_address(log_text: str, pattern: str | None = None) -> str | None:
    """The quick tunnel's address in cloudflared's log; `api.` is Cloudflare's own.

    `pattern` replaces the built-in pattern, for a cloudflared that prints its
    address differently (DEMO_TUNNEL_URL_PATTERN).
    """
    if pattern:
        match = re.search(pattern, log_text)
        return match.group(0) if match else None
    for match in _TUNNEL_URL.finditer(log_text):
        if match.group(1) != "api":
            return match.group(0)
    return None


def wait_for_tunnel(log_file: Path, timeout: float, pattern: str | None = None) -> str | None:
    deadline = time.monotonic() + timeout
    while True:
        if log_file.exists():
            address = find_tunnel_address(log_file.read_text(errors="replace"), pattern)
            if address:
                return address
        if time.monotonic() >= deadline:
            return None
        time.sleep(0.5)


# ---------------------------------------------------------------------------
# The smoke check


class CheckFailed(Exception):
    pass


class Response:
    def __init__(self, status, headers, body, url):
        self.status, self.headers, self.body, self.url = status, headers, body, url

    def header(self, name: str) -> str:
        return self.headers.get(name.lower(), "")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def fetch(url: str, headers: dict[str, str] | None = None, *, follow: bool = True) -> Response:
    """GET without transparent decompression. Redirects are followed unless `follow` is off."""
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity", **(headers or {})}
    )
    opener = urllib.request.build_opener() if follow else urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(request, timeout=30) as response:
            return Response(
                response.status,
                {k.lower(): v for k, v in response.getheaders()},
                response.read(),
                response.geturl(),
            )
    except urllib.error.HTTPError as error:
        return Response(error.code, {k.lower(): v for k, v in error.headers.items()}, error.read(), url)
    except (urllib.error.URLError, http.client.HTTPException, OSError) as error:
        raise CheckFailed(f"{url} could not be reached: {getattr(error, 'reason', error)}") from error


def _expect_ok(response: Response, what: str) -> Response:
    if response.status != 200:
        raise CheckFailed(f"{what} answered {response.status}, not 200 ({response.url})")
    return response


def check_app(base: str, ctx) -> str:
    index = ctx.app_root / "index.html"
    if not index.is_file():
        raise CheckFailed(f"the web build has no index.html in {ctx.app_root}")
    response = _expect_ok(fetch(f"{base}/app/"), "/app/")
    if response.body != index.read_bytes():
        raise CheckFailed("/app/ does not serve the build's index.html")
    return "/app/ serves the build's index"


def check_wasm(base: str, ctx) -> str:
    wasm_files = sorted(ctx.app_root.rglob("*.wasm"))
    if not wasm_files:
        raise CheckFailed(f"the web build has no .wasm file in {ctx.app_root}")
    relative = wasm_files[0].relative_to(ctx.app_root).as_posix()
    response = _expect_ok(
        fetch(f"{base}/app/{relative}", {"Accept-Encoding": "br, gzip"}), f"/app/{relative}"
    )
    kind = response.header("content-type").split(";")[0].strip()
    if kind != "application/wasm":
        raise CheckFailed(f"/app/{relative} is served as '{kind}', not application/wasm")
    if response.header("content-encoding") not in {"br", "gzip"}:
        raise CheckFailed(f"/app/{relative} comes back uncompressed")
    return f"{relative} is application/wasm, {response.header('content-encoding')}"


def check_static(base: str, ctx) -> str:
    files = sorted(p for p in ctx.static_root.rglob("*") if p.is_file())
    if not files:
        raise CheckFailed(f"no collected static files in {ctx.static_root}")
    chosen = next((p for p in files if p.suffix == ".css"), files[0])
    relative = chosen.relative_to(ctx.static_root).as_posix()
    response = _expect_ok(fetch(f"{base}/static/{relative}"), f"/static/{relative}")
    if not response.body:
        raise CheckFailed(f"/static/{relative} is empty")
    return f"/static/{relative} loads"


def check_kit(base: str, ctx) -> str:
    for name in KIT_FILES:
        on_disk = ctx.kit_dir / name
        if not on_disk.is_file():
            raise CheckFailed(f"{name} is missing from {ctx.kit_dir}")
        response = _expect_ok(fetch(f"{base}/demo-kit/{name}"), f"/demo-kit/{name}")
        if response.body != on_disk.read_bytes():
            raise CheckFailed(f"/demo-kit/{name} is not the kit's file")
    index = _expect_ok(fetch(f"{base}/demo-kit/"), "/demo-kit/").body.decode("utf-8", "replace")
    for name in KIT_FILES:
        if name not in index:
            raise CheckFailed(f"/demo-kit/ does not list {name}")
    return f"the kit's {len(KIT_FILES)} PDFs and its index load"


def check_login(base: str, ctx) -> str:
    response = _expect_ok(fetch(f"{base}/s/"), "/s/")
    page = response.body.decode("utf-8", "replace").lower()
    if 'type="password"' not in page:
        raise CheckFailed(f"/s/ did not end at the login page (ended at {response.url})")
    return "/s/ shows the login page"


def check_api(base: str, ctx) -> str:
    response = _expect_ok(fetch(f"{base}/api/v1/registration/options"), "/api/v1/")
    try:
        buildings = json.loads(response.body)
    except ValueError as error:
        raise CheckFailed("/api/v1/registration/options did not answer with JSON") from error
    if not isinstance(buildings, list) or not buildings:
        raise CheckFailed("/api/v1/ lists no building: has the demo been seeded?")
    return "/api/v1/registration/options answers with the seeded building"


def _is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    try:
        # A process that has exited but not been reaped still answers kill 0.
        state = Path(f"/proc/{pid}/stat").read_text().rpartition(")")[2].split()[0]
    except (OSError, IndexError):
        return True
    return state not in {"Z", "X"}


def check_worker(base: str, ctx) -> str:
    if not _is_running(ctx.worker_pid):
        raise CheckFailed(f"the worker (pid {ctx.worker_pid}) is not running")
    return f"the worker is running (pid {ctx.worker_pid})"


def check_clamav(base: str, ctx) -> str:
    host, port = _split_address(ctx.clamav)
    for name in KIT_FILES:
        path = ctx.kit_dir / name
        if not path.is_file():
            raise CheckFailed(f"{name} is missing from {ctx.kit_dir}")
        try:
            verdict = clamav_scan(host, port, path.read_bytes())
        except OSError as error:
            raise CheckFailed(f"ClamAV could not scan {name}: {error}") from error
        if not verdict.endswith(": OK"):
            raise CheckFailed(f"ClamAV says {name} is not clean: {verdict or 'no answer'}")
    return f"ClamAV finds {len(KIT_FILES)} kit files clean"


CHECKS = (
    ("app", check_app),
    ("wasm", check_wasm),
    ("static", check_static),
    ("kit", check_kit),
    ("login", check_login),
    ("api", check_api),
    ("worker", check_worker),
    ("clamav", check_clamav),
)


def wait_until_reachable(base: str, timeout: float) -> None:
    """A new quick-tunnel name can take a while to resolve; wait for it once."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            status = fetch(f"{base}/app/").status
            problem = f"{base}/app/ answered {status}" if status >= 500 else None
        except CheckFailed as error:
            problem = str(error)
        if problem is None:
            return
        if time.monotonic() >= deadline:
            raise SystemExit(f"FAIL  tunnel  {problem}")
        time.sleep(2)


def run_smoke(base: str, ctx, reach_timeout: float = 90) -> bool:
    base = base.rstrip("/")
    wait_until_reachable(base, reach_timeout)
    passed = True
    for name, check in CHECKS:
        try:
            print(f"ok  {name}  {check(base, ctx)}", flush=True)
        except CheckFailed as error:
            passed = False
            print(f"FAIL  {name}  {error}", file=sys.stderr, flush=True)
    return passed


# ---------------------------------------------------------------------------
# Address and QR code


def show_address(base: str, out=None) -> None:
    import qrcode

    out = out or sys.stdout
    base = base.rstrip("/")
    app_url = f"{base}/app/"
    code = qrcode.QRCode(border=2)
    code.add_data(app_url)
    code.make(fit=True)
    code.print_ascii(out=out, invert=True)
    print(file=out)
    print(f"  Điện thoại (quét mã QR trên):  {app_url}", file=out)
    print(f"  Máy tính, gửi qua Zalo:        {app_url}", file=out)
    print(f"  Trang quản lý:                 {base}/s/", file=out)
    print(f"  Bộ tài liệu mẫu:               {base}/demo-kit/", file=out)


# ---------------------------------------------------------------------------


def ports_in_use(ports: list[int]) -> list[int]:
    busy = []
    for port in ports:
        with socket.socket() as probe:
            probe.settimeout(0.5)
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                busy.append(port)
    return busy


class _Smoke:
    def __init__(self, args):
        self.app_root = args.app_root
        self.static_root = args.static_root
        self.kit_dir = args.kit_dir
        self.clamav = args.clamav
        self.worker_pid = args.worker_pid


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)

    ports = commands.add_parser("ports-free")
    ports.add_argument("ports", type=int, nargs="+")

    clam = commands.add_parser("wait-clamav")
    clam.add_argument("address")
    clam.add_argument("--timeout", type=float, default=300)

    kit = commands.add_parser("kit-site")
    kit.add_argument("source", type=Path)
    kit.add_argument("dest", type=Path)

    tunnel = commands.add_parser("tunnel-address")
    tunnel.add_argument("log_file", type=Path)
    tunnel.add_argument("--timeout", type=float, default=60)

    smoke = commands.add_parser("smoke")
    smoke.add_argument("base_url")
    smoke.add_argument("--app-root", type=Path, required=True)
    smoke.add_argument("--static-root", type=Path, required=True)
    smoke.add_argument("--kit-dir", type=Path, required=True)
    smoke.add_argument("--clamav", required=True)
    smoke.add_argument("--worker-pid", type=int, required=True)
    smoke.add_argument("--reach-timeout", type=float, default=90)

    show = commands.add_parser("show-address")
    show.add_argument("base_url")

    args = parser.parse_args(argv)

    if args.command == "ports-free":
        busy = ports_in_use(args.ports)
        if busy:
            print(" ".join(str(p) for p in busy), file=sys.stderr)
            return 1
        return 0
    if args.command == "wait-clamav":
        host, port = _split_address(args.address)
        return 0 if wait_for_clamav(host, port, args.timeout) else 1
    if args.command == "kit-site":
        for name in build_kit_site(args.source, args.dest):
            print(name)
        return 0
    if args.command == "tunnel-address":
        address = wait_for_tunnel(
            args.log_file, args.timeout, os.environ.get("DEMO_TUNNEL_URL_PATTERN") or None
        )
        if not address:
            return 1
        print(address)
        return 0
    if args.command == "smoke":
        return 0 if run_smoke(args.base_url, _Smoke(args), args.reach_timeout) else 1
    show_address(args.base_url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
