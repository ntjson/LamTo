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
