# Resident Registration and Building Announcements Design

Date: 2026-07-23

## Summary

LamTo will add two building-scoped workflows:

1. A first-time resident submits an account registration request from the
   Flutter app, selects a building and unit, and waits for that building's
   management committee to approve or reject the request.
2. A management committee member publishes building-wide announcements that
   appear in the resident app and optionally generate push notifications.

The design adds one focused domain record for each workflow and reuses LamTo's
existing `User`, `ResidentOccupancy`, management membership, notification feed,
push delivery, audit, MFA, and building-isolation mechanisms.

## Goals

- Let a new resident request an account without management creating it first.
- Let management manually verify the claimed building and unit.
- Keep pending and rejected applicants out of the real user table.
- Make registration status available in the submitting app without email.
- Let any active management member publish, edit, or withdraw announcements for
  their current building.
- Make announcements prominent on Home while preserving the existing
  notification inbox as history.
- Preserve building isolation, auditability, idempotency, and push retry
  behavior.

## Non-goals

- Existing residents requesting another unit or building.
- Invitation codes or pre-imported resident rosters.
- Registration document uploads.
- Registration status recovery after the app is reinstalled or moved to
  another device.
- Announcement drafts, scheduling, attachments, email delivery, audience
  targeting, or mandatory push.
- A generic approval-workflow or broadcast-campaign framework.

## Existing foundations

- `User` supports phone-or-email authentication.
- `ResidentOccupancy` links a resident to a unit and building.
- `ManagementMembership` supplies one active management role scoped to a
  building.
- The management website already enforces authentication, MFA, current-building
  selection, and cross-building denial.
- `NotificationDelivery` supplies building-scoped in-app, email, and push
  delivery with per-recipient read state, retries, and dead-letter handling.
- The Flutter app already has a Home screen, notification inbox, notification
  preferences, secure storage, and push deep links.

## Domain model

### RegistrationRequest

Add a `RegistrationRequest` record with:

- selected `building` and `unit`, protected by a database-level relationship
  requiring the unit to belong to the building;
- `display_name`;
- normalized, required `phone`;
- normalized, nullable `email`;
- Django `password_hash`, never plaintext;
- a SHA-256 digest of an unguessable status token;
- status: `PENDING`, `APPROVED`, `REJECTED`, or `EXPIRED`;
- `submitted_at`, `expires_at`, and `decided_at`;
- nullable `decided_by`;
- nullable `approved_user`;
- `rejection_reason`, required only for rejection.

Database constraints allow only one pending request per normalized phone and
one per non-null normalized email. Approval still rechecks the corresponding
`User` uniqueness constraints inside its transaction.

Pending requests expire after 30 days. Approval copies the password hash to the
new user and clears it from the request. Rejection and expiry also clear the
hash.

### User changes

Residents are phone-first:

- `User.phone` remains normalized, required for registrations, and unique.
- `User.email` becomes nullable and remains unique when present.
- `UserManager.create_user` accepts a phone-only resident while retaining
  email-based creation for existing callers. Management onboarding and
  `create_superuser` continue to require email.
- The existing phone-or-email authentication backend continues to accept
  either identifier.

### Announcement

Add an `Announcement` record with:

- `building`;
- `title`, limited to 160 characters;
- plain-text `body`, limited to 2,000 characters;
- `revision`, starting at 1;
- state: `PUBLISHED` or `WITHDRAWN`;
- `created_by`, `created_at`, and `published_at`;
- nullable `updated_by` and `updated_at`;
- nullable `withdrawn_by` and `withdrawn_at`.

The record holds the current content. Immutable audit events record publication,
each edit revision, and withdrawal with the responsible management member and
timestamp.

## Registration API and app flow

### Public API

Add three unauthenticated endpoints:

- `GET /api/v1/registration/options` returns configured building names and
  unit labels only.
- `POST /api/v1/registration-requests` accepts display name, phone, optional
  email, password, building ID, and unit ID.
