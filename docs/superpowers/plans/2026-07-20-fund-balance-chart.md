# Fund Balance Chart Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show a verified fund-balance chart (balance line + inflow/outflow bars, 30d/6m/12m ranges) on the staff Action inbox + fund page and in the resident app Home + Sổ quỹ tabs.

**Architecture:** One selector `fund_series(building_id, *, range_key)` is the single data source. The resident app reads it through a new `GET /api/v1/fund/series` endpoint (regenerated `lamto_api` Dart client); the staff views call the selector directly and render with a vendored Chart.js. The app renders with `fl_chart`.

**Tech Stack:** Django 5 + DRF + drf-spectacular, Chart.js 4 (vendored UMD file), Flutter + Riverpod + fl_chart, OpenAPI-generated dart-dio client.

**Spec:** `docs/superpowers/specs/2026-07-20-fund-balance-chart-design.md`

## Global Constraints

- Timezone: all bucketing in the project timezone `Asia/Ho_Chi_Minh` (Django `TIME_ZONE`; `USE_TZ=True`).
- Ranges: `30d` = today + previous 29 days, daily buckets; `6m`/`12m` = current calendar month + previous 5/11 months, monthly buckets. `period_start` = first day of the bucket.
- Only verified entries (`verified_fund_entries`, same bar as `fund_balance(verified_only=True)`). Last point of the series must equal `fund_balance(building_id, verified_only=True)`.
- Sign convention (existing DB constraint `fund_entry_amount_sign`): inflow-type amounts positive, outflow-type amounts **negative**. `outflows_vnd` in the series is therefore ≤ 0. Do not flip signs.
- Reversals/corrections land in the bucket of their own `recorded_at`; historical buckets are never rewritten (this falls out of bucketing by `recorded_at` — tested explicitly).
- Deviation from spec (flagged to user): invalid `range` on the API returns **400 `validation_failed`** (repo convention for bad params, e.g. `LedgerFilterSerializer`), not 422 (which this API reserves for occupancy selection).
- fl_chart has no combo chart: the app's "full" view stacks a balance LineChart above an in/out BarChart with the same x-axis. Chart.js on staff uses a true combo (line + bar datasets).
- Backend tests: `.venv/bin/python manage.py test <label>` from repo root. Flutter tests: `flutter test <file>` from `app/`.
- New user-facing strings: staff templates use `{% trans %}` + `locale/vi`; app uses `lib/l10n/app_en.arb` + `app_vi.arb`.

---

### Task 1: `fund_series` selector

**Files:**
- Modify: `src/lamto/finance/selectors.py` (add after `fund_period_flows`, ~line 99)
- Test: `src/lamto/finance/tests/test_selectors.py` (append)

**Interfaces:**
- Consumes: existing `verified_fund_entries(building_id)`, `MaintenanceFundEntry.EntryType`.
- Produces: `FUND_SERIES_RANGE_KEYS = ("30d", "6m", "12m")`; `fund_series(building_id, *, range_key) -> list[dict]` with rows `{"period_start": date, "inflows_vnd": int, "outflows_vnd": int, "balance_vnd": int}`; pure core `fund_series_from_entries(entries, *, range_key, today)` where `entries` iterates `(recorded_at: aware datetime, entry_type: str, amount_vnd: int)`. Tasks 2–4 import `fund_series` and `FUND_SERIES_RANGE_KEYS` from `lamto.finance.selectors`.

- [ ] **Step 1: Write the failing tests**

Append to `src/lamto/finance/tests/test_selectors.py`:

```python
class FundSeriesTests(TestCase):
    """Pure bucketing core: no DB rows needed, entries passed as tuples."""

    TODAY = date(2026, 7, 20)

    @staticmethod
    def _hcm(y, m, d, hour=12):
        # Naive-local helper: build an aware UTC datetime that lands on the
        # given Asia/Ho_Chi_Minh (UTC+7) calendar day at `hour` local.
        return datetime(y, m, d, hour - 7, tzinfo=dt_timezone.utc)

    def test_invalid_range_key_raises(self):
        with self.assertRaises(ValueError):
            fund_series_from_entries([], range_key="7d", today=self.TODAY)

    def test_30d_daily_buckets_and_window(self):
        series = fund_series_from_entries([], range_key="30d", today=self.TODAY)
        assert len(series) == 30
        assert series[0]["period_start"] == date(2026, 6, 21)
        assert series[-1]["period_start"] == date(2026, 7, 20)

    def test_monthly_buckets_span_calendar_months(self):
        six = fund_series_from_entries([], range_key="6m", today=self.TODAY)
        twelve = fund_series_from_entries([], range_key="12m", today=self.TODAY)
        assert [row["period_start"] for row in six] == [
            date(2026, 2, 1), date(2026, 3, 1), date(2026, 4, 1),
            date(2026, 5, 1), date(2026, 6, 1), date(2026, 7, 1),
        ]
        assert twelve[0]["period_start"] == date(2025, 8, 1)
        assert twelve[-1]["period_start"] == date(2026, 7, 1)

    def test_seed_running_balance_and_empty_bucket_fill(self):
        entries = [
            (self._hcm(2025, 12, 10), "OPENING_BALANCE", 80_000_000),  # pre-window
            (self._hcm(2026, 3, 5), "INFLOW", 20_000_000),
            (self._hcm(2026, 6, 9), "OUTFLOW", -15_000_000),
        ]
        series = fund_series_from_entries(entries, range_key="6m", today=self.TODAY)
        by_start = {row["period_start"]: row for row in series}
        assert by_start[date(2026, 2, 1)] == {
            "period_start": date(2026, 2, 1),
            "inflows_vnd": 0, "outflows_vnd": 0, "balance_vnd": 80_000_000,
        }
        assert by_start[date(2026, 3, 1)]["inflows_vnd"] == 20_000_000
        assert by_start[date(2026, 3, 1)]["balance_vnd"] == 100_000_000
        # Empty April/May carry the balance forward.
        assert by_start[date(2026, 4, 1)]["balance_vnd"] == 100_000_000
        assert by_start[date(2026, 5, 1)]["balance_vnd"] == 100_000_000
        assert by_start[date(2026, 6, 1)]["outflows_vnd"] == -15_000_000
        assert series[-1]["balance_vnd"] == 85_000_000

    def test_timezone_boundary_buckets_by_hcm_day(self):
        # 2026-06-30 18:00 UTC = 2026-07-01 01:00 in Asia/Ho_Chi_Minh → July.
        entries = [(datetime(2026, 6, 30, 18, 0, tzinfo=dt_timezone.utc), "INFLOW", 1_000)]
        series = fund_series_from_entries(entries, range_key="6m", today=self.TODAY)
        by_start = {row["period_start"]: row for row in series}
        assert by_start[date(2026, 7, 1)]["inflows_vnd"] == 1_000
        assert by_start[date(2026, 6, 1)]["inflows_vnd"] == 0

    def test_reversal_stays_in_its_own_bucket(self):
        entries = [
            (self._hcm(2026, 3, 5), "INFLOW", 5_000_000),
            (self._hcm(2026, 7, 2), "REVERSAL", -5_000_000),
        ]
        series = fund_series_from_entries(entries, range_key="6m", today=self.TODAY)
        by_start = {row["period_start"]: row for row in series}
        # March keeps its historical values; only July shows the reversal.
        assert by_start[date(2026, 3, 1)]["inflows_vnd"] == 5_000_000
        assert by_start[date(2026, 3, 1)]["outflows_vnd"] == 0
        assert by_start[date(2026, 7, 1)]["outflows_vnd"] == -5_000_000
        assert series[-1]["balance_vnd"] == 0


class FundSeriesIntegrationTests(TestCase):
    def test_verified_bar_and_last_point_match_fund_balance(self):
        from lamto.finance.fund import fund_balance
        from lamto.testing.factories import seed_pilot_world

        seed = seed_pilot_world(
            building_name="Series Building", email_prefix="fser",
            create_sample_report=False,
        )
        # An unverified direct row must not appear anywhere in the series.
        fund = MaintenanceFund.objects.get(building=seed.building)
        MaintenanceFundEntry.objects.create(
            fund=fund, entry_type="INFLOW", amount_vnd=999_999_999,
            source_key="series-unverified", recorded_at=timezone.now(),
        )
        for range_key in FUND_SERIES_RANGE_KEYS:
            series = fund_series(seed.building.pk, range_key=range_key)
            assert series[-1]["balance_vnd"] == fund_balance(
                seed.building.pk, verified_only=True
            )
            assert all(row["inflows_vnd"] < 999_999_999 for row in series)
```

