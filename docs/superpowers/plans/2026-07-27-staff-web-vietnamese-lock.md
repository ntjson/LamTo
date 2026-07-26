# Staff Web Vietnamese Lock Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Management workspace render Vietnamese for every manager regardless of browser language, and make English unable to creep back in unnoticed.

**Architecture:** The workspace is already fully translated — the leak is `LocaleMiddleware` negotiating against `LANGUAGES = [vi, en]`, so an English browser resolves `en` and renders the English msgids. Removing `en` from `LANGUAGES` closes header, cookie, and session negotiation in one line. Three pytest guards then hold the line: the lock itself, catalog completeness, and catalog currency. Six domain error strings that were never wrapped in `gettext` are wrapped last, driven red-green by the currency guard.

**Tech Stack:** Django 5.2, Python 3.12, pytest + pytest-django, gettext `.po`/`.mo` catalogs, `uv` for dependency management.

## Global Constraints

- English msgids remain the translation source. Do not replace them with Vietnamese literals.
- `LocaleMiddleware` stays in `MIDDLEWARE`. Do not remove it.
- No new declared dependencies. `polib` is used ad-hoc via `uv run --with polib` only.
- Guards must use the standard library only, so they run in any environment.
- Do not touch `src/lamto/maintenance/reporting.py` or `src/lamto/maintenance/ratings.py`. Those are resident-API only and explicitly out of scope.
- Do not touch the six `ValidationError`s in `src/lamto/evidence/services.py`. Explicitly excluded by the spec.
- Do not modify the 21 test files that use `@override_settings(LANGUAGE_CODE="en")` or `translation.override("en")`. They keep passing untouched.

### Running tests

`pyproject.toml` sets `testpaths = ["tests"]`, so a bare `pytest` will **not** pick up tests under `src/`. Always pass the path explicitly. Settings read required environment variables, so source `.env` first.

Database-backed tests additionally need the owner role. `.env` ships `POSTGRES_USER=lamto_writer`, which has `NOCREATEDB` and fails test-database creation with `psycopg.errors.InsufficientPrivilege: permission denied to create database`. `.env:16` records the override; `ops/postgres-init.sql` grants `CREATEDB` to `lamto_owner` only. Use this preamble for every test command in this plan:

```bash
set -a; . ./.env; set +a
export POSTGRES_USER=lamto_owner POSTGRES_PASSWORD=lamto-owner
```

Postgres and MinIO must be up (`docker compose ps` should show `db` healthy). The pure-settings tests in Task 1 and Task 2 are `SimpleTestCase` and need no database, but the preamble is harmless for them.

All commands below assume this preamble has been run in the shell.

---

### Task 1: Lock the language to Vietnamese

Removes English from negotiation and repairs the only two tests that depended on it.

**Files:**
- Create: `src/lamto/config/tests/test_locale.py`
- Modify: `src/lamto/config/settings.py:147-156`
- Modify: `src/lamto/web/tests/test_fund_ops.py:6,132,141,142,144,152,176,184,185,186,187`
- Modify: `src/lamto/web/tests/test_staff_bills.py:262,268,269`

**Interfaces:**
- Consumes: nothing.
- Produces: `src/lamto/config/tests/test_locale.py` containing `class LocaleLockTests(SimpleTestCase)`. Task 2 adds two more test classes to this same file.

- [ ] **Step 1: Write the failing guard**

Create `src/lamto/config/tests/test_locale.py`:

