#!/bin/sh
# Entry point of the trial image (ops/trial/Dockerfile).
#
#   web     migrate, seed the demo building on first boot, collect static
#           files into /srv/static (shared with Caddy), then run gunicorn
#   worker  run the background worker loop (outbox, inbox, integrity checks)
#   *       anything else runs as given, e.g. `python manage.py seed_demo ...`
set -eu
cd /srv/lamto

case "${1:-web}" in
web)
  POSTGRES_USER=lamto_owner POSTGRES_PASSWORD=lamto-owner \
    python manage.py migrate --noinput

  # First boot only: the marker lives in the database volume's neighbour,
  # the static volume, so a container restart never seeds twice. seed_demo
  # also refuses on its own when the building already exists.
  if [ ! -f /srv/static/.seeded ]; then
    PILOT_ALLOW_FIXTURES=1 python manage.py seed_demo --password "${TRIAL_PASSWORD}" \
      | tee /srv/static/.logins.txt
    touch /srv/static/.seeded
  fi

  STATIC_ROOT=/srv/static/files python manage.py collectstatic --noinput --clear >/dev/null
  exec gunicorn --config ops/gunicorn.conf.py --bind 0.0.0.0:8000 \
    lamto.config.wsgi:application
  ;;
worker)
  exec python manage.py run_worker
  ;;
*)
  exec "$@"
  ;;
esac
