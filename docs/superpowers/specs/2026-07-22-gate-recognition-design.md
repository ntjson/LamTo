# Gate Recognition — Design

Date: 2026-07-22
Status: Approved for planning

## Purpose

Residents register their vehicle licence plates and enrol their face in the LamTo app.
A gate reader recognizes them on arrival and writes a short-lived entry/exit log the
Management workspace can view.

The reader is a second phone running the existing Flutter app in a device-credentialled
mode. It is a stand-in for the eventual hardware — an ALPR camera and a facial-recognition
device — and calls the same endpoint that hardware will call, unchanged.

## What this is not

This subsystem **logs identity; it does not authorize anything**. It opens no barrier,
unlocks no door, and returns no allow/deny verdict. It has no relationship to the
maintenance-accountability chain and must not be entangled with `maintenance`, `finance`,
or `evidence`.

`PRODUCT.md` lists a surveillance interface as an anti-reference. The 24-hour retention
below is the primary answer to that: the log is a rolling live view, not a movement
history.

## Decisions

| Question | Decision |
|---|---|
| What recognition does | Writes an entry/exit log for staff. No access decision. |
| Where matching runs | Face: server-side, own model. Plate: OCR on the reader device. |
| Enrollment | Manager approves both plates and faces. |
| Face storage | Embedding only. Enrollment photo discarded after the decision. |
| Gate capture images | Never stored. Embedded in-memory, discarded within the request. |
| Event retention | 24 hours, configurable, hourly purge. |
| Reader | A credentialled mode inside the existing Flutter app. |
| Multiple plates per resident | In scope. |
| Household members without accounts | Out of MVP — deferred to its own spec. |

A licence plate is not biometric data; it is text. Real ALPR cameras perform their own OCR
and emit the plate string, so the server never needs a plate model. The reader phone does
on-device OCR with Google ML Kit text recognition, which makes the phone stage behave like
the hardware it stands in for.

## Architecture

New Django app `src/lamto/gate/`, reusing `accounts` tenancy (`Building`, `Unit`,
`ResidentOccupancy`).

The gate app **writes nothing to the `audit` app**. A 24-hour event that leaves a permanent
audit row is not a 24-hour event.

### Data model

**`FaceEnrollment`** — one-to-one with `ResidentOccupancy`.

- Fernet-encrypted 512-float embedding (`cryptography` is already present via `web3`)
- `model_name`, `model_version` — identifies who must re-enrol when the model changes
- `status`: `pending` | `approved` | `rejected` | `expired`
- `submitted_at`, `reviewed_by`, `reviewed_at`, `review_note`

Rejection, expiry, and revocation **delete the embedding row**. They do not flag it. A
revoked biometric that lingers is a retained biometric.

**`VehiclePlate`** — FK to `ResidentOccupancy`. Many rows per resident (a car and a
motorbike is the normal case).

- Normalized plate text: uppercased, separators stripped (`51F-123.45` → `51F12345`)
- Uniqueness constraint across approved plates within a building
- Same status and review fields as `FaceEnrollment`

**`PendingEnrollmentPhoto`** — FK to `FaceEnrollment`. The short-lived review image, in the
existing MinIO/S3 document storage.

- `storage_key`, `created_at`, `expires_at` = `created_at + GATE_ENROLLMENT_PHOTO_TTL_HOURS`
  (default 72)

Its lifecycle is **entirely independent of `GateEvent` retention** — separate setting,
separate query, separate deletion path. The two never share a knob or a code path.

**`GateDevice`** — FK to `Building`.

- `label`, `direction` (`entry` | `exit`), `active`
- `last_seen_at`, **truncated to the hour**

A single camera cannot infer direction, so the device declares it. That is what makes the
record an entry/exit log rather than a sighting log.

Hour-truncation of `last_seen_at` reconciles two requirements: operations needs to know a
reader went dark, and retention forbids keeping individual event timestamps. An
hour-resolution device heartbeat is enough for the first and too coarse for the second.

**`GateDeviceCredential`** — FK to `GateDevice`.

- `token_sha256` (unique), `created_at`, `created_by`
- `expires_at` (nullable), `revoked_at`, `revoked_by`

Only the hash is stored. The token is high-entropy random — SHA-256 is correct here, not a
password KDF — and is displayed exactly once at issue. A credential is valid when
`revoked_at` is null and `expires_at` is null or in the future. Multiple live credentials
per device is the rotation mechanism, not an accident.

Considered and rejected: reusing `django-rest-knox` tokens. Knox binds a token to a `User`,
and a gate reader is not a person in the accountability model.

**`GateEvent`** — append-only.

- `device` FK, `direction` snapshot, `occurred_at`
- `matched_occupancy` (nullable, `on_delete=CASCADE`)
- `matched_plate` (nullable, `on_delete=CASCADE`)
- Raw plate text as read, normalized plate text
- Face audit metadata: `model_name`, `model_version`, `match_metric` (`cosine`),
  `threshold_used`, `match_score`

No image is stored at any point. Unmatched sightings are recorded as unmatched rather than
dropped.

