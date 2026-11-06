"""The upload scanner and its off switch (DOCUMENT_SCAN_BACKEND)."""

import io
from unittest import mock

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, override_settings

from lamto.documents import scanner


class ScanBackendTests(SimpleTestCase):
    @override_settings(DOCUMENT_SCAN_BACKEND="none")
    def test_with_scanning_off_every_file_passes_without_contacting_clamav(self):
        with mock.patch.object(scanner.socket, "create_connection") as connect:
            self.assertTrue(scanner.scan_with_clamav(io.BytesIO(b"anything")))
        connect.assert_not_called()

    @override_settings(DOCUMENT_SCAN_BACKEND="clamav", CLAMAV_HOST="127.0.0.1", CLAMAV_PORT="1")
    def test_with_clamav_on_an_unreachable_scanner_is_still_an_error(self):
        with mock.patch.object(
            scanner.socket, "create_connection", side_effect=ConnectionRefusedError
        ):
            with self.assertRaises(scanner.DocumentScanUnavailable):
                scanner.scan_with_clamav(io.BytesIO(b"anything"))

    @override_settings(DOCUMENT_SCAN_BACKEND="nope")
    def test_an_unknown_backend_is_refused(self):
        with self.assertRaises(ImproperlyConfigured):
            scanner.scan_with_clamav(io.BytesIO(b"anything"))