```python
"""Guards that keep the staff workspace Vietnamese.

The workspace is fully translated, so the historical leak was never a missing
msgstr — it was LocaleMiddleware negotiating against LANGUAGES=[vi, en] and
resolving `en` for an English browser, which renders the English msgids.
"""

from django.conf import settings
from django.test import SimpleTestCase
from django.utils.translation import get_language_from_request


class _FakeRequest:
    def __init__(self, *, accept_language=None, cookie=None):
        self.META = {}
        if accept_language is not None:
            self.META["HTTP_ACCEPT_LANGUAGE"] = accept_language
        self.COOKIES = {}
        if cookie is not None:
            self.COOKIES[settings.LANGUAGE_COOKIE_NAME] = cookie
        self.session = {}

    def get_full_path(self):
        return "/s/"


class LocaleLockTests(SimpleTestCase):
    def test_only_vietnamese_is_offered(self):
        assert [code for code, _label in settings.LANGUAGES] == ["vi"]

    def test_language_code_is_vietnamese(self):
        assert settings.LANGUAGE_CODE == "vi"

    def test_english_browser_still_gets_vietnamese(self):
        request = _FakeRequest(accept_language="en-US,en;q=0.9")
        assert get_language_from_request(request) == "vi"

    def test_english_cookie_still_gets_vietnamese(self):
        request = _FakeRequest(cookie="en")
        assert get_language_from_request(request) == "vi"

    def test_no_header_gets_vietnamese(self):
        assert get_language_from_request(_FakeRequest()) == "vi"
```

- [ ] **Step 2: Run the guard to verify it fails**

```bash
set -a; . ./.env; set +a
export POSTGRES_USER=lamto_owner POSTGRES_PASSWORD=lamto-owner
uv run pytest src/lamto/config/tests/test_locale.py -q
```

Expected: FAIL. `test_only_vietnamese_is_offered` fails with `['vi', 'en'] != ['vi']`, `test_english_browser_still_gets_vietnamese` fails with `'en' != 'vi'`, and `test_english_cookie_still_gets_vietnamese` fails with `'en' != 'vi'`. The other two pass.

- [ ] **Step 3: Lock the language**

In `src/lamto/config/settings.py`, replace lines 147-156:

```python
# Internationalization
# https://docs.djangoproject.com/en/5.2/topics/i18n/
# Vietnamese-first product surface; English msgids remain the translation source.
#
# `en` is deliberately absent from LANGUAGES. LocaleMiddleware negotiates against
# this list, so listing `en` let an English browser (or an `en` language cookie)
# resolve to the untranslated msgids and render the whole workspace in English.
# With only `vi` available, negotiation has nowhere else to go. Do not add `en`
# back as a debugging convenience — use translation.override("en") in tests.

LANGUAGE_CODE = "vi"

LANGUAGES = [
    ("vi", "Tiếng Việt"),
]
```

- [ ] **Step 4: Run the guard to verify it passes**

```bash
set -a; . ./.env; set +a
export POSTGRES_USER=lamto_owner POSTGRES_PASSWORD=lamto-owner
uv run pytest src/lamto/config/tests/test_locale.py -q
```

Expected: PASS, 5 passed.

- [ ] **Step 5: Confirm exactly two test files broke**

```bash
uv run pytest src/lamto/web/tests -q -p no:randomly 2>&1 | tail -20
```

Expected: `5 failed, 131 passed`. This was dry-run during planning, so the failure list is exact:

```
FAILED test_fund_ops.py::FundHomeTests::test_fund_home_renders_chart_and_window_stats
FAILED test_fund_ops.py::FundHomeTests::test_fund_home_shows_balance_entries_and_pending
FAILED test_fund_ops.py::FundHomeTests::test_pending_proposals_render_once
FAILED test_fund_ops.py::FundHomeTests::test_verified_fund_rows_lead_with_record_state
FAILED test_staff_bills.py::test_bill_amounts_use_grouped_vnd_format
```

If anything else fails, stop and report — only these two files depended on English negotiation.

- [ ] **Step 6: Fix `test_fund_ops.py`**

`FundHomeTests._login` sets the `en` cookie for the whole class, so all its English assertions must move to Vietnamese.

Delete line 6, `from django.conf import settings`. It becomes unused — `override_settings` is imported separately on line 8 and every other `settings` reference in the file is that decorator.

Delete line 132 inside `FundHomeTests._login`:

```python
        self.client.cookies[settings.LANGUAGE_COOKIE_NAME] = "en"
```

Replace the nine English assertions across the four failing tests with their existing msgstrs from `locale/vi/LC_MESSAGES/django.po`:

