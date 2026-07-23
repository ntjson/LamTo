# Task 5 Report

## Files

- `app/lib/features/home/home_screen.dart`
- `app/lib/features/notifications/notifications_screen.dart`
- `app/lib/features/account/account_screen.dart`
- `app/lib/l10n/app_en.arb`
- `app/lib/l10n/app_vi.arb`
- `app/lib/l10n/app_localizations.dart`
- `app/lib/l10n/app_localizations_en.dart`
- `app/lib/l10n/app_localizations_vi.dart`
- `app/test/announcement_home_test.dart`
- `app/test/home_screen_test.dart`
- `app/test/notifications_screen_test.dart`
- `app/test/account_screen_test.dart`

## TDD Evidence

Red command:

`cd app && flutter test test/announcement_home_test.dart test/home_screen_test.dart test/notifications_screen_test.dart test/account_screen_test.dart`

Red result: failed as expected because `latestAnnouncementProvider`, the shared `AlertDialog`, and the building-announcement preference label were absent.

Final commands and results:

- `cd app && flutter gen-l10n`: completed successfully using `l10n.yaml`.
- `cd app && flutter test test/announcement_home_test.dart test/home_screen_test.dart test/notifications_screen_test.dart test/account_screen_test.dart`: 19 tests passed.
- `cd app && flutter analyze`: no issues found.

## Behavior

- Home requests the newest unread `building.announcement` through the existing authenticated repository and displays it before the fund summary.
- Opening the highlight marks it read, refreshes home and inbox providers, opens full content in the shared dialog, and advances to the next server-returned unread delivery.
- Edited unread deliveries resurface with current content; absent withdrawn deliveries disappear without client-side state.
- The inbox uses the same dialog for feed-only announcement links, marks them read, and retains them in the feed.
- Account preferences expose a server-default-on, user-toggleable building-announcement push preference.
- Existing four destinations remain unchanged.

## Self-review

- Compact 320px layout at 2x text scaling passes without overflow; the highlight uses wrapping platform text roles and a native 64dp list target.
- The single tonal `Card.filled` highlight does not introduce a card stack or a new component vocabulary.
- Theme color roles, `AlertDialog`, `ListTile`, and `Switch.adaptive` preserve dark-mode and Material/Cupertino behavior.
- Full body content scrolls in the dialog; no fixed text sizes or raw colors were added.

## Commit

`feat: show building announcements in resident app`

## Concerns

None. Dependency tooling reported newer incompatible package versions, but focused tests and analysis were clean.
