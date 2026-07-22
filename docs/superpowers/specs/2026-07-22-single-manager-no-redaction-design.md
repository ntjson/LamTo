# Single Manager, No Redaction — Design

**Date:** 2026-07-22
**Status:** Approved, ready for implementation planning

## Why

Manager 1 and Manager 2 already meet, review, and sign off offline — on paper, in
person, or over chat — before anyone touches the software. The application's
recorder-versus-verifier separation therefore duplicates a control that has
already happened, and it does so badly: it forces a second account to exist for
no purpose other than clicking a button. One manager account should perform the
data entry and publish the final result.

Separately, the redacted-copy requirement doubles every upload and gives
residents a censored document where the original would serve them better.
Residents should see the original.

These are two independent changes. They share this spec because they collide in
three files: `src/lamto/finance/fund.py`, `src/lamto/testing/factories.py`, and
`ops/pilot-runbook.md`.

## Scope

In scope:

- Remove the recorder ≠ verifier rule on fund sources.
- Seed one management account instead of two.
- Remove the redaction concept from the data model, the upload path, the
  anchored evidence payloads, the staff web forms, and the resident API.
- Serve originals to residents wherever redacted copies are served today.

Out of scope. The accountability model does not otherwise move: proposals,
work orders, settlement, blockchain anchoring, and the resident ledger keep
their current shape. The `approvers` and `corrections` compatibility fields on
the ledger serializer stay as they are. Fund source contracts remain invisible
to residents — they are not exposed today, and "residents see the original"
concerns documents residents already receive, not new ones.

## Decisions

Four decisions were settled before design, and the rest of this document
assumes them.

**Fund verification becomes a self-confirm step.** The record → confirm gesture
survives; only the different-actor requirement goes. A manager records a source,
then confirms it, and the balance moves on confirmation. This catches typos
before money appears in the fund and preserves the `verified_at` timestamp on
the record. The alternative — deleting verification outright — was rejected
because the second gesture still earns its place with one operator.

**Redaction is removed completely, not merely made optional.** Columns are
dropped rather than left nullable and empty.

**The database is re-seeded.** It holds development and seed data only, so the
migration drops columns outright with no data migration and no back-compat
branch in the verifier. Old snapshots stop being verifiable, which is
acceptable because they are disposable.

**The resident API field is renamed.** `redacted_documents` → `documents`,
`RedactedDocument` → `LedgerDocument`, with an OpenAPI regeneration of the Dart
client.

## Change 1 — Single manager

### Domain rule

`verify_fund_source` in `src/lamto/finance/fund.py` currently sets a `denied`
flag when `actor.user_id == entry.recorder.user_id`, falls out of the atomic
block, records a denial audit, and raises `PermissionDenied`. That entire branch
is removed, along with the `denied` / `denied_target` / `denied_actor` bookkeeping
that exists only to serve it. The function keeps:

- `require_management(verifier.user, entry.fund.building_id)`
- the source-entry-type check
- the "has no recorder" check
- the "already verified" check
- the `FundEntryVerification` row and its `fund.verify` audit event

`fund_balance(verified_only=True)` is unchanged: it still counts only confirmed
sources, so confirmation remains load-bearing.

### Web surface

`fund_verify` in `src/lamto/web/views/fund.py` keeps its route, its
`require_recent_auth` prompt, and the "awaiting verification" queue fed by
`pending_fund_verification_entries`. Only its docstring changes — the current
text claims "verifier != recorder, enforced by the domain service", which
becomes false.

### Seed and tests

`seed_pilot_world` in `src/lamto/testing/factories.py` seeds one management user
instead of iterating `for number in (1, 2)`. `seed_opening_fund` currently
unpacks `recorder, verifier = seed.management_memberships`; it uses the single
membership for both calls. `PilotSeed.management_users` and
`management_memberships` stay lists — a building may legitimately have several
managers; what changes is that dual control no longer requires it.

Call sites reaching for the second manager collapse to index `0`:

- `src/lamto/testing/factories.py:408` — `decide_proposal`
- `src/lamto/api/tests/test_proposals.py:137` — `decide_proposal`

`seed_pilot.py` prints one management login and its idempotent-reuse branch
lists `pilot-management-1@…` and `pilot-resident@…` only.