```python
# test_fund_home_shows_balance_entries_and_pending (lines 141, 142, 144)
        self.assertContains(resp, "Quỹ bảo trì")           # Maintenance fund
        self.assertContains(resp, "Bút toán đã xác minh")  # Verified entries
        self.assertContains(resp, "Số dư đầu kỳ")          # Opening balance

# test_verified_fund_rows_lead_with_record_state (line 152)
        self.assertContains(resp, '<span class="task-action">Bút toán đã xác minh</span>')

# test_pending_proposals_render_once (line 176) — a bytes count, so encode
        self.assertEqual(resp.content.count("Chuẩn bị công bố".encode()), 1)

# test_fund_home_renders_chart_and_window_stats (lines 184-187)
        self.assertContains(resp, "Số dư đầu kỳ")   # Opening balance
        self.assertContains(resp, "Số dư cuối kỳ")  # Closing balance
        self.assertContains(resp, "Tổng thu")       # Total inflows
        self.assertContains(resp, "Tổng chi")       # Total outflows
```

Two details worth care. "Verified entries" and "Verified entry" share the msgstr "Bút toán đã xác minh"; the `<span class="task-action">` wrapper is what makes line 152 specific. And line 176 counts **bytes** against `resp.content`, so the Vietnamese needs `.encode()` — a bare `b"..."` literal cannot hold non-ASCII.

- [ ] **Step 7: Fix `test_staff_bills.py`**

Delete line 262 from `test_bill_amounts_use_grouped_vnd_format`:

```python
    client.cookies[settings.LANGUAGE_COOKIE_NAME] = "en"
```

Change the two assertions on lines 268-269 to the Vietnamese thousands separator:

```python
    assert b'<span class="task-amount">250.000 VND</span>' in listing.content
    assert b"250.000 VND" in detail.content
```

This is the format production actually renders. Verified: under `vi`, `intcomma(250000)` returns `'250.000'` because `USE_THOUSAND_SEPARATOR = True` and `NUMBER_GROUPING = 3` combine with the vi locale's `THOUSAND_SEPARATOR = "."`. The old comma assertion tested a rendering no manager ever saw.

Keep the `from django.conf import settings` import on line 8 — line 362 in `test_void_confirmation_renders_vietnamese_catalogue` still uses it. Leave that `vi` cookie line alone; it is redundant now but harmless and out of scope.

- [ ] **Step 8: Run both repaired files**

```bash
set -a; . ./.env; set +a
export POSTGRES_USER=lamto_owner POSTGRES_PASSWORD=lamto-owner
uv run pytest src/lamto/web/tests/test_fund_ops.py src/lamto/web/tests/test_staff_bills.py -q
```

Expected: PASS, no failures.

- [ ] **Step 9: Run the full suite**

```bash
set -a; . ./.env; set +a
export POSTGRES_USER=lamto_owner POSTGRES_PASSWORD=lamto-owner
uv run pytest src/lamto tests -q 2>&1 | tail -20
```

Expected: PASS. In particular the 21 English-asserting files stay green, because `override_settings(LANGUAGE_CODE="en")` and `translation.override("en")` both bypass negotiation.

- [ ] **Step 10: Commit**

```bash
git add src/lamto/config/settings.py src/lamto/config/tests/test_locale.py \
        src/lamto/web/tests/test_fund_ops.py src/lamto/web/tests/test_staff_bills.py
git commit -m "fix(i18n): lock the staff workspace to Vietnamese

LocaleMiddleware negotiated against LANGUAGES=[vi, en], so an English browser
or an en language cookie resolved to the untranslated msgids and rendered the
whole workspace in English. Drop en from LANGUAGES so negotiation has nowhere
else to go, and guard it.

Repairs the two tests that set an en cookie. test_staff_bills now asserts
250.000 VND, the format production actually renders under vi.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Catalog guards

Two guards that stop English returning through the catalog rather than through settings.

**Files:**
- Modify: `src/lamto/config/tests/test_locale.py`

**Interfaces:**
- Consumes: `src/lamto/config/tests/test_locale.py` from Task 1.
- Produces: module-level helpers `PO_PATH`, `po_entries(path)` returning `list[dict]` with keys `msgid: str`, `msgstr: str`, `fuzzy: bool`; and `TRANS_TAG` / `PY_CALL` compiled regexes. Task 3 relies on `CatalogCurrentTests` going red when a string is wrapped without a msgid.

- [ ] **Step 1: Add the catalog guards**

Append to `src/lamto/config/tests/test_locale.py`. Also add `import pathlib` and `import re` to the imports at the top of the file.

```python
PO_PATH = pathlib.Path(settings.LOCALE_PATHS[0]) / "vi" / "LC_MESSAGES" / "django.po"

