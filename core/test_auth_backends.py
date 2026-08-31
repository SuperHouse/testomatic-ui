# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 SuperHouse Automation Pty Ltd <info@superhouse.tv>
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .auth_backends import RegisterAuthBackend
from .models import OperatorProfile
from .register_client import RegisterAPIError

User = get_user_model()

PROFILE = {'id': 5, 'email': 'op@example.com', 'full_name': 'Op Erator', 'avatar_type': 'gravatar', 'is_staff': True}


class RegisterAuthBackendTest(TestCase):
    def setUp(self):
        self.backend = RegisterAuthBackend()

    @patch('core.auth_backends.verify_operator')
    def test_register_success_creates_local_user_and_profile(self, mock_verify):
        mock_verify.return_value = PROFILE

        user = self.backend.authenticate(None, username='op@example.com', password='hunter2')

        self.assertIsNotNone(user)
        self.assertEqual(user.username, 'op@example.com')
        self.assertEqual(user.email, 'op@example.com')
        self.assertEqual(user.get_full_name(), 'Op Erator')
        self.assertTrue(user.is_staff)
        self.assertTrue(user.check_password('hunter2'))

        profile = OperatorProfile.objects.get(user=user)
        self.assertEqual(profile.register_user_id, 5)
        self.assertEqual(profile.full_name, 'Op Erator')
        self.assertEqual(profile.avatar_type, 'gravatar')

    @patch('core.auth_backends.verify_operator')
    def test_register_success_refreshes_cached_password(self, mock_verify):
        mock_verify.return_value = PROFILE
        self.backend.authenticate(None, username='op@example.com', password='old-password')

        mock_verify.return_value = {**PROFILE, 'full_name': 'Op Erator'}
        self.backend.authenticate(None, username='op@example.com', password='new-password')

        user = User.objects.get(username='op@example.com')
        self.assertTrue(user.check_password('new-password'))
        self.assertFalse(user.check_password('old-password'))

    @patch('core.auth_backends.verify_operator')
    def test_register_explicit_rejection_returns_none(self, mock_verify):
        mock_verify.side_effect = RegisterAPIError('Invalid email or password', status_code=401)

        user = self.backend.authenticate(None, username='op@example.com', password='wrong')

        self.assertIsNone(user)

    @patch('core.auth_backends.verify_operator')
    def test_register_non_staff_rejection_returns_none(self, mock_verify):
        mock_verify.side_effect = RegisterAPIError('User is not a staff member', status_code=403)

        user = self.backend.authenticate(None, username='customer@example.com', password='correct')

        self.assertIsNone(user)

    @patch('core.auth_backends.verify_operator')
    def test_explicit_rejection_does_not_fall_back_to_stale_local_cache(self, mock_verify):
        """A previously-cached password must never let someone back in once Register has
        explicitly said the credentials are no longer valid - only "unreachable" falls back."""
        mock_verify.return_value = PROFILE
        self.backend.authenticate(None, username='op@example.com', password='hunter2')

        mock_verify.side_effect = RegisterAPIError('Invalid email or password', status_code=401)
        user = self.backend.authenticate(None, username='op@example.com', password='hunter2')

        self.assertIsNone(user)

    @patch('core.auth_backends.verify_operator')
    def test_unreachable_with_no_local_cache_returns_none(self, mock_verify):
        mock_verify.side_effect = RegisterAPIError('Could not reach Register: timed out')

        user = self.backend.authenticate(None, username='op@example.com', password='hunter2')

        self.assertIsNone(user)

    @patch('core.auth_backends.verify_operator')
    def test_unreachable_falls_back_to_matching_local_cache(self, mock_verify):
        mock_verify.return_value = PROFILE
        self.backend.authenticate(None, username='op@example.com', password='hunter2')

        mock_verify.side_effect = RegisterAPIError('Could not reach Register: timed out')
        user = self.backend.authenticate(None, username='op@example.com', password='hunter2')

        self.assertIsNotNone(user)
        self.assertEqual(user.username, 'op@example.com')

    @patch('core.auth_backends.verify_operator')
    def test_unreachable_with_wrong_local_password_returns_none(self, mock_verify):
        mock_verify.return_value = PROFILE
        self.backend.authenticate(None, username='op@example.com', password='hunter2')

        mock_verify.side_effect = RegisterAPIError('Could not reach Register: timed out')
        user = self.backend.authenticate(None, username='op@example.com', password='totally-wrong')

        self.assertIsNone(user)

    @patch('core.auth_backends.verify_operator')
    def test_unreachable_falls_back_to_most_recently_synced_password(self, mock_verify):
        """The local fallback must use the latest cached hash, not whatever password was used
        the very first time - covers the "update opportunistically" half of issue #4."""
        mock_verify.return_value = PROFILE
        self.backend.authenticate(None, username='op@example.com', password='old-password')
        self.backend.authenticate(None, username='op@example.com', password='new-password')

        mock_verify.side_effect = RegisterAPIError('Could not reach Register: timed out')
        self.assertIsNone(self.backend.authenticate(None, username='op@example.com', password='old-password'))
        self.assertIsNotNone(self.backend.authenticate(None, username='op@example.com', password='new-password'))


class LoginViewTest(TestCase):
    @patch('core.auth_backends.verify_operator')
    def test_login_via_register_credentials(self, mock_verify):
        mock_verify.return_value = PROFILE

        response = self.client.post(reverse('login'), {'username': 'op@example.com', 'password': 'hunter2'})

        self.assertRedirects(response, reverse('home'))
        self.assertTrue(response.wsgi_request.user.is_authenticated)

    @patch('core.auth_backends.verify_operator')
    def test_topnav_shows_full_name_after_register_login(self, mock_verify):
        mock_verify.return_value = PROFILE
        self.client.post(reverse('login'), {'username': 'op@example.com', 'password': 'hunter2'})

        response = self.client.get(reverse('home'))

        self.assertContains(response, 'Op Erator')