The face audit metadata exists to make a live match explainable while it is being disputed
at the gate. Because the row dies within 24–25 hours, it is not a calibration dataset.

### Credential rotation and revocation

**Rotation has a grace period.** Issuing a replacement credential sets the previous
credential's `expires_at` to `now + GATE_CREDENTIAL_ROTATION_GRACE_HOURS` (default 24).
Both credentials authenticate during the overlap, so a device is reconfigured without a
lockout window. Setting the grace to `0` makes rotation invalidate the old token
immediately.

**Revocation is always immediate and has no grace.** It sets `revoked_at = now`, and the
credential fails authentication on the next request. Rotation is for planned key hygiene;
revocation is for a lost or compromised device, and a grace period on a compromised device
would defeat the point.

### Retention and purge

`GATE_EVENT_RETENTION_HOURS = 24`, configurable — not hard-coded.

An hourly job deletes every `GateEvent` row where
`occurred_at < now - GATE_EVENT_RETENTION_HOURS`. Rows are deleted whole. Nothing is
nulled-out, anonymized, or archived: the matched-person reference, matched-plate reference,
raw and normalized plate text, match score, model/version/threshold metadata, device
reference, direction, and all timestamps go with the row. No cascading or related record
retains enough to reconstruct an expired person-level event.

**Practical deletion window: 24–25 hours.** An event becomes eligible for deletion at
`occurred_at + 24h` and is deleted at the next hourly run, so a row lives at most 24 hours
plus up to one hour. The system does not claim exactness the schedule cannot deliver.
Lowering `GATE_EVENT_RETENTION_HOURS` shifts the window; the extra hour is a property of
hourly scheduling, not of the retention value.

No aggregate operational metrics are retained in MVP. The constraint that they be
untraceable to any resident, vehicle, device event, or individual timestamp leaves too
little to be worth designing now.

**Purge mechanism.** One management command, `purge_gate_data`, run hourly by cron or a
systemd timer — the way `evidence/worker.py` is already operated. It handles two expiries
through two separate queries against two separate settings:

1. `GateEvent` rows past `GATE_EVENT_RETENTION_HOURS`
2. `PendingEnrollmentPhoto` objects past `GATE_ENROLLMENT_PHOTO_TTL_HOURS`

### Pending enrollment expiry

Photo expiry is a state transition, not a cleanup detail. A manager cannot approve a face
they can no longer see.

When a `PendingEnrollmentPhoto` passes `expires_at` without a decision, the purge job:

1. Deletes the stored photo object and its row
2. Deletes the **unapproved embedding** on the associated `FaceEnrollment`
3. Sets that enrollment's `status` to `expired`

The resident must resubmit. An unreviewed embedding is never retained past the photo that
justified it — the two are deleted in the same transaction.

On an approve or reject decision the photo object and row are deleted immediately, within
the same transaction that records the decision. On rejection the embedding is deleted too;
on approval it is retained and activated.

### Settings

| Setting | Default | Purpose |
|---|---|---|
| `GATE_EVENT_RETENTION_HOURS` | `24` | Event retention |
| `GATE_ENROLLMENT_PHOTO_TTL_HOURS` | `72` | Review photo TTL |
| `GATE_CREDENTIAL_ROTATION_GRACE_HOURS` | `24` | Overlap on rotation; `0` = immediate |
| `GATE_FACE_MATCH_THRESHOLD` | `0.38` | Cosine similarity threshold |

The match threshold is a setting rather than a constant because it is the knob that will
actually be tuned against real lighting at a real gate. `0.38` is a starting point for an
ArcFace-family model, not a validated value; calibration against the pilot building's
readers is expected to move it.

## Security assumptions

- **No liveness or anti-spoofing detection. Out of MVP.** A printed photo or a phone screen
  held to the reader will match. This is tolerable *only* because the system logs and never
  authorizes — nothing opens. If an access-control decision is ever added, liveness stops
  being optional and this assumption must be revisited first.
- The single-face check at enrollment is an **image-quality gate**: exactly one detectable
  face, minimum resolution, blur threshold. It establishes that the image is usable. It is
  **not** identity assurance and **not** liveness, and must not be described or relied on as
  either. Identity assurance in MVP comes from exactly one place: a named manager comparing
  the pending photo against the resident record.
- Plate OCR runs on the reader device, so a compromised reader can post any string. The
  credential authenticates the *device*, not the read. Events record what a device claimed.
- The server never accepts a client-computed embedding. Only images are accepted, and
  embedding always happens server-side.
- Matching is scoped to the device's building.
- Embeddings are Fernet-encrypted with a key from settings. Database compromise *combined
  with* key compromise exposes biometric identifiers.

## Surfaces

Three consumers, three API groups. They share models and nothing else.

### Resident app

New `app/lib/features/gate/`, entered from the existing account screen.

One screen lists the resident's vehicles and face status. Each row shows pending, approved,
rejected with reason, or expired-please-resubmit.

Adding a plate is a text field showing the normalized form as the resident types, so they
see `51F12345` and know the dots and dashes do not matter.

