# Staff web: lock to Vietnamese

**Date:** 2026-07-27
**Status:** Approved, ready for implementation

## Problem

The Management workspace renders in English for any manager whose browser is
configured for English.

The cause is not missing translation. The workspace is already translated:
`LANGUAGE_CODE = "vi"`, 834 msgids in `locale/vi/LC_MESSAGES/django.po`, all of
them translated, no fuzzy entries. All 40 templates wrap their text in
`{% trans %}`; a scan for raw English text nodes and untranslated `placeholder`,
`title`, `aria-label`, and `alt` attributes returns nothing.

The cause is locale negotiation. `LocaleMiddleware` is active and
`LANGUAGES` lists both `vi` and `en`, so the browser decides. Verified against
the project settings:

```
Accept-Language: en-US,en;q=0.9  ->  en    # entire workspace renders English msgids
Accept-Language: vi              ->  vi
(no header)                      ->  vi
```

Because the English msgids *are* the source strings, resolving `en` renders the
whole workspace in English with no missing-translation error anywhere.

A second, much smaller source is domain-layer error strings that were never
wrapped in `gettext`. These stay English even under `vi`, because they carry no
msgid at all.

## Goals

- A manager sees Vietnamese regardless of browser, cookie, or session language.
- Error messages a manager can trigger are Vietnamese.
- English cannot creep back in unnoticed.

## Non-goals

- The resident app API (`maintenance/reporting.py`, `maintenance/ratings.py`,
  ~18 unwrapped strings). Those modules are imported only by `api/views.py` and
  never reach the staff web. Out of scope by decision.
- Removing gettext. English msgids remain the translation source, which is
  standard Django and keeps a second language possible later.
- Rewriting the 21 test files that assert English msgids. They keep passing
  untouched (see Testing).

## Design

### 1. Lock the language

`src/lamto/config/settings.py:153`:

```python
LANGUAGES = [("vi", "Tiếng Việt")]
```

`LocaleMiddleware` stays in the stack. With only `vi` available, negotiation
cannot resolve anything else — header, cookie, and session all dead-end.
Verified:

```
Accept-Language: en-US,en;q=0.9   ->  vi
Cookie django_language=en         ->  vi
override_settings(LANGUAGE_CODE)  ->  en   # still honoured
```

The last line matters: Django's final fallback in
`get_language_from_request` returns `settings.LANGUAGE_CODE` verbatim even when
it is not in `LANGUAGES`. That is what keeps the existing English-asserting
tests green.

Update the adjacent comment at `settings.py:147` to record that `en` was
removed deliberately, so nobody restores it as a convenience.

### 2. Wrap the reachable error strings

Six strings, six files. Each is reachable by a manager through normal use and
surfaces via `messages.error(request, str(error))` or
`"; ".join(error.messages)` in the web views.

| File:line | String |
| --- | --- |
| `finance/fund.py:69` | Fund evidence must be clean, safe, and in the fund building. |
| `finance/integrity.py:141` | Published ledger entry does not exist. |
| `finance/models/ledger.py:65` | Fund entries cannot be future-dated. |
| `billing/services.py:124` | Self-attested payment must be confirmed by the bill resident. |
| `web/forms/staff.py:257` | User is required. |
| `accounts/mfa.py:88` | Request is required. |

Wrap each in `_()`. Five of the six files already import
`gettext_lazy as _`; `finance/integrity.py` needs the import added.

`finance/models/ledger.py:65` raises a dict-form `ValidationError`
(`{"recorded_at": "..."}`); wrap the value, not the key.

Add the six msgids to `django.po` with Vietnamese translations and recompile
`django.mo`.

### Deliberately excluded

`evidence/services.py` (lines 76, 81, 84, 86, 90, 132) raises six
`ValidationError`s that are reachable from the staff web in principle but
validate payloads the system itself constructs during anchoring. They can only
fire on a programming error, and two are f-strings that would need
`%`-formatting conversion before gettext could see them. Translating assertions
produces text no reader will ever read.

Also excluded, all verified unreachable rather than merely unlikely:

- `PermissionDenied` messages throughout. `403.html` renders fixed text and
  never prints the exception message.
- `gate/plates.py:29`. `PlateFormatError` is caught in
  `api/gate_views.py:39` and replaced with `GatePlateUnreadable()`; the message
  never surfaces. The staff web only approves and declines plates.