# Source roots the guards scan. Tests and migrations are excluded: test files
# legitimately assert English msgids, and migrations carry frozen historical
# strings that are never rendered.
SRC_ROOT = pathlib.Path(settings.BASE_DIR)

TRANS_TAG = re.compile(r"""\{%\s*trans(?:late)?\s+(["'])(.+?)\1""")
# Longest-first alternation: `gettext` would otherwise shadow `gettext_lazy`.
# The trailing class allows `)`, `,`, `}` and `]` so a call nested in a dict or
# list literal is still matched — e.g. ValidationError({"field": _("...")}).
PY_CALL = re.compile(
    r"""\b(?:gettext_lazy|gettext|ngettext|_)\(\s*(["'])(.+?)\1\s*[,)}\]]"""
)


def po_entries(path):
    """Parse a .po file into entries, joining multi-line msgid/msgstr strings.

    Standard library only, deliberately: the guard must run wherever pytest
    runs, and this repository has no gettext toolchain installed.
    """
    entries = []
    current = {"msgid": "", "msgstr": "", "fuzzy": False}
    key = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            if current["msgid"] or current["msgstr"]:
                entries.append(current)
            current, key = {"msgid": "", "msgstr": "", "fuzzy": False}, None
            continue
        if line.startswith("#,") and "fuzzy" in line:
            current["fuzzy"] = True
            continue
        if line.startswith("#"):
            continue
        match = re.match(r'(msgid|msgstr|msgid_plural|msgstr\[\d+\])\s+"(.*)"$', line)
        if match:
            key = "msgstr" if match.group(1).startswith("msgstr") else "msgid"
            current[key] += match.group(2)
            continue
        if line.startswith('"') and line.endswith('"') and key:
            current[key] += line[1:-1]
    if current["msgid"] or current["msgstr"]:
        entries.append(current)
    return entries


class CatalogCompleteTests(SimpleTestCase):
    """Every msgid in the catalog has a Vietnamese translation."""

    def test_no_untranslated_or_fuzzy_entries(self):
        # The header entry has an empty msgid and carries metadata, not text.
        translatable = [e for e in po_entries(PO_PATH) if e["msgid"]]
        assert translatable, "catalog parsed as empty; the parser or path is wrong"
        broken = [
            e["msgid"] for e in translatable if not e["msgstr"] or e["fuzzy"]
        ]
        assert not broken, (
            f"{len(broken)} msgid(s) are untranslated or fuzzy and will render "
            f"English under vi: {broken[:5]}"
        )


class CatalogCurrentTests(SimpleTestCase):
    """Every translatable literal in the source has a msgid in the catalog.

    This catches the leak CatalogCompleteTests cannot: someone adds a
    {% trans %} tag or a _() call and never runs makemessages, so the string
    has no msgid at all and silently renders English under vi.

    Known limits, accepted: {% blocktrans %} blocks, calls split across lines,
    and strings built at runtime are not covered. Full coverage needs xgettext,
    which is not installed here. This is a deliberate 90% check, not a
    replacement for makemessages.
    """

    def _missing(self):
        msgids = {e["msgid"] for e in po_entries(PO_PATH)}
        missing = []
        for path in SRC_ROOT.rglob("*.html"):
            text = path.read_text(encoding="utf-8")
            for match in TRANS_TAG.finditer(text):
                if match.group(2) not in msgids:
                    missing.append((str(path), match.group(2)))
        for path in SRC_ROOT.rglob("*.py"):
            if "/tests/" in str(path) or "/migrations/" in str(path):
                continue
            text = path.read_text(encoding="utf-8")
            for match in PY_CALL.finditer(text):
                if match.group(2) not in msgids:
                    missing.append((str(path), match.group(2)))
        return missing

    def test_every_translatable_literal_has_a_msgid(self):
        missing = self._missing()
        assert not missing, (
            f"{len(missing)} translatable string(s) have no msgid and will render "
            f"English under vi. Add them to django.po and recompile django.mo. "
            f"First few: {missing[:5]}"
        )