`onboard_building --managers` continues to accept a comma-separated list. A
building with several staff members is a real situation; it was never dual
control.

## Change 2 — No redaction

### Documents

`DocumentVersion` loses two fields:

- `variant` — with `REDACTED` deleted, the column can only ever hold
  `ORIGINAL`. A one-valued enum is dead schema.
- `redacts` — the self-referential foreign key has nothing left to point at.

`DocumentVersion.Variant` is deleted. `version` and the
`document_version_once` constraint stay: append-only versioning is a genuine
domain concept independent of redaction. Every version simply becomes `1`,
because `add_redacted_copy` was the only producer of version 2.

`add_redacted_copy` in `src/lamto/documents/services.py` is deleted.
`create_document_version` loses its `variant` and `_redacts` parameters; its
resident-occupancy branch drops the `variant == ORIGINAL` clause, which is now
implied.

`backup_objects.py` writes `"variant": version.variant` into its backup
manifest; that key is removed.

### Staff upload helpers

In `src/lamto/web/staff_documents.py`:

- `upload_document_pair(building, kind, uploader, original_file, redacted_file)`
  becomes `upload_document(building, kind, uploader, file)`. It keeps the
  ClamAV pipeline, the `transaction.atomic()` wrapper, and the
  purge-blobs-on-failure behaviour — a single upload can still fail after
  writing a blob.
- `document_pair_options` → `document_options`, returning
  `(value, label, version)` where value is the version pk.
- `selected_pair` → `selected_document`.
- `_referenced_document_ids` drops `evidence_redacted_id`,
  `transfer_redacted_id`, and `ack_redacted_id` from its protected-field
  sweeps.
- `_hard_delete_document` drops its two-pass delete. The comment explaining
  that redacted versions PROTECT-reference originals, and the
  `redacts__isnull=False` first pass, both go.

`src/lamto/web/views/requests.py:43` imports `upload_document_pair` and never
uses it. Delete the import.

### Finance validators

Three validators currently follow the same shape — find the original, then
prove a distinct clean redacted twin exists. All three keep only the first half:
the original must be clean, of the right kind, in the right building, and not
itself a redaction.

| Function | File |
|---|---|
| `_require_evidence_pair` → `_require_evidence` | `finance/fund.py` |
| `_quotation_pairs` → `_quotation_versions` | `finance/proposals.py` |
| `_require_proof_pair` → `_require_proof` | `finance/settlements.py` |

Their callers change signature accordingly: `record_fund_source` takes one
`evidence` argument, `record_transfer` takes `transfer`, `record_acknowledgement`
takes `ack`, and `publish_proposal_version` /
`build_proposal_evidence_payload` keep `quotation_versions` but stop pairing.

`ProposalDocument.objects.bulk_create` in `publish_proposal_version` currently
flattens `for pair in pairs for document in pair`; it iterates versions
directly.

### Schema migration

Columns dropped:

| Model | Fields |
|---|---|
| `documents.DocumentVersion` | `variant`, `redacts` |
| `finance.MaintenanceFundEntry` | `evidence_redacted`, `evidence_redacted_hash` |
| `finance.Settlement` | `transfer_redacted`, `ack_redacted` |

`Settlement.transfer_redacted` is currently `NOT NULL`; the migration drops the
column, so no default is needed. The append-only database triggers on
`documents_documentversion` and `documents_document` are unaffected by
`ALTER TABLE … DROP COLUMN`.

The `finance.Settlement` field renames — `transfer_original` → `transfer` and
`ack_original` → `ack` — are part of the same migration. The word "original"
only means something in contrast to "redacted", and that contrast is gone. The
same applies to `MaintenanceFundEntry.evidence_original` → `evidence` and
`evidence_original_hash` → `evidence_hash`.

### Anchored evidence payloads

`EVIDENCE_PAYLOAD_SCHEMAS` in `src/lamto/evidence/services.py` loses three keys:

- `PROPOSAL_CREATED` required: `quotation_redacted_hash`
- `SETTLEMENT` required: `transfer_redacted_sha256`, `ack_redacted_sha256`

