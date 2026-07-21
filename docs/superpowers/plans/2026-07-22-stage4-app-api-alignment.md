# Stage 4: App + API Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build out the resident Flutter app for the full two-role lifecycle — info-request replies, decline reasons, private requests, case progress timelines with photos, and community proposal viewing/rating — and rewrite the product docs to the two-role model.

**Architecture:** One small backend extension first (progress-update evidence photos in the timeline API), then four Flutter feature tasks following the app's established patterns (Riverpod `ProviderScope` + repository interfaces + `_FakeRepo` widget tests + gen-l10n ARB en/vi pairs + `AuthenticatedImage` for signed photo URLs), then a docs + verification task. The API is otherwise already complete: `reports/<pk>/info-reply`, `cases/<pk>/rating`, `proposals`, `proposals/<pk>`, `proposals/<pk>/rating` all exist from stages 2–3, and both happy-path e2e scripts already pass.

**Tech Stack:** Flutter + flutter_riverpod 3 + dio + generated `lamto_api` (dart-dio) client, gen-l10n (`app/l10n.yaml`, ARB in `app/lib/l10n/`), Django API + OpenAPI YAML (`docs/api/openapi-v1.yaml`) + `app/tool/generate_api.sh`.

**Spec:** `docs/superpowers/specs/2026-07-21-two-role-rebuild-design.md` §4 (+§2 for status semantics, §7 stage 4).

## Global Constraints

- Resident copy is **Vietnamese-first**: every new user-facing string gets entries in BOTH `app/lib/l10n/app_en.arb` and `app/lib/l10n/app_vi.arb` (the plan supplies the Vietnamese copy; adjust diacritics only if a native check corrects them). Status meaning never depends on color alone (DESIGN.md Separate States Rule).
- Explain before proving (DESIGN.md): proposal/settlement screens lead with plain-language status; hashes/event ids only behind the existing evidence-labels progressive disclosure (`app/lib/features/ledger/evidence_labels.dart`).
- Platform-native controls, no new dependencies: reuse `PageBody`, `ErrorRetry`, `LoadMoreButton`, `AuthenticatedImage`, `adaptive_page_route` from `app/lib/core/`.
- Widget tests follow the existing pattern: a `_FakeRepo implements XRepository` + `ProviderScope(overrides:[...])` (see `app/test/issue_detail_test.dart`).
- App commands (run from `app/`): `flutter analyze` then `flutter test` — both must be clean at the end of every task. Backend tests as before: `set -a; . ./.env; set +a; export POSTGRES_USER=lamto_owner POSTGRES_PASSWORD=lamto-owner; uv run pytest src/lamto tests -q` (with `docker compose up -d`).
- Client regen only in Task 1 (`bash app/tool/generate_api.sh`, needs java or docker); later tasks must not edit `app/packages/lamto_api` by hand.
- **Spec deviation (documented):** the spec's "triage-labels agent doc" rewrite is dropped — `docs/agents/triage-labels.md` maps issue-tracker labels for agent skills, not product roles; it contains nothing about Board/Operator/etc. Docs rewrite = `PRODUCT.md` + the `DESIGN.md` description line.
- Both happy-path e2e scripts already exist (`tests/e2e/test_normal_flow.py::test_direct_outcome_c_happy_path`, `::test_realistic_normal_flow`, `::test_standalone_proposal_happy_path`) — Task 6 only verifies and extends assertions, it does not create new scripts.

---

### Task 1: Timeline API — progress-update evidence photos

**Files:**
- Modify: `src/lamto/maintenance/selectors.py` (`resident_report_timeline`, the `updates` list ~line 42), `src/lamto/api/serializers.py` (a `ReportWorkUpdatePhoto` child serializer beside the existing photo serializer with `download_url`), `src/lamto/api/views.py` only if the download URL is built in the view (find the mechanism: `grep -rn "download_url" src/lamto/api` — report photos already produce signed `download_url` values; reuse that exact builder for update evidence versions), `docs/api/openapi-v1.yaml` (`ReportWorkUpdate` schema gains `photos`).
- Test: extend the API report-detail test file (find: `grep -rln "resident_report_timeline\|ReportDetail" src/lamto/api/tests`).
- Regenerate: `bash app/tool/generate_api.sh`.