Update the imports at the top of the file to:

```python
from datetime import date, datetime, timedelta
from datetime import timezone as dt_timezone

from django.test import TestCase
from django.utils import timezone

from lamto.accounts.models import Building
from lamto.finance.models import MaintenanceFund, MaintenanceFundEntry
from lamto.finance.selectors import (
    FUND_SERIES_RANGE_KEYS,
    fund_period_flows,
    fund_series,
    fund_series_from_entries,
    verified_fund_entries,
)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python manage.py test lamto.finance.tests.test_selectors -v 1`
Expected: FAIL / ERROR with `ImportError: cannot import name 'FUND_SERIES_RANGE_KEYS'`

- [ ] **Step 3: Implement the selector**

In `src/lamto/finance/selectors.py`, change the first import line to `from datetime import date, timedelta`, then add after `fund_period_flows`:

```python
FUND_SERIES_RANGE_KEYS = ("30d", "6m", "12m")


def fund_series_from_entries(entries, *, range_key, today):
    """Pure bucketing core for fund_series.

    entries iterates (recorded_at aware-datetime, entry_type, amount_vnd).
    Buckets by the Asia/Ho_Chi_Minh calendar day of recorded_at; amounts keep
    their stored sign (outflow-types negative), so balance is a plain sum.
    """
    if range_key not in FUND_SERIES_RANGE_KEYS:
        raise ValueError(f"range_key must be one of {FUND_SERIES_RANGE_KEYS}")
    if range_key == "30d":
        starts = [today - timedelta(days=offset) for offset in range(29, -1, -1)]

        def bucket_of(day):
            return day
    else:
        months = 6 if range_key == "6m" else 12
        year, month = today.year, today.month
        starts = []
        for _ in range(months):
            starts.append(date(year, month, 1))
            month -= 1
            if month == 0:
                year, month = year - 1, 12
        starts.reverse()

        def bucket_of(day):
            return day.replace(day=1)

    inflow_types = {
        MaintenanceFundEntry.EntryType.OPENING_BALANCE,
        MaintenanceFundEntry.EntryType.INFLOW,
    }
    window_start = starts[0]
    flows = {start: [0, 0] for start in starts}
    balance = 0  # seeded with everything before the window
    for recorded_at, entry_type, amount_vnd in entries:
        day = timezone.localtime(recorded_at).date()
        if day < window_start:
            balance += amount_vnd
            continue
        slot = flows.get(bucket_of(day))
        if slot is None:
            continue  # future-dated rows fall outside the chart window
        slot[0 if entry_type in inflow_types else 1] += amount_vnd
    series = []
    for start in starts:
        inflows, outflows = flows[start]
        balance += inflows + outflows
        series.append(
            {
                "period_start": start,
                "inflows_vnd": inflows,
                "outflows_vnd": outflows,
                "balance_vnd": balance,
            }
        )
    return series


def fund_series(building_id, *, range_key):
    """Chart rows for the fund pages (spec 2026-07-20-fund-balance-chart).

    Last point's balance_vnd equals fund_balance(verified_only=True).
    """
    rows = verified_fund_entries(building_id).values_list(
        "recorded_at", "entry_type", "amount_vnd"
    )
    # ponytail: Python-side bucketing; funds have few entries. Switch to
    # TruncDay/TruncMonth aggregates if a fund ever nears ~10k rows.
    return fund_series_from_entries(
        rows, range_key=range_key, today=timezone.localdate()
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python manage.py test lamto.finance.tests.test_selectors -v 1`
Expected: PASS (all, including the pre-existing tests)

- [ ] **Step 5: Commit**

```bash
git add src/lamto/finance/selectors.py src/lamto/finance/tests/test_selectors.py
git commit -m "feat(finance): add fund_series selector for balance chart"
```

---

### Task 2: `GET /api/v1/fund/series` endpoint

**Files:**
- Modify: `src/lamto/api/serializers.py` (after `FundSummarySerializer`, ~line 197)
- Modify: `src/lamto/api/views.py` (after `FundSummaryView`, ~line 429; plus imports)
- Modify: `src/lamto/api/urls.py` (after the `fund/summary` path)
- Modify: `src/lamto/api/tests/test_openapi.py` (route list in `test_schema_covers_every_api_route`)
- Modify: `docs/api/openapi-v1.yaml` (regenerated, not hand-edited)
- Test: `src/lamto/api/tests/test_fund.py` (append)

**Interfaces:**
- Consumes: `fund_series`, `FUND_SERIES_RANGE_KEYS` from `lamto.finance.selectors` (Task 1); existing `resolve_api_occupancy`, `problem_responses`, `OCCUPANCY_HEADER_PARAMETER`.
- Produces: route name `api:fund-series`; response body `{"range": "6m", "points": [{"period_start": "2026-02-01", "inflows_vnd": 0, "outflows_vnd": 0, "balance_vnd": 0}, ...]}`. OpenAPI components `FundSeries` / `FundSeriesPoint` (what the Dart client generates as model classes in Task 5). The `range` query param is a **plain string** in the schema (no `enum=`) so the generated Dart parameter is a `String`, not a mangled enum.

- [ ] **Step 1: Write the failing tests**

