# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 SuperHouse Automation Pty Ltd <info@superhouse.tv>
from django.test import SimpleTestCase

from .serial_number import extract_serial_number


class ExtractSerialNumberTest(SimpleTestCase):
    def test_bare_barcode_scan_is_returned_unchanged(self):
        self.assertEqual(extract_serial_number('12345', 'https://d.superlab.au/'), '12345')

    def test_qr_code_scan_strips_configured_url_stem(self):
        self.assertEqual(
            extract_serial_number('https://d.superlab.au/12345', 'https://d.superlab.au/'), '12345'
        )

    def test_strips_leftover_leading_slash_when_stem_has_no_trailing_slash(self):
        self.assertEqual(
            extract_serial_number('https://d.superlab.au/12345', 'https://d.superlab.au'), '12345'
        )

    def test_blank_url_stem_returns_raw_input_unchanged(self):
        self.assertEqual(extract_serial_number('https://d.superlab.au/12345', ''), 'https://d.superlab.au/12345')

    def test_input_not_matching_stem_is_returned_unchanged(self):
        self.assertEqual(
            extract_serial_number('https://other-vendor.example/12345', 'https://d.superlab.au/'),
            'https://other-vendor.example/12345',
        )

    def test_surrounding_whitespace_is_stripped(self):
        self.assertEqual(extract_serial_number('  12345  ', 'https://d.superlab.au/'), '12345')