`_submission_snapshot` in `finance/proposals.py` stops writing `redacted_id`
and `redacted_sha256` into each `quotation_versions` entry, and drops
`quotation_redacted_hash` from `evidence_payload`.
`build_settlement_evidence_payload` in `finance/settlements.py` drops the two
redacted SHA-256 keys and renames the remaining two to `transfer_sha256` and
`ack_sha256`. The `settlement.v1` schema string is retained — the payload
shape changes, but nothing consumes the version discriminator across the
re-seed boundary.

`_collect_document_checks` in `finance/publication.py` drops the
`QUOTATION_REDACTED`, `SETTLEMENT_TRANSFER_REDACTED`, and
`SETTLEMENT_ACK_REDACTED` gates, and reads `item["original_id"]` /
`item["original_sha256"]` under their new snapshot names. Because the database
is re-seeded, it does not tolerate old snapshots; a missing key is a genuine
error and should raise. The `select_related` in `publish_settlement_entry`
drops `transfer_redacted` and `ack_redacted` and follows the renamed
`transfer` / `ack` fields.

### Resident downloads

`resident_can_download` in `src/lamto/api/downloads.py` loses its
`if version.variant != DocumentVersion.Variant.REDACTED: return False` guard.
That single line is what currently guarantees no staff original escapes
regardless of whether the reference queries below it are exact, so it is
replaced by an explicit kind allowlist rather than nothing:

```python
RESIDENT_DOWNLOADABLE_KINDS = frozenset({
    Document.Kind.REPORT_PHOTO,
    Document.Kind.BEFORE_PHOTO,
    Document.Kind.AFTER_PHOTO,
    Document.Kind.QUOTATION,
    Document.Kind.PAYMENT_PROOF,
})
```

The function returns `False` immediately for any other kind, making `CONTRACT`
(fund source evidence), `INVOICE`, and `ACCEPTANCE_REPORT` unreachable by
construction. A bug in a reference query cannot leak them.

The reference queries then target the direct foreign keys:

- quotations: `ProposalDocument.objects.filter(document_version=version, …)`
  replaces `document_version__redacted_versions=version`
- settlement proofs: `Q(settlement__transfer=version) | Q(settlement__ack=version)`
  replaces the `_redacted` variants

The building-scope, proposal-status, and `SETTLED_STATUSES` conditions are
unchanged. The module docstring, which promises "redacted published-ledger
documents", is rewritten.

### Resident API contract

In `docs/api/openapi-v1.yaml`:

- `LedgerEntryDetail.redacted_documents` → `documents`, in both `properties`
  and `required`
- schema `RedactedDocument` → `LedgerDocument`

Regenerate the Dart client with `app/tool/generate_api.sh`;
`app/tool/check_api_generated.sh` verifies the committed output matches.

In `src/lamto/api/serializers.py`, `RedactedDocumentSerializer` →
`LedgerDocumentSerializer` and the `redacted_documents` field → `documents`.
The serializer method that builds proposal document rows currently nests
`for original in version.quotations.all()` inside
`for redacted in original.redacted_versions.all()`; the inner loop goes and it
emits one row per quotation version.

In `src/lamto/finance/selectors.py`:

- `resident_proposals` prefetches `"quotations__redacted_versions"`; this
  becomes `"quotations"`.
- The `select_related` on `settlement__transfer_redacted` /
  `settlement__ack_redacted` follows the renamed `transfer` / `ack` fields.
- The `redacted_docs` local and the `redacted_docs` payload key become `docs`,
  and the labels lose their parentheticals: `"Transfer evidence (redacted)"` →
  `"Transfer evidence"`, `"Payee acknowledgement (redacted)"` → `"Payee
  acknowledgement"`.

In `app/lib/features/ledger/ledger_detail_screen.dart`,
`entry.redactedDocuments` → `entry.documents` and the `RedactedDocument` type
annotation → `LedgerDocument`.

Localisation: `app_en.arb` `"ledgerDocuments": "Redacted documents"` →
`"Documents"`; `app_vi.arb` `"Tài liệu (đã che thông tin)"` → `"Tài liệu"`.
Regenerate `app_localizations*.dart`.

### Staff web forms and templates

`src/lamto/web/forms/staff.py`: `CreateProposalForm.quotation_redacted` and
`RecordFundSourceForm.evidence_redacted` are deleted. `quotation_original` →
`quotation` and `evidence_original` → `evidence`. In
`RecordSettlementTransferForm` and the acknowledgement form, `proof_pair` →
`proof`.