**Interfaces:**
- Consumes: `WorkUpdate.evidence_links` (`WorkUpdateEvidence` rows with `version` + `kind` BEFORE/AFTER) from stage 2.
- Produces: each timeline update dict gains `"photos": [{"id": int, "filename": str, "kind": "BEFORE"|"AFTER", "download_url": str}]`; the regenerated Dart model `ReportWorkUpdate.photos` used by Task 4.

- [ ] **Step 1: Write the failing backend test** — in the located API test file, add a test that: builds a case with one `WorkUpdate` carrying one BEFORE evidence photo (use the factories' `document_pair`/`photo` helpers already used by maintenance tests), fetches `GET /api/v1/reports/<pk>` as the reporter, asserts `body["cases"][0]["updates"][0]["photos"][0]` has `id`, `kind == "BEFORE"`, `filename`, and a non-empty `download_url`. Mirror the file's existing report-photo assertions verbatim for style.
- [ ] **Step 2: Run to verify failure** — `uv run pytest <that file> -q` → KeyError/assertion on `photos`.
- [ ] **Step 3: Implement** — in the selector:

```python
        updates = []
        for u in case.updates.prefetch_related("evidence_links__version").order_by("pk"):
            updates.append({
                "id": u.pk, "cause": u.cause, "result": u.result, "created_at": u.created_at,
                "photos": [
                    {"id": link.version.pk, "filename": link.version.filename, "kind": link.kind}
                    for link in u.evidence_links.all()
                ],
            })
```

and attach `download_url` wherever the report-photo `download_url` is injected today (same token builder, same serializer layering — copy that mechanism exactly, do not invent a new one).
- [ ] **Step 4: YAML + regen** — add to `ReportWorkUpdate` in `docs/api/openapi-v1.yaml`:

```yaml
        photos:
          type: array
          items:
            type: object
            properties:
              id: {type: integer}
              filename: {type: string}
              kind: {type: string, enum: [BEFORE, AFTER]}
              download_url: {type: string}
            required: [id, filename, kind, download_url]
```

(match the file's existing indent/style; add `photos` to the schema's `required` list). Then `bash app/tool/generate_api.sh`.
- [ ] **Step 5: Green** — backend module + full suite; `cd app && flutter analyze && flutter test` (regen must not break existing models).
- [ ] **Step 6: Commit** — `git commit -am "feat(api): progress-update evidence photos in resident timeline"`

---

### Task 2: App — info-request reply

**Files:**
- Modify: `app/lib/features/reports/reports_repository.dart` (interface + impl: `Future<void> replyInfo({required int reportId, required String text})` calling the generated client's info-reply operation), `app/lib/features/reports/issue_detail_screen.dart` (NEEDS_INFO banner + reply sheet), `app/lib/l10n/app_en.arb` + `app_vi.arb`.
- Test: `app/test/issue_detail_test.dart` (extend `_FakeRepo` + new cases).

**Interfaces:**
- Consumes: `ReportDetail.openInfoRequest` (generated model: `id`, `message`, `createdAt`) and `ReportDetail.status`; `uploadPhoto` already on the repository (photos may accompany a reply).
- Produces: `replyInfo` on `ReportsRepository`; the detail screen refetches after replying.

- [ ] **Step 1: Write the failing widget tests** — extend `_FakeRepo` with `replyInfo` recording its arguments. New tests: (a) a detail whose `status == "NEEDS_INFO"` and non-null `openInfoRequest` renders the management message and a reply button; (b) submitting the sheet with text calls `replyInfo(reportId: …, text: "Kitchen tap")` and triggers a refetch (fake returns an updated detail with `status == "IN_REVIEW"`; assert the banner disappears); (c) empty text keeps the submit disabled.
- [ ] **Step 2: Run to verify failure** — `cd app && flutter test test/issue_detail_test.dart` → compile error on `replyInfo`.
- [ ] **Step 3: Implement.** Repository impl mirrors `rateCase`'s call/error mapping exactly (Dio → `Failure`). Screen: when `report.status == 'NEEDS_INFO' && report.openInfoRequest != null`, render above the photos section a bordered banner (warning tone, icon + text — Separate States Rule):

```dart
// inside _body's children, after the status header
if (report.status == 'NEEDS_INFO' && report.openInfoRequest != null)
  _InfoRequestBanner(
    message: report.openInfoRequest!.message,
    onReply: () => _showReplySheet(context, ref, report.id),
  ),
```

`_showReplySheet` presents a modal sheet (Cupertino/Material via the file's existing adaptive helpers, same as the rating sheet `_RateCaseSheet`) with a multiline text field, a hint that photos can be added from the report's photo button, and a submit that awaits `replyInfo` then invalidates the detail provider. Copy `_RateCaseSheet`'s structure (state class, busy flag, error display) — adapt, don't re-derive.
- [ ] **Step 4: l10n** — add to `app_en.arb` / `app_vi.arb`:

```json
"infoRequestTitle": "Management needs more information",
"infoReplyHint": "Write your reply…",
"infoReplySubmit": "Send reply",
"infoReplyPhotosHint": "You can also add photos from the photo section below."
```

```json
"infoRequestTitle": "Ban quản lý cần thêm thông tin",
"infoReplyHint": "Nhập câu trả lời của bạn…",
"infoReplySubmit": "Gửi trả lời",
"infoReplyPhotosHint": "Bạn cũng có thể thêm ảnh ở phần ảnh bên dưới."
```

- [ ] **Step 5: Green** — `flutter analyze && flutter test` → clean.
- [ ] **Step 6: Commit** — `git commit -am "feat(app): resident info-request reply"`

---

### Task 3: App — decline reason + private requests

**Files:**
- Modify: `app/lib/features/reports/issue_detail_screen.dart` (decline section), `app/lib/features/reports/report_form_screen.dart` + `report_draft.dart` + `report_submitter.dart` (private toggle → `is_private` in `createReport`), `app/lib/features/reports/reports_repository.dart` (`createReport` gains `bool isPrivate = false` if the generated request model requires explicit wiring), `app/lib/features/reports/my_issues_screen.dart` (private badge on list rows), status label map (find it: `grep -rn "SUBMITTED\|IN_REVIEW\|NEEDS_INFO" app/lib --include="*.dart"` — verify all 8 statuses have en+vi labels and semantic tones; add any missing), `app/lib/l10n/app_en.arb` + `app_vi.arb`.
- Test: `app/test/issue_detail_test.dart`, `app/test/report_form_test.dart` (or the form's existing test file — find with `ls app/test | grep -i form`).

**Interfaces:**
- Consumes: `ReportDetail.declinedReason` (nullable), `ReportDetail.isPrivate`, `ReportCreateRequest.isPrivate` from the regenerated client.
- Produces: nothing downstream.

- [ ] **Step 1: Failing widget tests** — (a) detail with `status == "DECLINED"` and a reason renders the reason inside a clearly-labeled section (find by the l10n title text) and hides the rating CTA; (b) form: toggling the private switch submits `isPrivate: true` (assert on the fake repository's captured argument); (c) list row for a private report shows the private badge.
- [ ] **Step 2: Verify failure**, then implement. Decline section (issue detail, rendered when `declinedReason != null`):

```dart
if (report.declinedReason != null)
  _SectionCard(
    title: l10n.declinedTitle,
    child: Text(report.declinedReason!),
  ),
```

(`_SectionCard` = whatever grouped-container pattern the file already uses for photos — reuse it, don't invent one.) Form: a platform switch row below the location picker with title + subtitle explaining the effect; the draft carries `isPrivate` through the submitter's queue (the submitter has offline-retry semantics — thread the field through its persisted draft model and bump any draft schema handling the same way `client_ref` is stored).
- [ ] **Step 3: l10n** —

```json
"declinedTitle": "Management decided not to proceed",
"privateToggleTitle": "Private request",
"privateToggleSubtitle": "Only you and Management can see this request. Private requests are not part of community proposals.",
"privateBadge": "Private",
"statusSubmitted": "Submitted", "statusInReview": "In review", "statusNeedsInfo": "Needs your information",
"statusDeclined": "Not proceeding", "statusInProgress": "In progress", "statusProposed": "Proposal created",
"statusCompleted": "Completed", "statusClosed": "Closed"
```

```json
"declinedTitle": "Ban quản lý quyết định không tiếp nhận",
"privateToggleTitle": "Yêu cầu riêng tư",
"privateToggleSubtitle": "Chỉ bạn và Ban quản lý xem được yêu cầu này. Yêu cầu riêng tư không đưa vào đề xuất cộng đồng.",
"privateBadge": "Riêng tư",
"statusSubmitted": "Đã gửi", "statusInReview": "Đang xem xét", "statusNeedsInfo": "Cần bạn bổ sung thông tin",
"statusDeclined": "Không tiếp nhận", "statusInProgress": "Đang xử lý", "statusProposed": "Đã lập đề xuất",
"statusCompleted": "Đã hoàn thành", "statusClosed": "Đã đóng"
```

(Skip any key that already exists from the stage-2 patch — check first; never duplicate ARB keys.)
- [ ] **Step 4: Green** — `flutter analyze && flutter test`.
- [ ] **Step 5: Commit** — `git commit -am "feat(app): decline reasons and private requests"`

---

### Task 4: App — case progress timeline

**Files:**
- Modify: `app/lib/features/reports/issue_detail_screen.dart` (progress section between status header and rating), `app/lib/l10n/app_en.arb` + `app_vi.arb`.
- Test: `app/test/issue_detail_test.dart`.

**Interfaces:**
- Consumes: `ReportCaseInfo.updates` (each: `cause`, `result`, `createdAt`, `photos[]` with `downloadUrl` from Task 1), `completedAt`, `canRate`.
- Produces: nothing downstream.

- [ ] **Step 1: Failing widget tests** — (a) a detail whose case has two updates renders both in order with cause + result text and a photo thumbnail per update photo (assert `AuthenticatedImage` count); (b) a case with `completedAt != null` shows the completed marker and, when `canRate`, the existing rating CTA; (c) no updates → the section shows the quiet empty line, not an empty card.
- [ ] **Step 2: Verify failure**, then implement a chronological list inside the existing case section:

```dart
for (final update in caseInfo.updates) ...[
  _ProgressTile(
    createdAt: update.createdAt,
    cause: update.cause,
    result: update.result,
    photos: update.photos,   // thumbnails via AuthenticatedImage(photo.downloadUrl)
  ),
],
if (caseInfo.completedAt != null)
  _CompletedMarker(at: caseInfo.completedAt!),
```

`_ProgressTile` follows the flat list-tile look of the ledger detail rows (no nested cards — DESIGN.md prohibition); thumbnails reuse the exact thumbnail sizing the report-photos section uses.
- [ ] **Step 3: l10n** —

```json
"progressTitle": "Work progress",
"progressEmpty": "No progress updates yet.",
"progressCompleted": "Work completed"
```

```json
"progressTitle": "Tiến độ xử lý",
"progressEmpty": "Chưa có cập nhật tiến độ.",
"progressCompleted": "Đã hoàn thành công việc"
```

- [ ] **Step 4: Green**, **Step 5: Commit** — `git commit -am "feat(app): case progress timeline with photos"`

---

### Task 5: App — community proposals (list, detail, rating)

**Files:**
- Create: `app/lib/features/proposals/proposals_repository.dart`, `app/lib/features/proposals/proposals_list_screen.dart`, `app/lib/features/proposals/proposal_detail_screen.dart`.
- Modify: `app/lib/features/ledger/ledger_screen.dart` (a segmented control at the top: Ledger | Proposals — the proposals segment hosts the list; keeps the 4-tab shell intact, no new tab), `app/lib/features/ledger/ledger_detail_screen.dart` (when the entry links a proposal, a whole-row link "View proposal" pushing the detail), `app/lib/l10n/app_en.arb` + `app_vi.arb`.
- Test: `app/test/proposals_test.dart` (new; both screens), extend the ledger screen test for the segment.

**Interfaces:**
- Consumes: generated client `Proposal` model (list + detail from `GET /proposals`, `GET /proposals/<pk>` — fields per the YAML `Proposal` schema: status, purpose/problem, proposed action, amount, fund code, contractor name, expected schedule, versions with anchor info, settlement summary, `can_rate`-equivalent; read the generated model in `app/packages/lamto_api/lib/src/model/` for exact property names before coding), `ProposalRatingResult`, `evidence_labels.dart` for anchor levels.
- Produces:

```dart
abstract class ProposalsRepository {
  Future<PaginatedProposalList> listProposals({String? cursor});
  Future<ProposalDetail> fetchProposal(int id);
  Future<ProposalRatingResult> rateProposal({
    required int id, required bool satisfied, String comment = '',
  });
}
```

(match the generated model class names exactly — if the generated list/detail classes are both named `Proposal`, alias accordingly; follow `reports_repository.dart`'s structure for the impl + provider.)

- [ ] **Step 1: Failing widget tests** — list: renders proposal rows (title = plain-language purpose, status chip, amount with tabular numerals via `core/format.dart`); detail: renders the seven fields in labeled rows, a versions section (version number + published date + evidence level chip via `evidence_labels.dart`), progress updates when present, settlement section with plain-language settled/unsettled line, and a rating CTA only when the proposal is completed and unrated; rating sheet submits `satisfied`. Fake repository pattern as always.
- [ ] **Step 2: Verify failure**, then implement. List screen mirrors `my_issues_screen.dart` (pull-to-refresh, `LoadMoreButton` pagination, `ErrorRetry`). Detail screen mirrors `ledger_detail_screen.dart`'s flat sections; the rating sheet is a copy-adapt of `_RateCaseSheet` targeting `rateProposal`. Ledger segment: a `StateProvider<int>` local to the ledger feature toggling between the two lists — the shell's `ledgerTabIndex` deep-link behavior must keep working (run the deep-link test).
- [ ] **Step 3: l10n** —

```json
"proposalsSegment": "Proposals",
"ledgerSegment": "Ledger",
"proposalStatusPublished": "Published", "proposalStatusInProgress": "In progress",
"proposalStatusNotProceeding": "Not proceeding", "proposalStatusCompleted": "Completed",
"proposalStatusClosed": "Closed", "proposalStatusDraft": "Draft",
"proposalProblem": "Problem or need", "proposalAction": "Proposed action",
"proposalCost": "Estimated cost", "proposalFund": "Funding source",
"proposalContractor": "Contractor", "proposalSchedule": "Expected schedule",
"proposalVersions": "Published versions", "proposalSettlement": "Payment settlement",
"proposalSettled": "Paid and acknowledged by the payee",
"proposalUnsettled": "Payment not yet settled",
"proposalViewFromLedger": "View proposal",
"proposalRateCta": "Rate the result"
```

```json
"proposalsSegment": "Đề xuất",
"ledgerSegment": "Sổ quỹ",
"proposalStatusPublished": "Đã công bố", "proposalStatusInProgress": "Đang thực hiện",
"proposalStatusNotProceeding": "Không thực hiện", "proposalStatusCompleted": "Đã hoàn thành",
"proposalStatusClosed": "Đã đóng", "proposalStatusDraft": "Bản nháp",
"proposalProblem": "Vấn đề hoặc nhu cầu", "proposalAction": "Phương án đề xuất",
"proposalCost": "Chi phí dự kiến", "proposalFund": "Nguồn kinh phí",
"proposalContractor": "Nhà thầu", "proposalSchedule": "Tiến độ dự kiến",
"proposalVersions": "Các phiên bản đã công bố", "proposalSettlement": "Quyết toán thanh toán",
"proposalSettled": "Đã thanh toán và bên nhận đã xác nhận",
"proposalUnsettled": "Chưa quyết toán thanh toán",
"proposalViewFromLedger": "Xem đề xuất",
"proposalRateCta": "Đánh giá kết quả"
```

- [ ] **Step 4: Green** — `flutter analyze && flutter test`; also `flutter test test/deep_link_test.dart` explicitly.
- [ ] **Step 5: Commit** — `git commit -am "feat(app): community proposals list, detail, and rating"`

---

### Task 6: Docs rewrite + stage verification

**Files:**
- Modify: `PRODUCT.md` (Users: primary residents stay; secondary becomes the single Management staff describing triage, direct handling, proposals, settlements, fund transparency — delete operator/board/representative/auditor sentences; Product Purpose: drop the emergency-drill success criterion (deleted workflow) and describe success as both happy paths completing end to end with independently verifiable proposal + settlement anchors; Positioning/Anti-references/Principles stand), `DESIGN.md` line 3 description (`"…resident mobile app and staff web platform"` → `"…resident mobile app and Management web workspace"`) and §1's operator wording (same substitution — nothing else), `app/README.md` if it names removed concepts (check: `grep -n "operator\|board\|auditor\|work order" app/README.md`).
- No code files.

- [ ] **Step 1: Rewrite the docs** per Files. Keep PRODUCT.md's voice and length discipline; the Users secondary paragraph becomes (verbatim starting point, tune wording in place):
  > **Secondary:** Management staff. They review and classify resident requests with AI assistance, request missing information, decline with recorded reasons, handle work directly with published progress, create and publish immutable spending proposals, record settlement evidence, and maintain the fund ledger through a denser desktop-first web workspace.
- [ ] **Step 2: Verify the e2e scripts still express the spec's three flows** — `uv run pytest tests/e2e/test_normal_flow.py -q` → 3 passed (outcome C, realistic flow with proposal D, standalone proposal). Add missing assertions only if a spec step (resident rating, anchor verification) is unasserted — read the three tests and confirm each ends with a rating + anchor check.
- [ ] **Step 3: Full verification suite**

```bash
uv run pytest src/lamto tests -q            # all passed
cd app && flutter analyze && flutter test   # clean
bash app/tool/check_api_generated.sh        # no drift
```

- [ ] **Step 4: Role-vocabulary sweep** — `grep -rn "Operator\|Board\|Auditor\|Resident Representative\|Technical Admin" PRODUCT.md DESIGN.md app/README.md docs/api/openapi-v1.yaml` → zero product-role hits (agent-tooling docs under `docs/agents/` are exempt).
- [ ] **Step 5: Commit** — `git commit -am "docs: two-role product model; stage 4 complete"`

---

## Self-review notes (already applied)

- The API needed only one extension (update photos); everything else the app consumes already exists — verified against `src/lamto/api/urls.py` and the YAML schemas before planning.
- Proposals live as a segment inside the Ledger tab rather than a fifth tab: keeps the shell/deep-link contract (`ledgerTabIndex`) stable and matches the accountability-narrative placement.
- The `report_submitter` offline-draft path must carry `isPrivate` (Task 3) — flagged explicitly because silently dropping it on retry would misclassify a private request.
- Vietnamese strings are supplied inline so the Vietnamese-first rule can't be deferred; existing ARB keys from the stage-2 patch are checked before adding to avoid duplicates.
- Spec's triage-labels doc rewrite dropped (it's agent tooling, not product roles) — recorded as a deviation in Global Constraints.