- `GET /api/v1/registration-requests/status` requires the private status token
  in an `X-Registration-Status-Token` header.

Submission:

1. Normalize and validate the phone and optional email.
2. Apply the existing password validators.
3. Verify that the selected unit belongs to the selected building.
4. Reject an existing user or duplicate pending request with one generic
   conflict response.
5. Apply configurable throttles, defaulting to five attempts per normalized
   phone and five attempts per client IP in 15 minutes.
6. Hash the password and create the pending request.
7. Return the private status token once.

The status endpoint returns only `pending`, `approved`, `rejected`, or
`expired`, plus the rejection reason when rejected. A request ID alone cannot
retrieve status.

### Flutter app

The login screen gains a "Register an account" action. The form collects:

- full name;
- required phone;
- optional email;
- password and confirmation;
- building;
- unit filtered by the selected building.

After submission, the app stores the private status token in its existing
secure-storage facility. It does not retain the plaintext password.

The status screen refreshes when opened, when the app resumes, and when the
resident explicitly retries. It does not poll continuously in the background.

- `PENDING`: show that committee review is required.
- `APPROVED`: show a "Go to login" action with the phone prefilled; the resident
  re-enters the chosen password.
- `REJECTED`: show the required reason and offer a new registration form.
- `EXPIRED`: explain that a new request is required.
- Offline or server failure: keep the last known state and show a retry action.

Per the chosen device-only behavior, losing app storage loses pending or
rejected status access. An approved resident can still log in normally.
A lost-device applicant with a still-pending request cannot submit another
request with the same phone until management decides it or it expires.

## Registration management flow

Add a building-scoped registration queue to the management website. Pending
registrations also appear as actionable items in the existing Inbox.

Any active management member for the current building may inspect and decide a
request.

### Approval

Approval runs in one transaction:

1. Lock the registration request.
2. Confirm it is still pending and not expired.
3. Recheck the manager's active membership and request building.
4. Recheck normalized phone and optional email uniqueness.
5. Create the `User` with the stored password hash.
6. Create an active `ResidentOccupancy` for the selected unit.
7. Mark the request approved, link the user, record the actor/time, and clear
   the request password hash.
8. Append an immutable audit event.

### Rejection

Rejection requires a non-blank reason. It locks and rechecks the pending
request, records the actor/time and reason, clears the password hash, and
appends an audit event.

The first concurrent decision wins. A stale second decision receives a conflict
response and reloads the final state.

## Announcement management flow

Add an Announcements area to the building-scoped management website.

The list shows current content, published or withdrawn state, revision,
timestamps, and responsible committee members. A form accepts a title and
plain-text message and publishes immediately.

Any active management member for the current building may:

- publish an announcement;
- edit a published announcement, incrementing its revision;
- withdraw a published announcement after confirmation.

Published announcements are not silently overwritten. Each action is
attributed and audited. Withdrawn announcements remain visible in management
history but cannot be edited or republished; a replacement requires a new
announcement.

## Announcement delivery

Use the event code `building.announcement`. It is a resident push-eligible
event and appears as "Building announcements" in notification preferences.
In-app delivery is mandatory. Push defaults to enabled and may be disabled by
the resident. Email is never queued for this event.

Recipients are distinct active users with at least one active occupancy in the
announcement's building. Multiple occupancies do not create duplicates.

Announcement state changes and their notification rows are written atomically.
No external push provider call occurs inside that transaction.

### Publish

- Create one stable `IN_APP` delivery per recipient using an event key tied to
  the announcement ID.
- Create a `PUSH` delivery for push-enabled recipients using a revision- and
  action-specific event key.

### Edit

- Increment the announcement revision.
- Update each existing in-app delivery's title and body.
- Mark those in-app deliveries unread so the announcement resurfaces on Home.
- Create in-app deliveries for residents who became active after publication.
- Create new revision-specific "updated" push deliveries for currently active,
  push-enabled residents.

### Withdraw

- Mark the announcement withdrawn.
- Hide its in-app deliveries from Home and the inbox.
- Create revision-specific "withdrawn" push deliveries for currently active,
  push-enabled residents.