Views follow: `fund_record` (`views/fund.py:110`), the two
`upload_document_pair` calls in `views/proposals.py` (lines 225 and 270), and
both settlement views.

Templates:

- `web/staff/_fund_forms.html:9` — "Upload the source evidence original and a
  redacted copy (PDF)" → "Upload the source evidence (PDF)"
- `web/staff/proposal_create.html:13` — "Upload the quotation original and a
  redacted copy (PDF)" → "Upload the quotation (PDF)"
- `web/staff/settlement_detail.html:18-19` — the
  `{{ …transfer_original.filename }} / {{ …transfer_redacted.filename }}` pairs
  render one filename each

### CSV export

`_fund_entry_rows` in `src/lamto/web/views/exports.py` drops the
`evidence_redacted_hash` column from both its header and its rows, and renames
`evidence_original_hash` to `evidence_hash`.

## Documentation

`ops/pilot-runbook.md` needs correcting beyond the lines this change touches.
It is already stale: its participant table lists "Payment recorder", "Payment
verifier — must not be the recorder", and "Publisher", and step 6 reads "A
different manager verifies payment (self-verification is denied)". That
payment maker-checker separation was deleted in migration
`0012_delete_approvaldecision` and does not exist in the code today. The
runbook is rewritten to describe the actual flow with one manager, and its
resident-facing references to "redacted docs" (participant table, step 9)
become plain documents.

`PRODUCT.md` and `DESIGN.md` do not mention dual control or redaction and need
no change.

## Verification

Two new tests cover the behaviour this change creates:

1. A single manager records a fund source, confirms it, and
   `fund_balance(verified_only=True)` reflects the amount. This is the
   behaviour that was impossible before.
2. `resident_can_download` returns `False` for a `CONTRACT` document version
   even when the resident has an active occupancy in that building. This pins
   the allowlist as a real gate rather than incidental behaviour.

Existing suites are updated, not deleted — they are the regression net for a
change this wide:

- `src/lamto/web/tests/test_fund_ops.py`
- `src/lamto/finance/tests/test_fund.py`
- `src/lamto/finance/tests/test_settlements.py`
- `src/lamto/finance/tests/test_proposals.py`
- `src/lamto/finance/tests/test_standalone_proposals.py`
- `src/lamto/documents/tests/test_versions.py`
- `src/lamto/documents/tests/test_access.py`
- `src/lamto/api/tests/test_downloads.py`
- `src/lamto/api/tests/test_ledger.py`
- `src/lamto/api/tests/test_proposals.py`
- `src/lamto/web/tests/test_proposal_create.py`
- `src/lamto/evidence/tests/` — signing, outbox contract, chain integration
- `tests/isolation/test_cross_building_access.py`
- `tests/e2e/test_normal_flow.py`
- `tests/e2e/test_anchoring_disabled_mode.py`
- `app/test/ledger_screens_test.dart`, `app/test/proposals_test.dart`
- `app/packages/lamto_api/test/` — regenerated

Any test asserting that self-verification is denied, or that a redacted copy is
required, is deleted rather than inverted. The behaviour is gone, not changed.

Acceptance run, in order, because the migration is destructive by design:

1. `dropdb` and recreate, then `manage.py migrate`
2. `PILOT_ALLOW_FIXTURES=1 manage.py seed_pilot --fixture`
3. Full Python suite
4. `app/tool/generate_api.sh` then `app/tool/check_api_generated.sh`
5. `flutter test` in `app/`
6. Walk the runbook's normal path manually with the single seeded manager,
   confirming the fund balance moves on self-confirmation and that a resident
   opening a published ledger entry downloads an original document

## Risks

**The download allowlist is the only barrier for non-resident document kinds.**
It is a frozenset in one function; the new test pins it. Adding a
`Document.Kind` in future requires deciding explicitly whether residents may
see it — that is the intended cost.

**Payload schema change invalidates existing anchors.** Accepted: the database
is re-seeded and the chain is a local Besu development network.

**Field renames touch many call sites.** `variant` alone appears across roughly
twenty files outside migrations. These are mechanical, and the test suite
catches misses; the risk is tedium, not correctness.
