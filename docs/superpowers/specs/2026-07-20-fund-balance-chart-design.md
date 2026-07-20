# Fund balance chart — design

Date: 2026-07-20
Status: approved architecture, pending final spec review

## Goal

Show a fund balance chart in two places:

- **Resident app** (Flutter): a compact chart on the Home tab under the existing
  fund balance block, and a full chart on the Sổ quỹ (ledger) tab.
- **Staff site** (Django): a compact chart on the Action inbox (`s/inbox/`)
  that links to the fund page (`s/fund/`), which carries the full chart.

The chart shows the **verified fund balance over time** (line) plus
**inflows/outflows per bucket** (bars), over a user-selectable range.

## Architecture (approved)

One backend selector → one JSON API endpoint for the app → the same selector
called directly by the staff views. Chart.js (vendored static file) renders on
the staff site; `fl_chart` renders in the Flutter app.

## Backend

### Selector

`fund_series(building_id, *, range_key)` in `src/lamto/finance/selectors.py`.

- `range_key` is one of `"30d"`, `"6m"`, `"12m"`. The selector maps it to the
  date window and bucket size internally; callers never pass days/bucket
  separately.
- Returns an ordered list of rows:
  `{period_start: date, inflows_vnd: int, outflows_vnd: int, balance_vnd: int}`.
- Source data: `verified_fund_entries(building_id)` — the same
  verified/finalized bar as `fund_balance(verified_only=True)`. Entries are
  bucketed by `recorded_at`.
- `balance_vnd` is a running total: seeded with the verified balance of all
  entries **before** the window start, then accumulated bucket by bucket. The
  last bucket's `balance_vnd` therefore always equals
  `fund_balance(building_id, verified_only=True)`.
- Entry-type mapping matches `fund_period_flows`: `OPENING_BALANCE` and
  `INFLOW` count as inflows; `OUTFLOW`, `REVERSAL`, and `REPLACEMENT` count as
  outflows.
- Empty buckets are filled in (zero flows, carried-forward balance) so the
  series has no gaps.

### Time-range and timezone rules

All bucketing uses the project timezone, `Asia/Ho_Chi_Minh` (Django
`TIME_ZONE`; `USE_TZ=True` so stored timestamps are UTC and are converted
before bucketing). There is no per-building timezone; if one is ever added,
this selector is the single place to honor it.

- `30d`: daily buckets — today plus the previous 29 days (30 daily buckets;
  "today" per `Asia/Ho_Chi_Minh`).
- `6m`: monthly buckets — the current calendar month plus the previous
  5 months (6 monthly buckets).
- `12m`: monthly buckets — the current calendar month plus the previous
  11 months (12 monthly buckets).
- `period_start` is the bucket's first day (the day itself for daily buckets,
  the first of the month for monthly buckets), as a date in
  `Asia/Ho_Chi_Minh`.

### Reversals and corrections

The series reflects the ledger as recorded. A reversal or correction appears
as its own entry in the bucket of **its own** `recorded_at` — the system must
**not** rewrite the flows or balance of the historical bucket that contained
the original entry. Past buckets are immutable once their period has ended;
only the append-only ledger semantics drive the chart.

### API endpoint

`GET /fund/series?range=30d|6m|12m` (default `6m`), added next to the existing
`fund/summary` route in `src/lamto/api/urls.py`.

- Resolves the building via `resolve_api_occupancy` like `FundSummaryView`.
- Response, via a new `FundSeriesSerializer` with `extend_schema` annotations:

  ```json
  {
    "range": "6m",
    "points": [
      {"period_start": "2026-02-01", "inflows_vnd": 0,
       "outflows_vnd": 0, "balance_vnd": 80000000},
      ...
    ]
  }
  ```

- Invalid `range` → 422 problem response, consistent with the rest of the API.
- The generated Dart client (`app/packages/lamto_api`, OpenAPI Generator) is
  regenerated to pick up the endpoint.

## Staff site

- **Action inbox** (`staff_common.action_inbox`): a compact card above the
  task list — balance line only, fixed `6m` range, current balance figure.
  The whole card is a link to `s/fund/`.
- **Fund page** (`fund.fund_home` / `fund_detail.html`): the full chart —
  balance line + inflow/outflow bars — with a 30d / 6m / 12m toggle rendered
  as plain links (`?range=`, server round-trip, no client state). Invalid or
  missing `range` falls back to `6m`.
- Above the full chart, the fund page also shows as text:
  **opening balance** (balance at the start of the window, i.e. the seed),
  **closing balance** (last point), **total inflows**, and **total outflows**
  for the selected range. These are derived from the same `fund_series`
  result — no separate query.
- Rendering: Chart.js vendored as one file under
  `src/lamto/web/static/web/`, initialized from a `{{ series|json_script }}`
  block. The views call `fund_series` directly; the browser makes no extra
  HTTP call.

## Resident app

- Add `fl_chart` to `app/pubspec.yaml`.
- New `fundSeriesProvider` (Riverpod, family-by-range or a range
  `StateProvider` + one provider — follow the existing `fundSummaryProvider`
  pattern) calling the new endpoint through the regenerated `lamto_api`
  client.
- **Home tab**: chart card inside `_fundBlock` under the balance/stat area —
  balance line only, fixed `6m` range. Tapping navigates to the Sổ quỹ tab.
- **Sổ quỹ tab**: full chart at the top — line + bars — with a 30d / 6m / 12m
  segmented-button selector.
- **Error state**: if the series fails to load, do **not** silently hide the
  chart. Show a small inline error state with a retry action
  (`ref.invalidate` on the series provider), while the balance header from
  the summary endpoint keeps rendering as it does today. The same rule
  applies on the Sổ quỹ tab.
- Loading state: the existing async placeholder pattern used by
  `fundSummaryProvider` consumers.
- All new strings go through `l10n` (vi + en).

## Testing

- **Selector** (`finance/tests/test_selectors.py`): bucket boundaries per
  range key in `Asia/Ho_Chi_Minh` (including a UTC-vs-local edge near
  midnight and a month boundary), running balance seed + last point equals
  `fund_balance`, empty-bucket fill, unverified entries excluded, reversal
  recorded in a later bucket leaves earlier buckets unchanged.
- **API** (`api/tests/test_fund.py`): response shape, default range, invalid
  range → 422, occupancy scoping.
- **Staff UI** (`web/tests/test_staff_ui.py`): series JSON present on inbox
  and fund page, range toggle changes the series, opening/closing/totals text
  present on the fund page.
- **Flutter**: widget test for the home chart card from a stubbed provider,
  including the error-with-retry state.

## Out of scope

- Per-building timezones (single hook point noted above).
- Unverified/pending entries in the chart.
- Export/download of the series.