- `staff.js:42,47,50` (`"Copied"`, `"Copy failed"`). These are `||` fallbacks.
  `base.html:39` and `staff/shell.html:108` already inject translated strings,
  so the fallbacks fire only if the template did not render.
- `CommandError` in management commands. CLI only.
- `ValueError` and `TypeError` guards. Never rendered.

### 3. Fix the two tests the lock breaks

Removing `en` from `LANGUAGES` breaks exactly two tests, both of which set an
`en` language cookie that now resolves to `vi`.

`src/lamto/web/tests/test_staff_bills.py:262` — drop the cookie line and assert
`250.000 VND`. The test currently asserts `250,000 VND`, comma-grouped, which is
the English rendering; production under `vi` uses `.` as the thousands
separator per `USE_THOUSAND_SEPARATOR` and `NUMBER_GROUPING` in settings. The
production format is currently untested, so this is a fidelity fix rather than
churn.

`src/lamto/web/tests/test_fund_ops.py:132` — drop the cookie line and translate
the three assertions (`Maintenance fund`, `Verified entries`, `Opening
balance`) to their Vietnamese msgstrs.

The other 21 English-asserting files use
`@override_settings(LANGUAGE_CODE="en")` or `translation.override("en")`. Both
bypass negotiation, so they keep passing unchanged and are left alone.

### 4. Guards

New file `src/lamto/config/tests/test_locale.py`, `SimpleTestCase` with plain
asserts, matching the style of the neighbouring `test_secrets.py`. No database.

**Guard A — the lock holds.** Assert `LANGUAGES` contains only `vi`, and that
`get_language_from_request` returns `vi` for both an `Accept-Language: en-US`
header and a `django_language=en` cookie. Clear `trans_real._accepted` between
cases; it caches header parsing across calls.

**Guard B — the catalog is complete.** Parse
`locale/vi/LC_MESSAGES/django.po` and fail on any untranslated or fuzzy entry.
Stdlib only, roughly 20 lines: split on blank lines, join continuation lines,
skip the header entry (`msgid ""`), flag `#, fuzzy`. No new dependency.

**Guard C — the catalog is current.** Regex-scan `src/**/*.html` for
`{% trans "X" %}` and `{% translate "X" %}`, and `src/**/*.py` (excluding
`tests/` and `migrations/`) for single-line `_("X")`, `gettext("X")`,
`gettext_lazy("X")`, and `ngettext("X")`. Assert every literal found exists as
a msgid in the `.po`.

Guard C catches the leak Guard B cannot: someone adds a `{% trans %}` and never
runs `makemessages`, so the string has no msgid and silently renders English
under `vi`. Prototyped against the current tree: 834 msgids, 0 missing, so it
lands green.

Guard C's known limits, accepted: it does not cover `{% blocktrans %}`,
multi-line calls, or strings built at runtime. Full coverage needs `xgettext`,
which is not installed here. Guard C is a deliberate 90% check, not a
replacement for `makemessages`.

### 5. Recompiling the catalog

`msgfmt` and the rest of the `gettext` toolchain are not installed, so
`django-admin compilemessages` cannot run. Recompile with:

```
uv run --with polib python -c "import polib; polib.pofile('locale/vi/LC_MESSAGES/django.po').save_as_mofile('locale/vi/LC_MESSAGES/django.mo')"
```

`uv` fetches `polib` ephemerally, so no dependency is declared. Verified
working against the current catalog.

This is a manual step, unchanged from how `django.mo` is maintained today. It is
not automated here because the repository has no Django CI — the two existing
workflows cover the Flutter app only.

## Testing

- The two amended tests pass.
- The three new guards pass.
- The existing suite passes, in particular the 21 untouched English-asserting
  test files.
- Manual check: load `/s/` with an English browser profile and confirm
  Vietnamese.

## Risks

**A manager genuinely needs English.** No longer possible without a code change.
Accepted: the product is Vietnamese-only for both surfaces per `PRODUCT.md`.

**Guard C false positives.** A legitimate new string trips the guard until
`makemessages` runs and the translation is written. That is the guard working,
but it does mean adding UI text now requires updating the catalog in the same
change.

**`.mo` drift.** Nothing enforces that the committed `.mo` matches the `.po`.
Guard B checks the `.po` only. Pre-existing, not introduced here.
