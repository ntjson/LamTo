# Task 3 report — staff fund chart and window stats

## Status

Implemented the reusable Chart.js contract, range-aware fund series context, window reconciliation stats, staff fund UI, responsive chart styling, reduced-motion behavior, and Vietnamese translations.

## RED

Command:

```bash
set -a; source .env; set +a
export POSTGRES_USER=lamto_owner POSTGRES_PASSWORD=lamto-owner PYTHONPATH="$PWD/src"
.venv/bin/python manage.py test lamto.web.tests.test_fund_ops.FundHomeTests -v 1
```

Result: RED as expected for all three new tests: missing `fund-chart-data`, `chart_points`, and `window_opening_vnd`. One pre-existing assertion also failed because the current page renders “Publish settled expenses” rather than the older pending-section wording.

## Chart.js vendor

- URL: `https://cdn.jsdelivr.net/npm/chart.js@4.4.9/dist/chart.umd.js`
- Version/sanity: first bytes report `Chart.js v4.4.9` and its MIT license; file size 206,670 bytes.
- SHA-256: `de315773454b6076b63990bfa05ce5155a37f71992c87d7bb5f9a2ea698697ef`
- The vendored file was downloaded unchanged with the prescribed `curl`; it was not hand-authored or truncated.

## Translation commands

The prescribed host `manage.py makemessages -l vi` could not run because GNU gettext (`msguniq`) is absent. I ran gettext in a disposable `python:3.12-slim` container, added the exact new Vietnamese translations without changing existing entries, and compiled the catalog with:

```bash
docker run --rm -v "$PWD:/app" -w /app python:3.12-slim \
  sh -c 'apt-get update -qq && apt-get install -y -qq gettext >/dev/null && msgfmt locale/vi/LC_MESSAGES/django.po -o locale/vi/LC_MESSAGES/django.mo'
```

## GREEN

Isolated new tests:

```bash
.venv/bin/python manage.py test \
  lamto.web.tests.test_fund_ops.FundHomeTests.test_fund_home_renders_chart_and_window_stats \
  lamto.web.tests.test_fund_ops.FundHomeTests.test_fund_home_range_toggle_and_fallback \
  lamto.web.tests.test_fund_ops.FundHomeTests.test_fund_home_window_stats_reconcile -v 1
```

Result: PASS — 3 tests.

Prescribed combined suite:

```bash
.venv/bin/python manage.py test lamto.web.tests.test_fund_ops.FundHomeTests lamto.web.tests.test_staff_ui -v 1
```

Result: 36/37 pass. The sole failure is the unchanged pre-existing `test_fund_home_shows_balance_entries_and_pending` wording assertion documented under RED; all new tests and all `test_staff_ui` tests pass.

## Design and accessibility

- Reused the existing panel, button, stat-grid, spacing, and color vocabulary; no new visual language or dependency was added beyond the explicitly required vendored Chart.js.
- The chart has an accessible name, the range control is labelled, the selected range uses `aria-current`, and links retain repo-native button focus behavior.
- The chart uses a fixed-height responsive container, preserves signed outflow bars, and disables Chart.js animation when `prefers-reduced-motion: reduce` matches.

## Files

- `src/lamto/web/views/fund.py`
- `src/lamto/web/templates/web/staff/fund_detail.html`
- `src/lamto/web/static/web/app.css`
- `src/lamto/web/static/web/chart.umd.js`
- `src/lamto/web/static/web/fund-chart.js`
- `src/lamto/web/tests/test_fund_ops.py`
- `locale/vi/LC_MESSAGES/django.po`
- `locale/vi/LC_MESSAGES/django.mo`

## Self-review

- `git diff --check` passes.
- Range fallback is constrained by the shared selector constants.
- Dates are serialized before `json_script`; no unsafe JSON interpolation is used.
- Window opening is derived from closing minus signed flows and is covered by the reconciliation test.
- The JS exits safely if its DOM contract, Chart.js, or points are absent, so form-mode rendering remains unaffected.

## Commit

Pending at report creation; see final task status for SHA and subject.

## Concerns

- Host gettext tooling is missing; future translation extraction should install GNU gettext or continue using a controlled container.
- The pre-existing fund-home wording test is stale against the current template and remains intentionally untouched.
