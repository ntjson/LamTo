## Task 3 Report

### Status

Implemented decline reason presentation, private report composition/persistence/submission, private list badges, and distinct localized labels/tones for all eight report statuses. No generated API client files were edited or regenerated.

### Changes

- Added a labeled decline card on report detail when `declinedReason` is present.
- Suppressed the rating CTA for declined reports, even if stale case data says the case is rateable.
- Added an adaptive private-request switch below the location picker with English and Vietnamese explanatory copy.
- Persisted `is_private` in `ReportDraft`, defaulting missing values to `false` for existing saved drafts.
- Forwarded privacy through `ReportSubmitter`, `ReportsRepository.createReport`, and `ReportCreateRequest.isPrivate`.
- Added a private badge to report rows by reusing `reportDetailProvider`, since the generated `ReportSummary` model does not contain `isPrivate`.
- Added distinct English and Vietnamese labels for `SUBMITTED`, `IN_REVIEW`, `NEEDS_INFO`, `DECLINED`, `IN_PROGRESS`, `PROPOSED`, `COMPLETED`, and `CLOSED`; `NEEDS_INFO` and `DECLINED` use warning tone, completed/closed use success, and the remaining active statuses use info.
- Regenerated only Flutter localization output from the ARB files.

### TDD Evidence

Initial red command:

```text
flutter test test/issue_detail_test.dart test/report_form_test.dart test/report_draft_test.dart test/report_submitter_test.dart test/my_issues_test.dart
```

Expected failures observed:

- Decline title/reason were absent and rating remained visible.
- No private switch existed.
- `ReportDraft` had no `isPrivate` field or persisted value.
- Submitter did not forward privacy.
- Private badge was absent.
- Declined status still rendered `Declined` rather than `Not proceeding`.

Green regression coverage:

- `issue_detail_test.dart`: declined reason section is labeled and rating CTA is hidden.
- `report_form_test.dart`: toggling the private switch submits `isPrivate: true`.
- `report_draft_test.dart`: private state survives draft persistence round-trip.
- `report_submitter_test.dart`: draft privacy is forwarded to the repository.
- `my_issues_test.dart`: private list badge renders; all eight statuses have distinct plain-language labels and semantic tones.

### Verification

```text
flutter analyze
No issues found! (ran in 1.8s)
```

```text
flutter test
153 tests passed; 0 failed (All tests passed!)
```

```text
git diff --check
exit 0
```

### Self-review

- Confirmed no files under `app/packages/lamto_api` changed.
- Confirmed old persisted drafts safely default privacy to false.
- Confirmed declined reports cannot expose a stale rating action.
- Confirmed form editing locks the privacy switch after submission or while busy.
- Concern: `ReportSummary` does not expose privacy, so list badges require one detail-provider request per visible report. Add `is_private` to the summary API and regenerate the client in a separate API-contract task if list scale makes this material.

## Review Correction: Report Summary Privacy Contract

### Plan deviation

Review identified that the private list badge could not be implemented correctly or efficiently because Task 1 omitted `is_private` from the report-summary API contract. Per explicit user direction, this correction is a documented exception to the stage 4 plan's "client regen only in Task 1" rule: Task 3 now completes the omitted Task 1 contract field and regenerates the Dart client. The previous per-row `ReportDetail` fetch workaround was removed.

### Files

- `src/lamto/api/serializers.py`: added `ReportSummarySerializer.is_private`.
- `src/lamto/api/tests/test_reports.py`: list API now asserts a private report returns `is_private: true`.
- `docs/api/openapi-v1.yaml`: added required `ReportSummary.is_private`.
- `app/packages/lamto_api/doc/ReportSummary.md`: regenerated documentation.
- `app/packages/lamto_api/lib/src/model/report_summary.dart`: regenerated `isPrivate` model field/serializer.
- `app/packages/lamto_api/lib/src/model/report_summary.g.dart`: regenerated built-value implementation.
- `app/packages/lamto_api/test/report_summary_test.dart`: regenerated model test stub.
- `app/lib/features/reports/my_issues_screen.dart`: badge now reads `report.isPrivate`; removed detail-provider watch and per-row request.
- `app/test/my_issues_test.dart`: private summary drives badge and asserts zero detail fetches.
- `app/test/home_screen_test.dart`, `app/test/report_form_test.dart`, `app/test/report_submitter_test.dart`, `app/test/reports_repository_test.dart`: updated required summary fixtures/mock responses.

### TDD evidence

Backend red:

```text
SECRET_KEY=test POSTGRES_DB=lamto POSTGRES_USER=lamto_owner POSTGRES_PASSWORD=lamto-owner POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=5432 POSTGRES_EXECUTOR_ROLE=lamto_writer CLAMAV_HOST=127.0.0.1 CLAMAV_PORT=3310 AI_TRIAGE_URL='' AI_TRIAGE_TOKEN='' PRIVATE_STORAGE_BUCKET=lamto-documents PRIVATE_STORAGE_ENDPOINT_URL=http://127.0.0.1:9000 PRIVATE_STORAGE_ACCESS_KEY=x PRIVATE_STORAGE_SECRET_KEY=x .venv/bin/pytest src/lamto/api/tests/test_reports.py::ReportCreateTests::test_list_returns_only_own_reports
FAILED: KeyError: 'is_private'
```

Flutter red after client regeneration:

```text
cd app && flutter test test/my_issues_test.dart
FAILED: private badge absent because the row still fetched ReportDetail rather than reading ReportSummary.isPrivate
```

### Exact verification

```text
SECRET_KEY=test POSTGRES_DB=lamto POSTGRES_USER=lamto_owner POSTGRES_PASSWORD=lamto-owner POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=5432 POSTGRES_EXECUTOR_ROLE=lamto_writer CLAMAV_HOST=127.0.0.1 CLAMAV_PORT=3310 AI_TRIAGE_URL='' AI_TRIAGE_TOKEN='' PRIVATE_STORAGE_BUCKET=lamto-documents PRIVATE_STORAGE_ENDPOINT_URL=http://127.0.0.1:9000 PRIVATE_STORAGE_ACCESS_KEY=x PRIVATE_STORAGE_SECRET_KEY=x .venv/bin/pytest src/lamto/api/tests/test_reports.py
7 passed in 13.29s
```

```text
cd app && flutter analyze
No issues found! (ran in 1.5s)
```

```text
cd app && flutter test
153 tests passed; 0 failed (All tests passed!)
```

```text
bash app/tool/check_api_generated.sh
OK: generated API client matches the committed schema.
```

### Commit

`fbf28a0 fix(api): expose report privacy in summaries`

### Concerns

None. The list response now carries privacy directly and list rendering performs no detail requests.
