# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 SuperHouse Automation Pty Ltd <info@superhouse.tv>
from django.test import SimpleTestCase

from .avatar import get_avatar_color, get_gravatar_url, get_initials


class GetInitialsTest(SimpleTestCase):
    def test_two_word_name(self):
        self.assertEqual(get_initials('Jon Oxer', 'jon@example.com'), 'JO')

    def test_three_word_name_uses_first_and_last(self):
        self.assertEqual(get_initials('Jon Middle Oxer', 'jon@example.com'), 'JO')

    def test_single_word_name(self):
        self.assertEqual(get_initials('Cher', 'cher@example.com'), 'C')

    def test_no_name_falls_back_to_email(self):
        self.assertEqual(get_initials('', 'jon@example.com'), 'J')

    def test_no_name_or_email(self):
        self.assertEqual(get_initials('', ''), '?')


class GetGravatarUrlTest(SimpleTestCase):
    def test_hashes_and_normalises_email(self):
        # Same hash whether the email is mixed-case or has surrounding whitespace, matching
        # Gravatar's own case/whitespace-insensitive lookup.
        url = get_gravatar_url('Test@Example.com ')
        self.assertEqual(url, 'https://www.gravatar.com/avatar/55502f40dc8b7c769880b10874abc9d0?s=40&d=identicon')

    def test_custom_size(self):
        url = get_gravatar_url('test@example.com', size=80)
        self.assertIn('s=80', url)

    def test_no_email_returns_none(self):
        self.assertIsNone(get_gravatar_url(''))


class GetAvatarColorTest(SimpleTestCase):
    def test_deterministic_for_same_email(self):
        self.assertEqual(get_avatar_color('jon@example.com'), get_avatar_color('jon@example.com'))

    def test_different_for_different_emails(self):
        self.assertNotEqual(get_avatar_color('jon@example.com'), get_avatar_color('someone-else@example.com'))

    def test_no_email_returns_default_grey(self):
        self.assertEqual(get_avatar_color(''), '#6c757d')

    def test_returns_a_valid_hex_color(self):
        color = get_avatar_color('jon@example.com')
        self.assertRegex(color, r'^#[0-9a-f]{6}$')
