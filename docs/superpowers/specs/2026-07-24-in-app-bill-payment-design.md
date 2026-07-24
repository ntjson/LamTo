# In-App Bill Payment Design

Date: 2026-07-24

## Summary

LamTo will let a building's management issue a bill to a specific resident's app
and let that resident record that they have paid it by bank transfer. Management
scans or uploads an electronic copy of the bill (which already carries the
bank's transfer QR); LamTo delivers it to the one addressed resident, who views
it in the app, transfers the amount using their own banking app, and then
records the payment inside LamTo by scanning a LamTo-specific bill QR.

LamTo never moves money, holds funds, or verifies the transfer with a bank. A
recorded payment is resident self-attestation, captured through a demo scan and
stored behind a single confirmation seam so that a real bank webhook or a manual
management confirmation can replace the demo trigger later without changing the
rest of the system.

The design adds one focused domain record (`Bill`) in a new `billing` app and
reuses LamTo's existing `Document` storage, `ResidentOccupancy`,
`ManagementMembership`, `NotificationDelivery`, push delivery, audit, and
building-isolation mechanisms.

## Goals

- Let any active management member for the current building issue a bill to a
  specific resident of that building, attaching the uploaded bill file.
- Deliver the bill only to the addressed resident, in-app and — by default —
  by push.
- Let a resident view the bill and its file, and record a payment by scanning a
  LamTo-specific bill QR.
- Keep confirmation behind one shared service so real reconciliation can replace
  the demo trigger.
- Represent a recorded payment honestly everywhere: resident-reported, not
  bank-verified.
- Preserve building isolation, occupancy-scoped access, auditability, and
  idempotency.

## Non-goals

- Moving money, holding funds, initiating transfers, or verifying a transfer
  with a bank.
- Generating a VietQR or pre-filling a transfer amount.
- Real bank/gateway reconciliation, management manual "mark paid", partial
  payments, refunds, or receipts (all deferred behind the confirmation seam).
- Recurring bills, schedules, reminders, late fees, or overdue state machines.
- Multi-currency; VND only.
- Billing a resident with no active occupancy in the building, or targeting a
  whole unit so co-residents also see the bill (only the named resident sees it).
- A generic invoicing or payments framework.

## Existing foundations

- `ResidentOccupancy` links a resident `User` to a `Unit` and `Building`, with
  an `active` flag.
- `ManagementMembership` supplies one active management role scoped to a
  building. The management website already enforces authentication, MFA,
  current-building selection, and cross-building denial.
- `Document` / `DocumentVersion` store scanned private files by `kind`;
  `web.staff_documents.upload_document` is the staff upload path and virus-scans
  to a `CLEAN` version.
- `NotificationDelivery` and `queue_notification` supply building-scoped in-app
  and push delivery with per-recipient read state, retries, and dead-letter
  handling; `notifications.push` maps event codes to generic OS-visible copy.
- The Flutter app has a tab shell, a Home screen that highlights the newest
  announcement, a notification inbox with deep links, secure storage, and a
  `camera`-based reader used for license-plate OCR only — there is no QR decoder
  yet.

## Domain model

### Bill (new `billing` app)

Add a `Bill` record with:

- `building` (FK) and `resident` (FK to `User`) — the addressed homeowner. The
  resident must have an active `ResidentOccupancy` in `building`; this is enforced
  in the issue transaction and reflected by the management resident picker, which
  lists only that building's active residents;
- `title`, limited to 160 characters (e.g. "Phí quản lý 07/2026");
- optional plain-text `note`, limited to 500 characters;
- optional `period` label and optional `due_date`;
- `amount_vnd`, a positive integer in đồng (VND has no minor units);
- `document` (FK to a `DocumentVersion` of a new `Document.Kind = RESIDENT_BILL`)
  — the uploaded electronic copy;
- `reference`, an unguessable per-bill token (≥16 chars); it is both the bill's
  display reference and the payload carried by the LamTo bill QR;
- `status`: `ISSUED`, `PAID`, or `VOID`;
- `payment_source`: null while unpaid; on payment one of `SELF_ATTESTED_DEMO`
  (this release) or the deferred `BANK_WEBHOOK` / `MANAGEMENT_MANUAL`;
- `issued_by`, `issued_at`;
- nullable `paid_at` and `paid_confirmed_by`;
- nullable `void_by`, `void_at`, and `void_reason` (required only for void).

`status=PAID` means a payment was **recorded**, not that a bank confirmed it;
`payment_source` records how. Immutable audit events record issue, payment, and
void with the responsible actor and timestamp.

### The LamTo bill QR

`reference` is rendered as a QR encoding the LamTo-specific string
`lamto-bill:<reference>`. The management website displays this QR on the bill's
detail page; in the demo the resident scans it to record payment. The scheme
prefix lets the app reject any non-LamTo QR, and the unguessable reference ties a
scan to exactly one bill.

In production this QR is a demo affordance only: real reconciliation is
server-side and does not involve the phone. It is required now purely so the
demo records a payment against the correct bill rather than accepting any QR.

## Confirmation seam

A single service `billing.confirm_payment(bill, *, source, actor, reference)`
performs, in one transaction:

1. Lock the bill and confirm it is `ISSUED`. Idempotent: an already `PAID` bill
   returns unchanged; a `VOID` bill raises a conflict.
2. Verify the supplied `reference` equals `bill.reference`.
3. Set `status=PAID`, `payment_source=source`, `paid_at`,
   `paid_confirmed_by=actor`.
4. Append an immutable "payment recorded" audit event carrying the source.

Today its only caller is the resident confirm endpoint, with
`source=SELF_ATTESTED_DEMO`. A future bank webhook or a management manual-confirm
calls the same service with a different `source` and actor; nothing else in the
system changes.

## API (resident, authenticated)

- `GET /api/v1/bills` — bills addressed to the requesting resident, newest first,
  with status and amount. Excludes `VOID`.
- `GET /api/v1/bills/{id}` — full detail plus a download route for the bill file.
  Both are gated by the caller being `bill.resident`.
- `POST /api/v1/bills/{id}/confirm-payment` — the body carries the scanned
  `reference`. Guards: the caller is `bill.resident`; then
  `confirm_payment(..., source=SELF_ATTESTED_DEMO, reference=…)`. Returns the
  updated bill. An invalid or mismatched reference returns a `problem+json` 422;
  a `VOID` bill returns 409.

Bill-file download reuses `Document` storage but is gated by billing's own
`caller == bill.resident` check rather than the evidence allowlist.

## Management flow (Django web portal, building-scoped)

Add a Bills area to the building-scoped management website.

- **Issue**: a form selects a resident of the current building (from that
  building's active residents) and accepts title, amount, optional period/due
  date/note, and the bill file. In one transaction it uploads the file via
  `upload_document(kind=RESIDENT_BILL)`, creates the `Bill` with a fresh
  `reference`, and queues the resident's delivery; the external push call happens
  after commit.
- **Detail**: shows status, amount, the LamTo bill QR, and — when paid — who
  recorded it and when, labelled **"Cư dân tự xác nhận — chưa đối soát ngân
  hàng" (resident-reported, not bank-verified)**.
- **Void**: after confirmation and a required reason, marks the bill `VOID`,
  hides it from the resident, and appends an audit event (mirrors announcement
  withdrawal). A voided bill cannot be paid or reissued; a correction is a new
  bill.

Every action rechecks active management membership and building scope
server-side; UI filtering is not authorization.

## Delivery

Use event code `building.bill_issued`. The recipient is the single addressed
resident (`bill.resident`) — not the unit's other occupants, and not the whole
building. In-app delivery is mandatory; push defaults to enabled and is
resident-toggleable; email is never queued. Bill creation and its notification rows are written atomically, and no
push provider call happens inside that transaction. The in-app item deep-links to
the bill.

OS-visible push copy is generic Vietnamese ("Có hóa đơn mới từ ban quản lý");
amount and detail are read only inside the authenticated app. Void hides the
bill's in-app deliveries.

## Resident experience (Flutter)

- A "Hóa đơn" (Bills) surface lists the resident's bills with status; Home
  highlights the newest unpaid bill much as it highlights the newest
  announcement.
- Bill detail shows title, amount, due date, status, and an in-app
  viewer/download of the bill file.
- The primary action **"Tôi đã thanh toán"** opens a QR scanner (new
  `mobile_scanner` dependency). A scanned code must start with `lamto-bill:`;
  anything else shows "Mã QR không hợp lệ". On a valid scan the app posts the
  reference to the confirm endpoint.
- Success copy is **"Đã ghi nhận thanh toán" / "Payment recorded"** — never
  "successful" or "paid" language that implies bank verification. The recorded
  bill thereafter reads as resident-reported.
- Errors state whether the payment was recorded and the next safe action; the
  confirm call is idempotent, so a retry after a flaky network does not
  double-record.
- Vietnamese-first with English strings and screen-reader semantics, per the
  existing l10n pattern.

## Dependencies added

- Flutter: `mobile_scanner` — QR decoding for the confirm scan.
- Backend: `qrcode` — render the LamTo bill QR as inline SVG on the management
  page (SVG factory, no image library).

## Security and error handling

- Every server action rechecks scope: management actions recheck active
  membership and building; resident actions require the caller to be
  `bill.resident`. The confirm endpoint enforces the reference match server-side
  even if a client bypasses the QR.
- `reference` has sufficient entropy and is the only accepted confirm payload for
  a bill.
- Bill-file access is `bill.resident`-gated and audited; a `VOID` bill is not
  resident-visible.
- Validation uses standard `application/problem+json` responses; the
  positive-amount database constraint is the final defense.
- Confirmation is idempotent; repeated submissions and stale management actions
  use conflict behavior rather than duplicating records.
- A recorded payment is never presented as bank-verified in management, audit, or
  resident surfaces.

## Testing

Use the existing Django and Flutter test stacks.

### Backend

- The issue-time check that the resident has an active occupancy in the building,
  the positive-amount constraint, and the `RESIDENT_BILL` document kind.
- Delivery reaches exactly the addressed resident **only** — not a co-resident of
  the same unit, not the whole building — with building isolation and no email.
- `confirm_payment` idempotency, reference match and mismatch, `VOID` conflict,
  and the audit event carrying the source.
- Resident endpoints: `bill.resident`-gated list, detail, and download; another
  resident (including a co-resident of the same unit) and cross-building access
  are denied.
- Void hides the bill and blocks payment and reissue; required reason.
- OpenAPI schema and standardized problem responses.

### Management website

- Only active members act in their selected building; cross-building denial.
- Issue creates the bill, uploads the file, and queues deliveries.
- Paid bills display resident-reported / not-bank-verified labelling.
- A stale void reloads the final state safely.

### Flutter

- Bills list and detail, file view, and the Home highlight of the newest unpaid
  bill.
- Confirm flow: a valid `lamto-bill:` scan records payment and shows "Payment
  recorded"; a non-LamTo QR is rejected; a retry is idempotent.
- Deep link from the bill notification.
- Vietnamese and English strings and screen-reader semantics.

### End-to-end acceptance path

1. Management issues a bill to a specific resident and uploads the file.
2. That resident sees it on Home and in the inbox, and opens the file.
3. The resident scans the LamTo bill QR and sees "Payment recorded".
4. Management sees the bill as paid, labelled resident-reported / not
   bank-verified.
5. A voided bill disappears from the resident app and cannot be paid.

## Deferred work

Add only when a concrete need appears:

- real reconciliation via a bank/gateway webhook or management manual-confirm
  (both call `confirm_payment`);
- VietQR generation with a pre-filled amount;
- overdue and reminder handling, recurring bills, partial payments, refunds, or
  receipts;
- multi-currency, targeting a whole unit so co-residents also receive a bill, or
  associating a bill with a specific unit for the building's records;
- a printable payment slip carrying the LamTo bill QR.