Push event keys make publication, every edit, and withdrawal independently
idempotent. Existing retry and dead-letter processing handles provider failure.
A push failure does not affect the authoritative announcement or its in-app
availability.

Push payloads follow the existing privacy rule: the operating system sees
generic Vietnamese copy such as "Có thông báo mới từ ban quản lý", "Thông báo
tòa nhà đã được cập nhật", or "Thông báo tòa nhà đã được thu hồi". The full
title and body are read inside the authenticated app.

## Resident announcement experience

Extend the existing notification list API with optional `event_code` and
`unread` filters. Home requests the newest unread `building.announcement`
delivery.

- Home highlights the newest unread, non-withdrawn announcement.
- Opening it uses the existing mark-read endpoint and removes that highlight.
- If another unread announcement exists, it becomes the next highlight.
- The opened announcement remains in the notification inbox.
- An edit marks the item unread and resurfaces it.
- A withdrawal removes the item from Home and the inbox.

The notification inbox remains the complete resident-visible announcement
history except for withdrawn items. The existing four-tab navigation remains
unchanged.

## Security and error handling

- Public registration options contain no resident or management data.
- Passwords and raw status tokens are excluded from logs, audit metadata, and
  subsequent API responses.
- Status tokens have sufficient entropy, are compared by digest, and are sent
  in a header rather than a URL.
- Registration validation uses the project's standard
  `application/problem+json` responses.
- Database constraints are the final duplicate defense.
- Management actions reuse existing authentication, MFA, and active-building
  checks.
- Every server-side management action rechecks building scope; UI filtering is
  not treated as authorization.
- Announcement delivery creation is transactional. Push sending is
  asynchronous and retryable.
- Repeated submissions and actions use stable idempotency or conflict behavior
  rather than creating duplicate accounts or notifications.

## Testing

Use the existing Django and Flutter test stacks.

### Backend

- Phone-only user creation and optional unique email.
- Phone/email normalization and login compatibility.
- Registration field validation, building/unit integrity, throttling, generic
  duplicate responses, and token hashing.
- Pending-request uniqueness, expiry, and password-hash cleanup.
- Atomic approval and rejection, required rejection reason, and concurrent
  decision behavior.
- Cross-building queue, detail, approval, and rejection denial.
- Announcement recipient deduplication and building isolation.
- Mandatory in-app delivery and preference-aware push without email.
- Publication, edit revision, unread reset, new-resident inclusion,
  withdrawal, and idempotent event keys.
- Transaction rollback, push retry, and dead-letter behavior.
- OpenAPI schema and standardized problem responses.

### Management website

- Active management members can act only in their selected building.
- Pending registrations appear in the Inbox and registration queue.
- Rejection requires a reason.
- Stale registration and announcement actions reload the final state safely.
- Announcement history displays state, revision, and actor attribution.

### Flutter

- Registration form validation and building/unit selection.
- Secure, device-local status persistence.
- Pending, approved, rejected, expired, offline, and retry states.
- Approved transition to phone-prefilled login.
- Home announcement highlighting and mark-read behavior.
- Resurfacing after an edit and removal after withdrawal.
- Notification inbox history and push deep links.
- Vietnamese and English strings and screen-reader semantics.

### End-to-end acceptance path

1. A resident submits a registration.
2. A committee member approves it from the management website.
3. The app observes approval and the resident logs in.
4. A committee member publishes an announcement.
5. The resident sees it on Home and in the inbox.
6. Opening it removes the Home highlight but preserves inbox history.
7. An edit resurfaces it and sends an updated push when enabled.
8. Withdrawal hides it and sends a withdrawal push when enabled.

## Deferred work

Add only when a concrete need appears:

- registration invitations or roster matching;
- registration recovery across devices;
- additional occupancy requests for existing users;
- announcement drafts, schedules, attachments, expiry, or audience segments;
- batched fan-out infrastructure beyond the current per-building scale.