Face enrollment uses the `image_picker` camera already in `app/pubspec.yaml`, uploaded
through the same multipart path `ReportPhotoSerializer` uses
(`src/lamto/api/serializers.py:231`), inheriting ClamAV scanning.

After submit, the screen states that the photo is held for review and deleted once a manager
decides. Stating retention to the person it is about is the cheapest trust mechanism
available.

Endpoints under `/api/gate/`, knox-authenticated with the `X-LamTo-Occupancy` header the
rest of the resident API already uses:

- `GET /registrations`
- `POST /plates`, `DELETE /plates/{id}`
- `POST /face`, `DELETE /face`

Both deletes are resident-initiated revocation and drop the underlying row, embedding
included.

### Management workspace

`/s/gate/`, following existing staff templates.

**Pending queue** (primary screen) — the enrollment photo, the resident's name and unit
from their occupancy, approve or reject with a required reason on reject, decision
attributed to the named manager. This is the only identity check in the system, so the
screen is built for that one comparison and nothing else.

**Registrations** — approved plates and faces, with revoke.

**Readers** — register a device with its direction, issue a credential shown exactly once,
rotate, revoke.

**Live log** — labelled as a rolling 24-hour view, not a search interface. There is no date
filter because there is nothing older to filter for. Unmatched sightings appear as
"unrecognized" rather than being hidden.

### Gate reader

A screen in the same Flutter app, invisible until a device credential is entered, stored in
the existing secure `token_store`.

Camera preview showing the device's configured direction. Plate mode runs ML Kit text
recognition on-device and posts the string. Face mode captures and uploads the frame. The
result is a large pass/fail card: name and unit, or "not recognized".

`POST /api/gate/recognize` authenticates with the device credential, not a user session, and
is the endpoint real hardware will call later unchanged. It returns the matched resident's
display name, unit label, and match score — deliberately, since telling the guard who this
is *is* the feature. It is rate-limited per device. A failed credential is rejected without
revealing whether the device exists.

## Error handling

**Enrollment failures are resident-facing**, so they state what happened and whether
anything was saved. No detectable face, more than one face, too small, too blurry — each is
a distinct machine code keyed to Vietnamese copy in the app, never a server-supplied display
string. The photo is not stored on a quality failure. A ClamAV hit rejects outright. If the
model is unavailable the submission returns 503 and stores nothing rather than
half-committing.

A plate already approved in the building returns a conflict telling the resident to contact
management. It **does not reveal which unit holds it** — staff see the collision; the
resident does not get a lookup oracle.

**At the gate, "not recognized" is a result, not an error.** Below-threshold matches return
`matched: false` and are logged as an unrecognized sighting.

Genuine errors are distinct:

- No face in the frame — fast 422, reader shows "try again"
- Model outage — 503, reader shows "reader offline", and **no event is written**, because a
  failed read is not a sighting
- Revoked credential — a different code from an expired one, so a guard sees "this device
  was revoked" rather than debugging a network problem

There is no offline queue. A read that cannot reach the server is lost. Queueing captured
frames on a phone is precisely what this design spent its budget avoiding.

**Purge failure is a retention breach and cannot fail quietly.** The hourly command exits
non-zero and writes a heartbeat timestamp to the existing ops health surface alongside
`BackupMarker`. If the last successful purge is older than two hours, that surface says so.
A bare timestamp of a successful job run identifies nobody.

## Testing

Existing pytest-django setup.

The face embedder is injected through a Protocol, the way `evidence/chain.py` does
`default_client`. Tests bind a fake mapping fixed image bytes to canned vectors:
deterministic thresholds, no 100MB model in CI. The real model gets one opt-in test behind
a marker.

Tests that matter:

- Threshold boundary, just above and just below
- Building scoping — a resident of building A is not matched at building B's reader
- Rotation grace keeps the old credential alive; revocation kills it immediately
- Rotation with grace `0` invalidates the old credential immediately
- Photo TTL expiry moves the enrollment to `expired`, deletes the photo, and deletes the
  unapproved embedding
- An approve or reject decision deletes the photo object and row in the same transaction
- Duplicate approved plate returns a conflict without revealing the holding unit
- ClamAV rejection stores nothing

**The purge test is the important one.** It advances the clock past the boundary, runs the
command, and asserts not only that the event is gone but that no row anywhere in the
database still references it — including an explicit assertion that the `audit` app holds
nothing about gate events. A second case asserts the 24–25 hour window: an event at 24.5
hours is gone after the next hourly run, and an event at 23 hours is not.

One end-to-end acceptance test: enroll, approve, recognize, see the event, advance the
clock, purge, gone.

## Out of MVP

- Liveness and anti-spoofing detection
- Household members without app accounts — requires its own consent and authority
  lifecycle: how a non-user proves agreement, who holds enrolling authority, how consent is
  withdrawn without an account, and what happens when the enrolling resident moves out.
  `enrolled_by` alone is not consent. When designed, `RegisteredPerson` returns as a
  migration and `FaceEnrollment` moves off `ResidentOccupancy`.
- Visitors and temporary passes
- Any access-control decision or gate hardware integration
- Residents viewing their own entry/exit log
- Aggregate operational metrics