Append to `src/lamto/api/tests/test_fund.py` (reuse the module's existing `@override_settings(...)` block verbatim as the class decorator, same as `FundSummaryTests`):

```python
@override_settings(
    STORAGES={
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {"location": _TEMP_STORAGE},
        },
        "private": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {"location": _TEMP_STORAGE},
        },
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    }
)
class FundSeriesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.seed = seed_pilot_world(
            building_name="API Series Building",
            email_prefix="apis",
            create_sample_report=False,
        )
        cls.resident = cls.seed.users["resident"]

    def _auth(self):
        _instance, token = AuthToken.objects.create(user=self.resident)
        return {"authorization": f"Token {token}"}

    def test_default_range_shape_and_final_balance(self):
        response = self.client.get(reverse("api:fund-series"), headers=self._auth())
        assert response.status_code == 200, response.content
        body = response.json()
        assert body["range"] == "6m"
        assert len(body["points"]) == 6
        point = body["points"][-1]
        assert set(point) == {
            "period_start", "inflows_vnd", "outflows_vnd", "balance_vnd",
        }
        assert point["balance_vnd"] == fund_balance(
            self.seed.building.pk, verified_only=True
        )

    def test_each_range_bucket_count(self):
        for range_key, count in (("30d", 30), ("6m", 6), ("12m", 12)):
            response = self.client.get(
                reverse("api:fund-series"), {"range": range_key},
                headers=self._auth(),
            )
            assert response.status_code == 200
            assert len(response.json()["points"]) == count

    def test_invalid_range_is_400(self):
        response = self.client.get(
            reverse("api:fund-series"), {"range": "7d"}, headers=self._auth()
        )
        assert response.status_code == 400
        assert problem(response)["code"] == "validation_failed"

    def test_unauthenticated_is_401(self):
        assert self.client.get(reverse("api:fund-series")).status_code == 401
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python manage.py test lamto.api.tests.test_fund.FundSeriesTests -v 1`
Expected: ERROR with `NoReverseMatch: Reverse for 'fund-series' not found`

- [ ] **Step 3: Implement serializer, view, url**

`src/lamto/api/serializers.py`, after `FundSummarySerializer`:

```python
class FundSeriesPointSerializer(serializers.Serializer):
    period_start = serializers.DateField()
    inflows_vnd = serializers.IntegerField()
    outflows_vnd = serializers.IntegerField(
        help_text="Outflow-type amounts are stored negative; this is <= 0."
    )
    balance_vnd = serializers.IntegerField()


class FundSeriesSerializer(serializers.Serializer):
    range = serializers.ChoiceField(choices=("30d", "6m", "12m"))
    points = FundSeriesPointSerializer(many=True)
```

`src/lamto/api/views.py`:
- Add `FundSeriesSerializer` to the existing `from lamto.api.serializers import (...)` block (alphabetical, after `FundSummarySerializer`).
- Change the existing selectors import (~line 92) to include the new names:

```python
from lamto.finance.selectors import (
    FUND_SERIES_RANGE_KEYS,
    fund_period_flows,
    fund_series,
)
```

(Keep whatever else that block already imports.) Then add after `FundSummaryView`:

```python
class FundSeriesView(APIView):
    @extend_schema(
        parameters=[
            OCCUPANCY_HEADER_PARAMETER,
            OpenApiParameter(
                name="range",
                type=OpenApiTypes.STR,
                description="Chart range: 30d, 6m, or 12m. Defaults to 6m.",
            ),
        ],
        responses={
            200: FundSeriesSerializer,
            **problem_responses(400, 401, 403, 404, 422),
        },
    )
    def get(self, request):
        _occupancy, tenant = resolve_api_occupancy(request)
        range_key = request.query_params.get("range", "6m")
        if range_key not in FUND_SERIES_RANGE_KEYS:
            raise exceptions.ValidationError(
                {"range": f"must be one of {', '.join(FUND_SERIES_RANGE_KEYS)}"}
            )
        data = {
            "range": range_key,
            "points": fund_series(tenant.building_id, range_key=range_key),
        }
        return Response(FundSeriesSerializer(data).data)
```

`src/lamto/api/urls.py`, after the `fund/summary` line:

```python
    path("fund/series", views.FundSeriesView.as_view(), name="fund-series"),
```

`src/lamto/api/tests/test_openapi.py`: add `"/api/v1/fund/series",` to the route tuple in `test_schema_covers_every_api_route`, right after `"/api/v1/fund/summary",` (open the file; the tuple starts around line 35).

- [ ] **Step 4: Regenerate the OpenAPI schema (drift gate)**

```bash
.venv/bin/python manage.py spectacular --file docs/api/openapi-v1.yaml
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python manage.py test lamto.api.tests.test_fund lamto.api.tests.test_openapi -v 1`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/lamto/api/serializers.py src/lamto/api/views.py src/lamto/api/urls.py \
  src/lamto/api/tests/test_fund.py src/lamto/api/tests/test_openapi.py docs/api/openapi-v1.yaml
git commit -m "feat(api): add GET /fund/series balance-chart endpoint"
```

---

### Task 3: Staff fund page — full chart + window stats

**Files:**
- Create: `src/lamto/web/static/web/chart.umd.js` (vendored Chart.js 4)
- Create: `src/lamto/web/static/web/fund-chart.js`
- Modify: `src/lamto/web/views/fund.py` (`fund_home`, ~lines 27–86)
- Modify: `src/lamto/web/templates/web/staff/fund_detail.html` (after the stat-grid, ~line 26)
- Modify: `src/lamto/web/static/web/app.css` (append)
- Modify: `locale/vi/LC_MESSAGES/django.po` (+ recompile)
- Test: `src/lamto/web/tests/test_fund_ops.py` (extend `FundHomeTests`)

**Interfaces:**
- Consumes: `fund_series`, `FUND_SERIES_RANGE_KEYS` (Task 1).
- Produces: template context keys `chart_points` (list of dicts with ISO-string `period_start`), `chart_range`, `chart_ranges` (list of `(key, label)`), `window_opening_vnd`, `window_closing_vnd`, `window_inflows_vnd`, `window_outflows_vnd`; static files `web/chart.umd.js` + `web/fund-chart.js` and the `#fund-chart` / `#fund-chart-data` element contract — all reused verbatim by Task 4.

- [ ] **Step 1: Write the failing tests**

Add to `FundHomeTests` in `src/lamto/web/tests/test_fund_ops.py`:

```python
    def test_fund_home_renders_chart_and_window_stats(self):
        seed = seed_pilot_world(building_name="Fund Chart B", email_prefix="fch")
        self._login(seed, "fund_recorder")
        resp = self.client.get(reverse("web:fund-home"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'id="fund-chart-data"')
        self.assertContains(resp, "Opening balance")
        self.assertContains(resp, "Closing balance")
        self.assertContains(resp, "Total inflows")
        self.assertContains(resp, "Total outflows")
        self.assertEqual(resp.context["chart_range"], "6m")
        self.assertEqual(len(resp.context["chart_points"]), 6)
        # json_script payload uses ISO date strings.
        first = resp.context["chart_points"][0]
        self.assertIsInstance(first["period_start"], str)

    def test_fund_home_range_toggle_and_fallback(self):
        seed = seed_pilot_world(building_name="Fund Chart R", email_prefix="fcr")
        self._login(seed, "fund_recorder")
        resp = self.client.get(reverse("web:fund-home"), {"range": "30d"})
        self.assertEqual(len(resp.context["chart_points"]), 30)
        resp = self.client.get(reverse("web:fund-home"), {"range": "bogus"})
        self.assertEqual(resp.context["chart_range"], "6m")

    def test_fund_home_window_stats_reconcile(self):
        seed = seed_pilot_world(building_name="Fund Chart S", email_prefix="fcs")
        self._login(seed, "fund_recorder")
        ctx = self.client.get(reverse("web:fund-home")).context
        self.assertEqual(
            ctx["window_opening_vnd"]
            + ctx["window_inflows_vnd"]
            + ctx["window_outflows_vnd"],
            ctx["window_closing_vnd"],
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python manage.py test lamto.web.tests.test_fund_ops.FundHomeTests -v 1`
Expected: the three new tests FAIL (`chart_range` not in context / `fund-chart-data` not found); the two pre-existing tests still PASS.

- [ ] **Step 3: Vendor Chart.js**

```bash
curl -fsSL https://cdn.jsdelivr.net/npm/chart.js@4.4.9/dist/chart.umd.js \
  -o src/lamto/web/static/web/chart.umd.js
head -c 200 src/lamto/web/static/web/chart.umd.js   # sanity: JS, not an error page
```

- [ ] **Step 4: Implement view context**

In `src/lamto/web/views/fund.py`:
- Extend the selectors import block with `FUND_SERIES_RANGE_KEYS` and `fund_series`.
- Add near the top: `from django.utils.translation import gettext_lazy as _`.
- Add a module-level constant after the imports:

```python
FUND_CHART_RANGES = (
    ("30d", _("30 days")),
    ("6m", _("6 months")),
    ("12m", _("12 months")),
)
```

- In `fund_home`, before the `return render(...)`:

```python
    range_key = request.GET.get("range", "6m")
    if range_key not in FUND_SERIES_RANGE_KEYS:
        range_key = "6m"
    series = fund_series(building_id, range_key=range_key)
    window_inflows = sum(row["inflows_vnd"] for row in series)
    window_outflows = sum(row["outflows_vnd"] for row in series)
    window_closing = series[-1]["balance_vnd"]
    chart_points = [
        {**row, "period_start": row["period_start"].isoformat()} for row in series
    ]
```

- Add to the `staff_context(...)` kwargs:

```python
            chart_points=chart_points,
            chart_range=range_key,
            chart_ranges=FUND_CHART_RANGES,
            window_opening_vnd=window_closing - window_inflows - window_outflows,
            window_closing_vnd=window_closing,
            window_inflows_vnd=window_inflows,
            window_outflows_vnd=window_outflows,
```

- [ ] **Step 5: Implement template + chart script + CSS**

`src/lamto/web/templates/web/staff/fund_detail.html`:
- Change line 2 to `{% load i18n humanize static staff_extras %}`.
- Insert after the closing `</dl>` of the 30d stat-grid (~line 26):

```django
  <div class="workflow-section" aria-labelledby="fund-chart-heading">
    <div class="panel-header">
      <h2 id="fund-chart-heading">{% trans "Balance over time" %}</h2>
      <nav class="range-toggle" aria-label="{% trans 'Chart range' %}">
        {% for key, label in chart_ranges %}
        <a class="button {% if key == chart_range %}button-primary{% else %}button-secondary{% endif %}"
           {% if key == chart_range %}aria-current="true"{% endif %}
           href="?range={{ key }}">{{ label }}</a>
        {% endfor %}
      </nav>
    </div>
    <dl class="stat-grid">
      <div><dt>{% trans "Opening balance" %}</dt><dd>{{ window_opening_vnd|intcomma }} VND</dd></div>
      <div><dt>{% trans "Closing balance" %}</dt><dd>{{ window_closing_vnd|intcomma }} VND</dd></div>
      <div><dt>{% trans "Total inflows" %}</dt><dd>{{ window_inflows_vnd|intcomma }} VND</dd></div>
      <div><dt>{% trans "Total outflows" %}</dt><dd>{{ window_outflows_vnd|intcomma }} VND</dd></div>
    </dl>
    <div class="chart-box">
      <canvas id="fund-chart" role="img"
              aria-label="{% trans 'Fund balance chart' %}"
              data-label-balance="{% trans 'Balance' %}"
              data-label-inflows="{% trans 'Inflows' %}"
              data-label-outflows="{% trans 'Outflows' %}"></canvas>
    </div>
    {{ chart_points|json_script:"fund-chart-data" }}
  </div>
```

- Add at the end of the file (before any final `{% endblock %}` of content, as its own block):

```django
{% block extra_js %}
<script src="{% static 'web/chart.umd.js' %}"></script>
<script src="{% static 'web/fund-chart.js' %}"></script>
{% endblock %}
```

Create `src/lamto/web/static/web/fund-chart.js`:

```js
/* Renders #fund-chart from the #fund-chart-data json_script payload.
   data-compact="1" = balance line only (Action inbox card). */
(function () {
  "use strict";
  var dataEl = document.getElementById("fund-chart-data");
  var canvas = document.getElementById("fund-chart");
  if (!dataEl || !canvas || typeof Chart === "undefined") return;
  var points = JSON.parse(dataEl.textContent);
  if (!points.length) return;
  var compact = canvas.dataset.compact === "1";
  var vnd = function (v) { return Number(v).toLocaleString("vi-VN"); };
  var datasets = [
    {
      type: "line",
      label: canvas.dataset.labelBalance || "Balance",
      data: points.map(function (p) { return p.balance_vnd; }),
      borderColor: "#3f51b5",
      backgroundColor: "rgba(63, 81, 181, 0.12)",
      fill: true,
      tension: 0.2,
      pointRadius: compact ? 0 : 2,
      order: 0,
    },
  ];
  if (!compact) {
    datasets.push(
      {
        type: "bar",
        label: canvas.dataset.labelInflows || "Inflows",
        data: points.map(function (p) { return p.inflows_vnd; }),
        backgroundColor: "rgba(46, 125, 50, 0.6)",
        order: 1,
      },
      {
        type: "bar",
        label: canvas.dataset.labelOutflows || "Outflows",
        data: points.map(function (p) { return p.outflows_vnd; }),
        backgroundColor: "rgba(198, 40, 40, 0.6)",
        order: 1,
      }
    );
  }
  new Chart(canvas, {
    data: {
      labels: points.map(function (p) { return p.period_start; }),
      datasets: datasets,
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      scales: {
        x: { ticks: { display: !compact } },
        y: { ticks: { callback: vnd } },
      },
      plugins: {
        legend: { display: !compact },
        tooltip: {
          callbacks: {
            label: function (ctx) {
              return ctx.dataset.label + ": " + vnd(ctx.parsed.y) + " VND";
            },
          },
        },
      },
    },
  });
})();
```

Append to `src/lamto/web/static/web/app.css`:

```css
/* Fund balance chart (staff fund page + action inbox card) */
.chart-box { position: relative; height: 260px; }
.chart-box-compact { height: 140px; }
.range-toggle { display: flex; gap: 8px; }
a.fund-chart-link { display: block; color: inherit; text-decoration: none; }
```

- [ ] **Step 6: Vietnamese translations**

```bash
.venv/bin/python manage.py makemessages -l vi
```

In `locale/vi/LC_MESSAGES/django.po`, fill the new msgids (leave existing entries untouched):

| msgid | msgstr |
|---|---|
| Balance over time | Số dư theo thời gian |
| Chart range | Khoảng thời gian biểu đồ |
| Opening balance* | Số dư đầu kỳ |
| Closing balance | Số dư cuối kỳ |
| Total inflows | Tổng thu |
| Total outflows | Tổng chi |
| Fund balance chart | Biểu đồ số dư quỹ |
| Balance | Số dư |
| Inflows | Thu |
| Outflows | Chi |
| 30 days | 30 ngày |
| 6 months | 6 tháng |
| 12 months | 12 tháng |

\* "Opening balance" may already exist (it is a `MaintenanceFundEntry.EntryType` label); if the msgid is already translated, keep it. Then:

```bash
.venv/bin/python manage.py compilemessages -l vi
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `.venv/bin/python manage.py test lamto.web.tests.test_fund_ops.FundHomeTests lamto.web.tests.test_staff_ui -v 1`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add src/lamto/web/views/fund.py src/lamto/web/templates/web/staff/fund_detail.html \
  src/lamto/web/static/web/chart.umd.js src/lamto/web/static/web/fund-chart.js \
  src/lamto/web/static/web/app.css src/lamto/web/tests/test_fund_ops.py locale/
git commit -m "feat(staff): fund page balance chart with range toggle and window stats"
```

---

### Task 4: Staff Action inbox — compact chart card

**Files:**
- Modify: `src/lamto/web/views/staff_common.py` (`action_inbox`, ~lines 164–205; plus imports)
- Modify: `src/lamto/web/templates/web/staff/action_inbox.html`
- Test: `src/lamto/web/tests/test_fund_ops.py` (append a new class)

**Interfaces:**
- Consumes: `fund_series` (Task 1); static files and the `#fund-chart` / `#fund-chart-data` contract from Task 3 (`data-compact="1"` renders line-only).
- Produces: context keys `fund_chart_points`, `fund_balance_vnd`, `fund_link_ok` on the action-inbox response.

- [ ] **Step 1: Write the failing tests**

Append to `src/lamto/web/tests/test_fund_ops.py` (reuse the module's `@override_settings` block verbatim, same as `FundHomeTests`):

```python
@override_settings(
    ROOT_URLCONF="lamto.config.urls",
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"location": _TEMP}},
        "private": {"BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"location": _TEMP}},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    },
)
class ActionInboxChartTests(TestCase):
    def _login(self, seed, role_key):
        membership = seed.roles[role_key]
        self.client.force_login(membership.user)
        device = TOTPDevice.objects.create(
            user=membership.user, name="t", confirmed=True, key=random_hex()
        )
        session = self.client.session
        session[DEVICE_ID_SESSION_KEY] = device.persistent_id
        session[RECENT_REAUTH_KEY] = time.time()
        session["active_membership_id"] = membership.pk
        session.save()
        return membership

    def test_inbox_shows_compact_chart_with_fund_link_for_fund_staff(self):
        seed = seed_pilot_world(building_name="Inbox Chart B", email_prefix="ich")
        self._login(seed, "fund_recorder")
        resp = self.client.get(reverse("web:action-inbox"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'id="fund-chart-data"')
        self.assertContains(resp, 'data-compact="1"')
        self.assertContains(resp, reverse("web:fund-home"))
        self.assertEqual(len(resp.context["fund_chart_points"]), 6)
        self.assertTrue(resp.context["fund_link_ok"])

    def test_inbox_chart_without_fund_capability_has_no_fund_link(self):
        seed = seed_pilot_world(building_name="Inbox Chart D", email_prefix="icd")
        self._login(seed, "maintenance")
        resp = self.client.get(reverse("web:action-inbox"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'id="fund-chart-data"')
        self.assertNotContains(resp, reverse("web:fund-home"))
        self.assertFalse(resp.context["fund_link_ok"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python manage.py test lamto.web.tests.test_fund_ops.ActionInboxChartTests -v 1`
Expected: FAIL (`fund-chart-data` not found / `fund_chart_points` not in context)

- [ ] **Step 3: Implement view context**

In `src/lamto/web/views/staff_common.py`:
- Add imports (merge into existing import lines if the modules are already imported):

```python
from lamto.accounts.capabilities import FUND_RECORD, FUND_VERIFY
from lamto.finance.selectors import fund_series
```

(`capabilities_for` is defined in `lamto.web.staff`; the module already imports from there — extend that import if `capabilities_for` isn't imported yet.)

- In `action_inbox`, after `membership, memberships = resolve_active_membership(request)`:

```python
    caps = capabilities_for(membership)
    series = fund_series(membership.organization.building_id, range_key="6m")
```

- Add to the `staff_context(...)` kwargs:

```python
            fund_chart_points=[
                {**row, "period_start": row["period_start"].isoformat()}
                for row in series
            ],
            fund_balance_vnd=series[-1]["balance_vnd"],
            fund_link_ok=FUND_RECORD in caps or FUND_VERIFY in caps,
```

- [ ] **Step 4: Implement template**

In `src/lamto/web/templates/web/staff/action_inbox.html`:
- Change line 2 to `{% load i18n humanize static staff_extras %}`.
- Insert immediately after `{% block content %}` (line 4), before the inbox `<section class="panel" ...>`:

```django
<section class="panel" aria-labelledby="fund-chart-card-heading">
  {% if fund_link_ok %}<a class="fund-chart-link" href="{% url 'web:fund-home' %}">{% endif %}
    <div class="panel-header">
      <div>
        <h2 id="fund-chart-card-heading">{% trans "Maintenance fund" %}</h2>
        <p class="balance-value">
          <span class="amount">{{ fund_balance_vnd|intcomma }}</span>
          <span class="currency">VND</span>
        </p>
      </div>
    </div>
    <div class="chart-box chart-box-compact">
      <canvas id="fund-chart" role="img" data-compact="1"
              aria-label="{% trans 'Fund balance chart' %}"
              data-label-balance="{% trans 'Balance' %}"></canvas>
    </div>
  {% if fund_link_ok %}</a>{% endif %}
  {{ fund_chart_points|json_script:"fund-chart-data" }}
</section>
```

- Add at the end of the file:

```django
{% block extra_js %}
<script src="{% static 'web/chart.umd.js' %}"></script>
<script src="{% static 'web/fund-chart.js' %}"></script>
{% endblock %}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python manage.py test lamto.web.tests.test_fund_ops.ActionInboxChartTests lamto.web.tests.test_staff_ui.ActionInboxUiTests -v 1`
Expected: PASS. ("Maintenance fund" already has a vi translation from the fund page; no new msgids here — if `makemessages` was rerun and added none, nothing to do.)

- [ ] **Step 6: Commit**

```bash
git add src/lamto/web/views/staff_common.py \
  src/lamto/web/templates/web/staff/action_inbox.html src/lamto/web/tests/test_fund_ops.py
git commit -m "feat(staff): compact fund chart card on action inbox"
```

---

### Task 5: Flutter plumbing — client regen, fl_chart, repository + provider

**Files:**
- Modify: `docs/api/openapi-v1.yaml` consumers — regenerate `app/packages/lamto_api/` (whole directory, generated)
- Modify: `app/pubspec.yaml` (add `fl_chart`)
- Modify: `app/lib/features/transparency/transparency_repository.dart`
- Modify: `app/test/transparency_repository_contract_test.dart`

**Interfaces:**
- Consumes: `/api/v1/fund/series` from Task 2 (already in `docs/api/openapi-v1.yaml`).
- Produces: generated models `FundSeries` (`.range: String`, `.points: BuiltList<FundSeriesPoint>`) and `FundSeriesPoint` (`.periodStart: DateTime`, `.inflowsVnd/.outflowsVnd/.balanceVnd: int`); `TransparencyApiPaths.fundSeries`; `TransparencyRepository.fetchFundSeries({String range})`; `fundSeriesProvider` — a `FutureProvider.autoDispose.family<FundSeries, String>` keyed by range string (`'30d' | '6m' | '12m'`); `fundSeriesRanges` const list. Tasks 6–7 consume these exact names.

- [ ] **Step 1: Regenerate the Dart client and add fl_chart**

```bash
cd app
bash tool/generate_api.sh      # needs java or docker; regenerates packages/lamto_api
```

Then in `app/pubspec.yaml` add under `dependencies:` (after `built_collection`):

```yaml
  fl_chart: ^1.1.0
```

```bash
flutter pub get
```

Verify the generated surface: open `app/packages/lamto_api/doc/FundApi.md` — it must list a `fundSeriesRetrieve` method with a `String range` parameter and a `FundSeries` return model. If the generator named it differently (e.g. different casing), use the documented name in Step 3.

- [ ] **Step 2: Extend the contract test (fails until Step 3 compiles)**

In `app/test/transparency_repository_contract_test.dart`, add `TransparencyApiPaths.fundSeries,` to the list of checked constants directly after `TransparencyApiPaths.fundSummary,` (~line 44).

Run: `flutter test test/transparency_repository_contract_test.dart`
Expected: COMPILE ERROR — `fundSeries` isn't defined yet.

- [ ] **Step 3: Implement repository + provider**

In `app/lib/features/transparency/transparency_repository.dart`:

- Add to `TransparencyApiPaths` after `fundSummary`:

```dart
  static const fundSeries = '/api/v1/fund/series';
```

- Add to the `TransparencyRepository` abstract class after `fetchFundSummary`:

```dart
  Future<FundSeries> fetchFundSeries({String range});
```

- Add to `DioTransparencyRepository` after `fetchFundSummary`:

```dart
  @override
  Future<FundSeries> fetchFundSeries({String range = '6m'}) async {
    final res = await _fund.fundSeriesRetrieve(range: range);
    return res.data!;
  }
```

- Add after `fundSummaryProvider` at the bottom of the file:

```dart
/// Ranges accepted by /fund/series, in display order.
const fundSeriesRanges = ['30d', '6m', '12m'];

/// Chart series keyed by range; building-scoped like fundSummaryProvider.
final fundSeriesProvider = FutureProvider.autoDispose
    .family<FundSeries, String>((ref, range) {
      ref.watch(occupancyScopedProviders);
      return ref
          .watch(transparencyRepositoryProvider)
          .fetchFundSeries(range: range);
    });
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
flutter analyze lib test
flutter test test/transparency_repository_contract_test.dart test/transparency_repository_test.dart
```

Expected: analyze clean for the touched files; contract test PASS. If `transparency_repository_test.dart` has a fake implementing `TransparencyRepository`, the compiler will force a `fetchFundSeries` override there — add a throwing or fixed-value override following that file's existing fake style (`noSuchMethod` fakes need no change).

- [ ] **Step 5: Commit**

```bash
git add app/packages/lamto_api app/pubspec.yaml app/pubspec.lock \
  app/lib/features/transparency/transparency_repository.dart \
  app/test/transparency_repository_contract_test.dart app/test/transparency_repository_test.dart
git commit -m "feat(app): fund series client, fl_chart dependency, provider"
```

---

### Task 6: Flutter chart widget + Home card + shell tab hop

**Files:**
- Create: `app/lib/features/transparency/fund_chart.dart`
- Modify: `app/lib/features/shell/home_shell.dart`
- Modify: `app/lib/features/home/home_screen.dart` (`_fundBlock`, ~lines 110–160)
- Modify: `app/lib/l10n/app_en.arb`, `app/lib/l10n/app_vi.arb`
- Test: `app/test/home_screen_test.dart`

**Interfaces:**
- Consumes: `fundSeriesProvider`, `fundSeriesRanges`, `FundSeries`/`FundSeriesPoint` (Task 5); existing `ErrorRetry(error:, onRetry:)`.
- Produces: `FundChart({required String range, bool compact = false, VoidCallback? onTap})` widget; `shellTabProvider` (`StateProvider<int>`) and `ledgerTabIndex` const in `home_shell.dart`. Task 7 reuses `FundChart` (non-compact).

- [ ] **Step 1: Add l10n strings**

`app/lib/l10n/app_en.arb` — add:

```json
  "fundChartTitle": "Fund balance",
  "fundChartFlowsTitle": "Inflows and outflows",
  "fundChartSemantics": "Fund balance chart",
  "fundChartRange30d": "30 days",
  "fundChartRange6m": "6 months",
  "fundChartRange12m": "12 months",
```

`app/lib/l10n/app_vi.arb` — add:

```json
  "fundChartTitle": "Số dư quỹ",
  "fundChartFlowsTitle": "Thu và chi",
  "fundChartSemantics": "Biểu đồ số dư quỹ",
  "fundChartRange30d": "30 ngày",
  "fundChartRange6m": "6 tháng",
  "fundChartRange12m": "12 tháng",
```

Run: `cd app && flutter gen-l10n`

- [ ] **Step 2: Write the failing widget tests**

In `app/test/home_screen_test.dart`:

- Add a series fixture next to `_fund()`:

```dart
FundSeries _series(String range) => FundSeries(
  (b) => b
    ..range = range
    ..points = ListBuilder<FundSeriesPoint>([
      for (var i = 0; i < 6; i++)
        FundSeriesPoint(
          (p) => p
            ..periodStart = DateTime.utc(2026, 2 + i, 1)
            ..inflowsVnd = i == 2 ? 200000 : 0
            ..outflowsVnd = i == 4 ? -50000 : 0
            ..balanceVnd = 1500000 + i * 10000,
        ),
    ]),
);
```

- In `_FakeTransparency`, add:

```dart
  @override
  Future<FundSeries> fetchFundSeries({String range = '6m'}) async =>
      _series(range);
```

- Add a throwing variant next to the existing throwing fakes:

```dart
/// Series throws; summary still succeeds — chart must show retry, balance stays.
class _ThrowingSeriesTransparency extends _FakeTransparency {
  @override
  Future<FundSeries> fetchFundSeries({String range = '6m'}) async {
    throw Exception('series down');
  }
}
```

- Add tests (follow the file's existing pump helper/harness):

```dart
  testWidgets('home renders fund chart card', (tester) async {
    // ...pump HomeScreen with _FakeTransparency via the file's harness...
    await tester.pumpAndSettle();
    expect(find.byType(FundChart), findsOneWidget);
    expect(find.byType(LineChart), findsOneWidget);
  });

  testWidgets('series failure shows retry but keeps balance', (tester) async {
    // ...pump with _ThrowingSeriesTransparency...
    await tester.pumpAndSettle();
    expect(find.text(formatVnd(1500000)), findsOneWidget); // summary balance
    expect(find.byType(ErrorRetry), findsWidgets); // chart error state
    expect(find.byType(LineChart), findsNothing);
  });

  testWidgets('tapping home chart switches shell tab to ledger', (tester) async {
    // ...pump with _FakeTransparency inside a ProviderScope you keep a
    // ProviderContainer reference to (UncontrolledProviderScope)...
    await tester.pumpAndSettle();
    await tester.tap(find.byType(FundChart), warnIfMissed: false);
    expect(container.read(shellTabProvider), ledgerTabIndex);
  });
```

Imports to add at top: `package:fl_chart/fl_chart.dart`, `package:lamto/features/transparency/fund_chart.dart`, `package:lamto/features/shell/home_shell.dart`, `package:lamto/core/error_retry.dart`, `package:lamto/core/format.dart`.

Run: `flutter test test/home_screen_test.dart`
Expected: COMPILE ERROR (`FundChart`, `shellTabProvider` undefined).

- [ ] **Step 3: Implement `FundChart`**

Create `app/lib/features/transparency/fund_chart.dart`:

```dart
import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';
import 'package:lamto_api/lamto_api.dart';

import '../../core/error_retry.dart';
import '../../l10n/app_localizations.dart';
import 'transparency_repository.dart';

/// Verified fund-balance chart (spec 2026-07-20-fund-balance-chart).
/// compact: balance line only (Home card). Full: line + in/out bars (Sổ quỹ).
class FundChart extends ConsumerWidget {
  const FundChart({
    super.key,
    required this.range,
    this.compact = false,
    this.onTap,
  });

  final String range;
  final bool compact;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = AppLocalizations.of(context)!;
    final series = ref.watch(fundSeriesProvider(range));
    return switch (series) {
      AsyncData(:final value) => Semantics(
        label: l10n.fundChartSemantics,
        child: _chart(context, l10n, value),
      ),
      AsyncError(:final error) => ErrorRetry(
        error: error,
        onRetry: () => ref.invalidate(fundSeriesProvider(range)),
      ),
      _ => const SizedBox(
        height: 160,
        child: Center(child: CircularProgressIndicator.adaptive()),
      ),
    };
  }

  Widget _chart(BuildContext context, AppLocalizations l10n, FundSeries series) {
    final points = series.points.toList();
    if (points.isEmpty) return const SizedBox.shrink();
    final line = _balanceLine(context, points);
    if (compact) {
      return GestureDetector(
        onTap: onTap,
        child: SizedBox(height: 140, child: line),
      );
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SizedBox(height: 180, child: line),
        const SizedBox(height: 16),
        Text(
          l10n.fundChartFlowsTitle,
          style: Theme.of(context).textTheme.titleSmall,
        ),
        const SizedBox(height: 8),
        SizedBox(height: 120, child: _flowsBars(context, points)),
      ],
    );
  }

  Widget _balanceLine(BuildContext context, List<FundSeriesPoint> points) {
    final scheme = Theme.of(context).colorScheme;
    return LineChart(
      LineChartData(
        gridData: const FlGridData(show: false),
        borderData: FlBorderData(show: false),
        titlesData: FlTitlesData(
          leftTitles: const AxisTitles(),
          topTitles: const AxisTitles(),
          rightTitles: const AxisTitles(),
          bottomTitles: AxisTitles(
            sideTitles: SideTitles(
              showTitles: !compact,
              interval: (points.length / 6).ceilToDouble(),
              getTitlesWidget: (value, meta) =>
                  _periodLabel(context, points, value),
            ),
          ),
        ),
        lineTouchData: LineTouchData(enabled: !compact),
        lineBarsData: [
          LineChartBarData(
            spots: [
              for (var i = 0; i < points.length; i++)
                FlSpot(i.toDouble(), points[i].balanceVnd!.toDouble()),
            ],
            isCurved: false,
            color: scheme.primary,
            dotData: const FlDotData(show: false),
            belowBarData: BarAreaData(
              show: true,
              color: scheme.primary.withValues(alpha: 0.12),
            ),
          ),
        ],
      ),
    );
  }

  Widget _flowsBars(BuildContext context, List<FundSeriesPoint> points) {
    final scheme = Theme.of(context).colorScheme;
    return BarChart(
      BarChartData(
        gridData: const FlGridData(show: false),
        borderData: FlBorderData(show: false),
        titlesData: const FlTitlesData(
          leftTitles: AxisTitles(),
          topTitles: AxisTitles(),
          rightTitles: AxisTitles(),
          bottomTitles: AxisTitles(),
        ),
        barGroups: [
          for (var i = 0; i < points.length; i++)
            BarChartGroupData(
              x: i,
              barRods: [
                BarChartRodData(
                  toY: points[i].inflowsVnd!.toDouble(),
                  color: Colors.green.shade700,
                  width: 6,
                ),
                BarChartRodData(
                  toY: points[i].outflowsVnd!.toDouble(),
                  color: scheme.error,
                  width: 6,
                ),
              ],
            ),
        ],
      ),
    );
  }

  Widget _periodLabel(
    BuildContext context,
    List<FundSeriesPoint> points,
    double value,
  ) {
    final i = value.toInt();
    if (i < 0 || i >= points.length) return const SizedBox.shrink();
    final start = points[i].periodStart!;
    final label = range == '30d'
        ? DateFormat('d/M').format(start)
        : DateFormat('M/yy').format(start);
    return Padding(
      padding: const EdgeInsets.only(top: 4),
      child: Text(label, style: Theme.of(context).textTheme.labelSmall),
    );
  }
}
```

Note: generated built_value getters may be non-nullable depending on the schema (`required` fields); if the analyzer flags `!` on `balanceVnd` etc. as unnecessary, drop the `!`.

- [ ] **Step 4: Implement shell tab provider**

In `app/lib/features/shell/home_shell.dart`:

- Add imports: `package:flutter_riverpod/flutter_riverpod.dart`.
- Add above `class HomeShell`:

```dart
/// Cross-tab navigation target (e.g. Home fund chart → Sổ quỹ).
final shellTabProvider = StateProvider<int>((_) => 0);

/// Index of LedgerScreen in the shell's tab list.
const ledgerTabIndex = 2;
```

- Convert `HomeShell` to `ConsumerStatefulWidget` and `_HomeShellState` to `ConsumerState<HomeShell>` (`createState() => _HomeShellState();` stays).
- In `initState`, after creating `_cupertinoController`, keep tab taps in sync:

```dart
    _cupertinoController.addListener(() {
      ref.read(shellTabProvider.notifier).state = _cupertinoController.index;
    });
```

- At the top of `build`, sync provider → UI:

```dart
    ref.listen<int>(shellTabProvider, (_, next) {
      if (_index != next) setState(() => _index = next);
      if (_cupertinoController.index != next) {
        _cupertinoController.index = next;
      }
    });
```

- In every `onDestinationSelected: (i) => setState(() => _index = i)` (two occurrences), change to:

```dart
    onDestinationSelected: (i) {
      ref.read(shellTabProvider.notifier).state = i;
      setState(() => _index = i);
    },
```

- [ ] **Step 5: Wire the Home card**

In `app/lib/features/home/home_screen.dart`:
- Add imports: `../shell/home_shell.dart`, `../transparency/fund_chart.dart`.
- `_fundBlock` needs `ref`: change its signature to `Widget _fundBlock(BuildContext context, WidgetRef ref, AppLocalizations l10n, FundSummary fund)` and the call site to `_fundBlock(context, ref, l10n, value)`.
- In `_fundBlock`, append to the `Column` children after the inflow/outflow row/column:

```dart
        const SizedBox(height: 16),
        FundChart(
          range: '6m',
          compact: true,
          onTap: () =>
              ref.read(shellTabProvider.notifier).state = ledgerTabIndex,
        ),
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
flutter analyze lib test
flutter test test/home_screen_test.dart test/app_routing_test.dart test/app_entry_smoke_test.dart
```

Expected: PASS (routing/smoke tests exercise the converted shell).

- [ ] **Step 7: Commit**

```bash
git add app/lib/features/transparency/fund_chart.dart app/lib/features/shell/home_shell.dart \
  app/lib/features/home/home_screen.dart app/lib/l10n app/test/home_screen_test.dart
git commit -m "feat(app): fund balance chart card on Home with ledger-tab hop"
```

---

### Task 7: Flutter Sổ quỹ tab — full chart with range selector

**Files:**
- Modify: `app/lib/features/ledger/ledger_screen.dart`
- Test: `app/test/ledger_screens_test.dart`

**Interfaces:**
- Consumes: `FundChart` (Task 6), `fundSeriesProvider`, `fundSeriesRanges` (Task 5).
- Produces: `fundChartRangeProvider` (`StateProvider<String>`, default `'6m'`) in `ledger_screen.dart`.

- [ ] **Step 1: Write the failing widget tests**

In `app/test/ledger_screens_test.dart`, extend the file's transparency fake with the same `fetchFundSeries` override and `_series(range)` fixture as Task 6 Step 2 (copy the fixture into this file — tests must stay self-contained), then add:

```dart
  testWidgets('ledger tab shows full fund chart with range selector',
      (tester) async {
    // ...pump LedgerScreen via the file's existing harness...
    await tester.pumpAndSettle();
    expect(find.byType(FundChart), findsOneWidget);
    expect(find.byType(LineChart), findsOneWidget);
    expect(find.byType(BarChart), findsOneWidget);
    expect(find.byType(SegmentedButton<String>), findsOneWidget);
  });

  testWidgets('range selector switches the series', (tester) async {
    // ...pump with a ProviderContainer reference...
    await tester.pumpAndSettle();
    await tester.tap(find.text('30 days'));
    await tester.pumpAndSettle();
    expect(container.read(fundChartRangeProvider), '30d');
  });
```

(If the harness pumps with a Vietnamese locale, tap `find.text('30 ngày')` instead — match the file's locale setup.)

Run: `flutter test test/ledger_screens_test.dart`
Expected: COMPILE ERROR (`fundChartRangeProvider` undefined) or FAIL.

- [ ] **Step 2: Implement the chart header**

In `app/lib/features/ledger/ledger_screen.dart`:

- Add import: `../transparency/fund_chart.dart`.
- Add near the top of the file, after the existing providers:

```dart
/// Selected chart range on the Sổ quỹ tab; survives tab switches.
final fundChartRangeProvider = StateProvider<String>((_) => '6m');
```

- Locate the widget that builds the scrollable ledger list (below the period chips setup) and insert a chart header as the first content above the entry list — inside whatever `ListView`/`Column` renders the screen body:

```dart
    final chartRange = ref.watch(fundChartRangeProvider);
    String rangeLabel(String key) => switch (key) {
      '30d' => l10n.fundChartRange30d,
      '12m' => l10n.fundChartRange12m,
      _ => l10n.fundChartRange6m,
    };
```

```dart
    Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          l10n.fundChartTitle,
          style: Theme.of(context).textTheme.titleMedium,
        ),
        const SizedBox(height: 8),
        SegmentedButton<String>(
          segments: [
            for (final key in fundSeriesRanges)
              ButtonSegment(value: key, label: Text(rangeLabel(key))),
          ],
          selected: {chartRange},
          showSelectedIcon: false,
          onSelectionChanged: (selection) => ref
              .read(fundChartRangeProvider.notifier)
              .state = selection.first,
        ),
        const SizedBox(height: 12),
        FundChart(range: chartRange),
        const SizedBox(height: 24),
      ],
    ),
```

Match the screen's existing structure: if the list is a `ListView`, add this `Column` as the first child; if it is a `CustomScrollView`, wrap it in a `SliverToBoxAdapter` as the first sliver. Do not change the list/pagination behavior below it.

- [ ] **Step 3: Run tests to verify they pass**

```bash
flutter analyze lib test
flutter test test/ledger_screens_test.dart
flutter test
```

Expected: all app tests PASS.

- [ ] **Step 4: Full backend regression + commit**

```bash
.venv/bin/python manage.py test lamto -v 1
git add app/lib/features/ledger/ledger_screen.dart app/test/ledger_screens_test.dart
git commit -m "feat(app): full fund chart with range selector on ledger tab"
```
