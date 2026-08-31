from unittest.mock import Mock, patch

import requests
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from __VERSION import VERSION
from core.register_client import (
    RegisterAPIError,
    fetch_design_asset,
    fetch_test_suite,
    list_design_assets,
    list_test_suites,
    verify_operator,
)


class VersionDisplayTest(TestCase):
    def test_version_is_displayed_in_sidebar(self):
        user = get_user_model().objects.create_user(username='testuser', password='secret123')
        self.client.force_login(user)

        response = self.client.get(reverse('home'))

        self.assertContains(response, VERSION)
        self.assertContains(response, 'sidebar-footer')


class OperatorAvatarDisplayTest(TestCase):
    def test_shows_gravatar_and_full_name_in_name_then_avatar_order(self):
        from core.models import OperatorProfile

        user = get_user_model().objects.create_user(username='op@example.com', password='secret123', email='op@example.com')
        OperatorProfile.objects.create(user=user, register_user_id=5, full_name='Jon Oxer', avatar_type='gravatar')
        self.client.force_login(user)

        response = self.client.get(reverse('home'))
        content = response.content.decode()

        self.assertIn('Jon Oxer', content)
        self.assertIn('gravatar.com/avatar', content)
        # Register's own topnav shows the name before the avatar - check the same order here.
        self.assertLess(content.index('Jon Oxer'), content.index('gravatar.com/avatar'))

    def test_shows_initials_when_avatar_type_is_initials(self):
        from core.models import OperatorProfile

        user = get_user_model().objects.create_user(username='op@example.com', password='secret123', email='op@example.com')
        OperatorProfile.objects.create(user=user, register_user_id=5, full_name='Jon Oxer', avatar_type='initials')
        self.client.force_login(user)

        response = self.client.get(reverse('home'))

        self.assertContains(response, 'JO')
        self.assertNotContains(response, 'gravatar.com/avatar')

    def test_local_only_account_falls_back_to_username(self):
        """A createsuperuser-created account has no OperatorProfile at all - the page must still
        render (no OperatorProfile.DoesNotExist crash), falling back to the username."""
        user = get_user_model().objects.create_user(username='localadmin', password='secret123')
        self.client.force_login(user)

        response = self.client.get(reverse('home'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'localadmin')


@override_settings(REGISTER_API_URL='https://register.example.com', REGISTER_API_KEY='test-key')
class RegisterClientTest(TestCase):
    def _mock_response(self, status_code, json_data=None, content=b'', headers=None):
        response = Mock(status_code=status_code, content=content, headers=headers or {})
        response.json.side_effect = lambda: json_data if json_data is not None else (_ for _ in ()).throw(ValueError)
        response.text = '' if json_data is None else str(json_data)
        return response

    @patch('core.register_client.requests.get')
    def test_list_test_suites_success(self, mock_get):
        suites = [{'id': 7, 'design_id': 1, 'version': 2, 'status': 'SAVED', 'created_dt': '2026-08-01T09:15:00Z'}]
        mock_get.return_value = self._mock_response(200, json_data=suites)

        result = list_test_suites()

        self.assertEqual(result, suites)
        mock_get.assert_called_once_with(
            'https://register.example.com/api/v1/test-suites/',
            headers={'X-API-Key': 'test-key'},
            params=None,
            timeout=10,
        )

    @patch('core.register_client.requests.get')
    def test_list_test_suites_filters_by_design_id(self, mock_get):
        mock_get.return_value = self._mock_response(200, json_data=[])

        list_test_suites(design_id=3)

        mock_get.assert_called_once_with(
            'https://register.example.com/api/v1/test-suites/',
            headers={'X-API-Key': 'test-key'},
            params={'design_id': 3},
            timeout=10,
        )

    @patch('core.register_client.requests.get')
    def test_list_test_suites_non_staff_key_raises(self, mock_get):
        mock_get.return_value = self._mock_response(
            403, json_data={'message': 'API key does not have access to Test Suite Packages'}
        )

        with self.assertRaises(RegisterAPIError) as ctx:
            list_test_suites()

        self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(ctx.exception.message, 'API key does not have access to Test Suite Packages')

    @patch('core.register_client.requests.get')
    def test_fetch_test_suite_success(self, mock_get):
        mock_get.return_value = self._mock_response(200, content=b'PK\x03\x04fake-zip-bytes')

        result = fetch_test_suite(7)

        self.assertEqual(result, b'PK\x03\x04fake-zip-bytes')
        mock_get.assert_called_once_with(
            'https://register.example.com/api/v1/test-suites/7/download/',
            headers={'X-API-Key': 'test-key'},
            params=None,
            timeout=10,
        )

    @patch('core.register_client.requests.get')
    def test_fetch_test_suite_not_found_raises(self, mock_get):
        mock_get.return_value = self._mock_response(404, json_data={'detail': 'Not Found'})

        with self.assertRaises(RegisterAPIError) as ctx:
            fetch_test_suite(999)

        self.assertEqual(ctx.exception.status_code, 404)

    @patch('core.register_client.requests.get')
    def test_fetch_test_suite_draft_raises(self, mock_get):
        mock_get.return_value = self._mock_response(
            403, json_data={'message': 'Test Suite Package is still a draft and is not available for download'}
        )

        with self.assertRaises(RegisterAPIError) as ctx:
            fetch_test_suite(8)

        self.assertEqual(ctx.exception.status_code, 403)
        self.assertIn('draft', ctx.exception.message)

    @override_settings(REGISTER_API_URL='', REGISTER_API_KEY='')
    @patch('core.register_client.requests.get')
    def test_missing_config_raises_without_network_call(self, mock_get):
        with self.assertRaises(RegisterAPIError):
            list_test_suites()

        mock_get.assert_not_called()

    @patch('core.register_client.requests.get')
    def test_list_design_assets_success(self, mock_get):
        assets = [{'id': 42, 'design_id': 1, 'asset_type': 'PCB_TOP', 'name': 'top', 'uploaded_dt': '2026-08-01T00:00:00Z'}]
        mock_get.return_value = self._mock_response(200, json_data=assets)

        result = list_design_assets()

        self.assertEqual(result, assets)
        mock_get.assert_called_once_with(
            'https://register.example.com/api/v1/design-assets/',
            headers={'X-API-Key': 'test-key'},
            params=None,
            timeout=10,
        )

    @patch('core.register_client.requests.get')
    def test_list_design_assets_filters_by_design_id_and_type(self, mock_get):
        mock_get.return_value = self._mock_response(200, json_data=[])

        list_design_assets(design_id=1, asset_type='PCB_TOP')

        mock_get.assert_called_once_with(
            'https://register.example.com/api/v1/design-assets/',
            headers={'X-API-Key': 'test-key'},
            params={'design_id': 1, 'asset_type': 'PCB_TOP'},
            timeout=10,
        )

    @patch('core.register_client.requests.get')
    def test_fetch_design_asset_success(self, mock_get):
        mock_get.return_value = self._mock_response(200, content=b'\x89PNGfake', headers={'Content-Type': 'image/png'})

        content, content_type = fetch_design_asset(42)

        self.assertEqual(content, b'\x89PNGfake')
        self.assertEqual(content_type, 'image/png')
        mock_get.assert_called_once_with(
            'https://register.example.com/api/v1/design-assets/42/download/',
            headers={'X-API-Key': 'test-key'},
            params=None,
            timeout=10,
        )

    @patch('core.register_client.requests.get')
    def test_fetch_design_asset_internal_forbidden_raises(self, mock_get):
        mock_get.return_value = self._mock_response(
            403, json_data={'message': 'This asset is internal and not available to non-staff API keys'}
        )

        with self.assertRaises(RegisterAPIError) as ctx:
            fetch_design_asset(42)

        self.assertEqual(ctx.exception.status_code, 403)

    @patch('core.register_client.requests.post')
    def test_verify_operator_success(self, mock_post):
        profile = {'id': 5, 'email': 'op@example.com', 'full_name': 'Op Erator', 'avatar_type': 'gravatar', 'is_staff': True}
        mock_post.return_value = self._mock_response(200, json_data=profile)

        result = verify_operator('op@example.com', 'hunter2')

        self.assertEqual(result, profile)
        mock_post.assert_called_once_with(
            'https://register.example.com/api/v1/auth/verify/',
            headers={'X-API-Key': 'test-key'},
            json={'email': 'op@example.com', 'password': 'hunter2'},
            timeout=10,
        )

    @patch('core.register_client.requests.post')
    def test_verify_operator_wrong_password_raises_401(self, mock_post):
        mock_post.return_value = self._mock_response(401, json_data={'message': 'Invalid email or password'})

        with self.assertRaises(RegisterAPIError) as ctx:
            verify_operator('op@example.com', 'wrong')

        self.assertEqual(ctx.exception.status_code, 401)

    @patch('core.register_client.requests.post')
    def test_verify_operator_non_staff_raises_403(self, mock_post):
        mock_post.return_value = self._mock_response(403, json_data={'message': 'User is not a staff member'})

        with self.assertRaises(RegisterAPIError) as ctx:
            verify_operator('customer@example.com', 'correct')

        self.assertEqual(ctx.exception.status_code, 403)

    @patch('core.register_client.requests.post')
    def test_verify_operator_network_failure_has_no_status_code(self, mock_post):
        """RegisterAuthBackend relies on status_code being None to distinguish "Register is
        unreachable" (fall back to a local check) from "Register explicitly said no" (don't)."""
        mock_post.side_effect = requests.ConnectionError('connection refused')

        with self.assertRaises(RegisterAPIError) as ctx:
            verify_operator('op@example.com', 'hunter2')

        self.assertIsNone(ctx.exception.status_code)