```

- [ ] **Step 2: Run the guards**

```bash
set -a; . ./.env; set +a
export POSTGRES_USER=lamto_owner POSTGRES_PASSWORD=lamto-owner
uv run pytest src/lamto/config/tests/test_locale.py -q
```

Expected: PASS, 7 passed. Both new guards are green against the current tree — the catalog is already 834/834 translated with zero fuzzy entries, and every literal already has a msgid. They are characterisation guards, so there is no red phase to observe naturally.

- [ ] **Step 3: Prove each guard actually bites**

A guard that has never failed is not yet known to work. Break each one deliberately, confirm the failure, then revert.

Prove `CatalogCompleteTests` bites — append an untranslated entry to the catalog. Restore from a file copy rather than `git checkout`: the catalog is a long-lived working file and `git checkout` would silently discard any uncommitted translation work alongside the probe.

```bash
cp locale/vi/LC_MESSAGES/django.po /tmp/django.po.bak
printf '\nmsgid "Probe untranslated string."\nmsgstr ""\n' >> locale/vi/LC_MESSAGES/django.po
uv run pytest src/lamto/config/tests/test_locale.py::CatalogCompleteTests -q
```

Expected: FAIL, naming `Probe untranslated string.`. Then restore and confirm the restore was byte-exact:

```bash
cp /tmp/django.po.bak locale/vi/LC_MESSAGES/django.po
git diff --stat locale/vi/LC_MESSAGES/django.po   # expect no output
```

Prove `CatalogCurrentTests` bites — add a trans tag with no msgid. A new file needs no restore, just deletion:

```bash
printf '{%% load i18n %%}{%% trans "Probe missing msgid." %%}\n' > src/lamto/web/templates/web/staff/_probe.html
uv run pytest src/lamto/config/tests/test_locale.py::CatalogCurrentTests -q
```

Expected: FAIL, naming `Probe missing msgid.`. Then remove it:

```bash
rm src/lamto/web/templates/web/staff/_probe.html
```

- [ ] **Step 4: Confirm the tree is clean and guards are green again**

```bash
git status --porcelain locale/ src/lamto/web/templates/
set -a; . ./.env; set +a
export POSTGRES_USER=lamto_owner POSTGRES_PASSWORD=lamto-owner
uv run pytest src/lamto/config/tests/test_locale.py -q
```

Expected: `git status` shows no changes to `locale/` or the templates directory from the probes, and 7 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/lamto/config/tests/test_locale.py
git commit -m "test(i18n): guard catalog completeness and currency

CatalogCompleteTests fails on any untranslated or fuzzy msgid.
CatalogCurrentTests fails when a {% trans %} tag or _() call has no msgid at
all, which is the leak a completeness check cannot see. Standard library only,
so both run wherever pytest runs — this repository has no gettext toolchain.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Wrap the six reachable error strings

Six domain strings that stay English even under `vi` because they carry no msgid. Each is reachable by a manager through normal use and surfaces as a flash message via `messages.error(request, str(error))` or `"; ".join(error.messages)` in the web views.

**Files:**
- Modify: `src/lamto/finance/fund.py:69-71`
- Modify: `src/lamto/finance/integrity.py:1-14,141`
- Modify: `src/lamto/finance/models/ledger.py:65-67`
- Modify: `src/lamto/billing/services.py:124-126`
- Modify: `src/lamto/web/forms/staff.py:257`
- Modify: `src/lamto/accounts/mfa.py:88`
- Modify: `locale/vi/LC_MESSAGES/django.po`
- Modify: `locale/vi/LC_MESSAGES/django.mo`

**Interfaces:**
- Consumes: `CatalogCurrentTests` from Task 2, which drives the red-green cycle here.
- Produces: nothing later tasks depend on.

- [ ] **Step 1: Wrap all six strings**

`src/lamto/finance/fund.py` already imports `gettext_lazy as _`. Replace lines 69-71:

```python
        raise ValidationError(
            _("Fund evidence must be clean, safe, and in the fund building.")
        )
