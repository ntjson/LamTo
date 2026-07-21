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
