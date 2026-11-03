# One origin: Caddy in front of Django

With debug off, nothing in Django serves the workspace's styles, and the
Resident app's web build (ADR 0009) needs somewhere to live. Caddy fronts both,
so a phone and a laptop use one address:

| Path | Served by |
|---|---|
| `/static/` | Caddy, from the directory `collectstatic` fills (`STATIC_ROOT`) |
| `/app/` | Caddy, from the web build (`flutter build web --release --base-href /app/`) |
| everything else | gunicorn, on loopback |

Files: [`Caddyfile`](Caddyfile) and [`gunicorn.conf.py`](gunicorn.conf.py).
Neither names a machine; paths and ports come from the environment.

## Run it

```bash
export STATIC_ROOT=/srv/lamto/static       # also read by Django's settings
export APP_WEB_ROOT=/srv/lamto/app         # holds the web build's index.html

python manage.py collectstatic --noinput
gunicorn --config ops/gunicorn.conf.py lamto.config.wsgi:application &
caddy run --config ops/Caddyfile --adapter caddyfile
```

Caddy listens on `127.0.0.1:8080` (`CADDY_PORT`), gunicorn on
`127.0.0.1:8000` (`GUNICORN_PORT`). Leave `DEBUG` unset.

## Behind a Cloudflare tunnel

Point cloudflared at `http://127.0.0.1:8080`. Caddy trusts loopback and nothing
else, so it believes what cloudflared sends and nothing a client sends itself.
Caddy listens on `127.0.0.1` only, which makes "loopback" mean processes on the
same machine: any of them could set these headers, so run nothing untrusted
beside it.

- `X-Forwarded-Proto: https` from cloudflared reaches Django, which treats the
  request as secure (`SECURE_PROXY_SSL_HEADER`).
- The client address Django sees is Cloudflare's `CF-Connecting-IP`. Any
  `X-Forwarded-For` the client sent is replaced.

A quick tunnel's hostname is allowed with the existing environment setting, no
code change: `ALLOWED_HOSTS=localhost,127.0.0.1,<name>.trycloudflare.com`.

## Pre-compressed web build

`/app/` serves a `.br` or `.gz` copy sitting next to a file when the client
accepts it. The demo reset script makes those copies after `flutter build web`.

## Timeouts

A document upload is virus-scanned inside its request. gunicorn's timeout
(`GUNICORN_TIMEOUT`, 60 s) stays well above ClamAV's scan timeout
(`SCAN_TIMEOUT_SECONDS`, 10 s, per socket operation); a test fails if it is
below three times that.

## Tests

`tests/ops/test_caddyfile.py` runs the Caddyfile for real against a stand-in
upstream. It needs a `caddy` binary on `PATH` (or `CADDY_BIN`) and is skipped
without one.