```

`src/lamto/finance/integrity.py` has no gettext import. Add it after line 5 (`from django.utils import timezone`):

```python
from django.utils.translation import gettext_lazy as _
```

Then replace line 141:

```python
            raise ValidationError(_("Published ledger entry does not exist."))
```

`src/lamto/finance/models/ledger.py` already imports `gettext_lazy as _`. Replace lines 65-67. Wrap the dict *value*, not the key:

```python
            raise ValidationError(
                {"recorded_at": _("Fund entries cannot be future-dated.")}
            )
```

`src/lamto/billing/services.py` already imports `gettext_lazy as _`. Replace lines 124-126:

```python
        raise BillActorError(
            _("Self-attested payment must be confirmed by the bill resident.")
        )
```

`BillActorError` is a plain `Exception` subclass, not a Django `ValidationError`, and `bill_views.py:188` renders it with `messages.error(request, str(error))`. That still works: `BaseException.__str__` calls `str()` on its single argument, which forces the lazy proxy against the language active at render time. Verified during planning.

`src/lamto/web/forms/staff.py` already imports `gettext_lazy as _`. Replace line 257:

```python
            raise ValidationError(_("User is required."))
```

`src/lamto/accounts/mfa.py` already imports `gettext_lazy as _`. Replace line 88:

```python
        raise ValidationError(_("Request is required."))
```

- [ ] **Step 2: Run the currency guard to verify it fails**

```bash
set -a; . ./.env; set +a
export POSTGRES_USER=lamto_owner POSTGRES_PASSWORD=lamto-owner
uv run pytest src/lamto/config/tests/test_locale.py::CatalogCurrentTests -q
```

Expected: FAIL, reporting 6 translatable strings with no msgid. This is Task 2's guard doing its job — the strings are now marked translatable but the catalog does not know them.

- [ ] **Step 3: Add the six msgids to the catalog**

Append to `locale/vi/LC_MESSAGES/django.po`. Translations follow the catalog's established terminology: *evidence* → "bằng chứng", *entry* → "bút toán", *ledger* → "sổ cái", *bill* → "hóa đơn", *resident* → "cư dân", and the "X is required." → "Cần X." pattern.

```po
msgid "Fund evidence must be clean, safe, and in the fund building."
msgstr "Bằng chứng quỹ phải sạch (đã quét an toàn) và thuộc tòa nhà của quỹ."

msgid "Published ledger entry does not exist."
msgstr "Bút toán sổ cái đã công bố không tồn tại."

msgid "Fund entries cannot be future-dated."
msgstr "Bút toán quỹ không được ghi ngày trong tương lai."

msgid "Self-attested payment must be confirmed by the bill resident."
msgstr "Thanh toán tự xác nhận phải do cư dân của hóa đơn xác nhận."

msgid "User is required."
msgstr "Cần có người dùng."

msgid "Request is required."
msgstr "Cần có yêu cầu."
```

The first mirrors the existing "Quotations must be clean, safe, and in the work-order building." → "Báo giá phải sạch (đã quét an toàn) và thuộc tòa nhà của công việc.", so the parenthetical gloss on "clean" stays consistent.

- [ ] **Step 4: Run both catalog guards to verify they pass**

```bash
set -a; . ./.env; set +a
export POSTGRES_USER=lamto_owner POSTGRES_PASSWORD=lamto-owner
uv run pytest src/lamto/config/tests/test_locale.py -q
```

Expected: PASS, 7 passed.

- [ ] **Step 5: Recompile the binary catalog**

`msgfmt` is not installed, so `django-admin compilemessages` cannot run. Compile with `polib`, fetched ephemerally so nothing is added to the project's dependencies:

```bash
uv run --with polib python -c "import polib; polib.pofile('locale/vi/LC_MESSAGES/django.po').save_as_mofile('locale/vi/LC_MESSAGES/django.mo')"
```

- [ ] **Step 6: Verify the new strings actually translate at runtime**

The `.po` is the source but the `.mo` is what Django reads. Confirm the recompile took:

```bash
set -a; . ./.env; set +a
export POSTGRES_USER=lamto_owner POSTGRES_PASSWORD=lamto-owner
uv run python -c "
import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'lamto.config.settings')
django.setup()
from django.utils import translation
probes = [
    'Fund evidence must be clean, safe, and in the fund building.',
    'Published ledger entry does not exist.',
    'Fund entries cannot be future-dated.',
    'Self-attested payment must be confirmed by the bill resident.',
    'User is required.',
    'Request is required.',
]
with translation.override('vi'):
    for p in probes:
        out = translation.gettext(p)
        assert out != p, f'NOT TRANSLATED: {p}'
        print('ok:', out)
"
```

Expected: six `ok:` lines with Vietnamese text, no assertion error. If a string comes back unchanged, the `.mo` did not recompile — rerun Step 5.

- [ ] **Step 7: Run the suites covering the touched modules**

```bash
set -a; . ./.env; set +a
export POSTGRES_USER=lamto_owner POSTGRES_PASSWORD=lamto-owner
uv run pytest src/lamto/finance src/lamto/billing src/lamto/accounts src/lamto/web -q 2>&1 | tail -20
```

Expected: PASS. Watch for tests asserting these six strings in English — none were found during planning, but if one appears it will be in a file using `override_settings(LANGUAGE_CODE="en")`, where the English msgid still resolves and the test should still pass.

- [ ] **Step 8: Run the full suite**

```bash
set -a; . ./.env; set +a
export POSTGRES_USER=lamto_owner POSTGRES_PASSWORD=lamto-owner
uv run pytest src/lamto tests -q 2>&1 | tail -20
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add src/lamto/finance/fund.py src/lamto/finance/integrity.py \
        src/lamto/finance/models/ledger.py src/lamto/billing/services.py \
        src/lamto/web/forms/staff.py src/lamto/accounts/mfa.py \
        locale/vi/LC_MESSAGES/django.po locale/vi/LC_MESSAGES/django.mo
git commit -m "fix(i18n): translate the six reachable staff error strings

These carried no msgid, so they stayed English even under vi. Each is
reachable by a manager and surfaces as a flash message through
messages.error(request, str(error)).

Excludes evidence/services.py, whose ValidationErrors validate system-built
anchoring payloads and can only fire on a bug.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Manual verification

After Task 3, confirm the original symptom is gone:

- [ ] Start the app and load `/s/` from a browser whose language is set to English.
- [ ] Confirm the navigation, Action Inbox, and fund pages render Vietnamese.
- [ ] Trigger a validation error — for example submit the fund entry form with a future date — and confirm the flash message is Vietnamese.

## Out of scope, recorded for later

- The ~18 English strings in `src/lamto/maintenance/reporting.py` and `src/lamto/maintenance/ratings.py`. Imported only by `api/views.py`, so they reach the resident app rather than the staff web. `PRODUCT.md` positions the resident app as Vietnamese-only, so these will want doing eventually.
- The six `ValidationError`s in `src/lamto/evidence/services.py`. Two are f-strings needing `%`-formatting conversion before gettext can see them.
- `{% blocktrans %}` coverage in `CatalogCurrentTests`, which needs `xgettext`.
- Nothing enforces that the committed `.mo` matches the `.po`. Pre-existing.
