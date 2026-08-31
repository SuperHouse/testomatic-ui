# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 SuperHouse Automation Pty Ltd <info@superhouse.tv>
import shutil
import tempfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import Design, TestSuite
from .sync import fetch_test_suite_package, sync_test_suites


class MediaIsolatedTestCase(TestCase):
    """Base for any test that actually calls fetch_test_suite_package()/sync_test_suites() (as
    opposed to mocking them out entirely) - those write real files via FileField, which TestCase's
    DB transaction rollback does NOT undo, so without this they'd leak test .zip files into the
    real MEDIA_ROOT on every test run."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._media_root = tempfile.mkdtemp(prefix='testomatic-ui-test-media-')
        cls._media_root_override = override_settings(MEDIA_ROOT=cls._media_root)
        cls._media_root_override.enable()

    @classmethod
    def tearDownClass(cls):
        cls._media_root_override.disable()
        shutil.rmtree(cls._media_root, ignore_errors=True)
        super().tearDownClass()

DESIGNS = [
    {'id': 133, 'sku': 'ABC123', 'client': {'id': 1, 'company_name': 'Acme'}, 'name': 'Widget', 'hw_version': '1.0', 'description': ''},
]

SUITES = [
    {'id': 6, 'design_id': 133, 'version': 2, 'status': 'SAVED', 'created_dt': '2026-08-26T10:02:56Z'},
    {'id': 2, 'design_id': 133, 'version': 1, 'status': 'SAVED', 'created_dt': '2026-08-26T03:21:52Z'},
]


@patch('test_suites.sync.fetch_test_suite')
@patch('test_suites.sync.list_test_suites')
@patch('test_suites.sync.list_designs')
class SyncTestSuitesTest(MediaIsolatedTestCase):
    def test_creates_designs_and_test_suites(self, mock_list_designs, mock_list_test_suites, mock_fetch):
        mock_list_designs.return_value = DESIGNS
        mock_list_test_suites.return_value = SUITES
        mock_fetch.return_value = b'PK\x03\x04zip-bytes'

        sync_test_suites()

        design = Design.objects.get(register_id=133)
        self.assertEqual(design.sku, 'ABC123')
        self.assertEqual(design.name, 'Widget')
        self.assertEqual(TestSuite.objects.count(), 2)

    def test_only_fetches_latest_version_per_design(self, mock_list_designs, mock_list_test_suites, mock_fetch):
        mock_list_designs.return_value = DESIGNS
        mock_list_test_suites.return_value = SUITES
        mock_fetch.return_value = b'PK\x03\x04zip-bytes'

        sync_test_suites()

        latest = TestSuite.objects.get(register_id=6)  # version 2
        older = TestSuite.objects.get(register_id=2)  # version 1
        self.assertTrue(latest.package_file)
        self.assertFalse(older.package_file)
        mock_fetch.assert_called_once_with(6)

    def test_is_insert_only_for_existing_test_suites(self, mock_list_designs, mock_list_test_suites, mock_fetch):
        mock_list_designs.return_value = DESIGNS
        mock_list_test_suites.return_value = SUITES
        mock_fetch.return_value = b'PK\x03\x04zip-bytes'
        sync_test_suites()
        mock_fetch.reset_mock()

        sync_test_suites()  # second sync, nothing new

        self.assertEqual(TestSuite.objects.count(), 2)
        mock_fetch.assert_not_called()

    def test_skips_test_suite_for_unknown_design(self, mock_list_designs, mock_list_test_suites, mock_fetch):
        mock_list_designs.return_value = []
        mock_list_test_suites.return_value = SUITES

        sync_test_suites()

        self.assertEqual(TestSuite.objects.count(), 0)

    def test_handles_null_description_and_hw_version(self, mock_list_designs, mock_list_test_suites, mock_fetch):
        # Register returns JSON null, not an empty string, for an unset optional field.
        mock_list_designs.return_value = [
            {'id': 133, 'sku': 'ABC123', 'client': {'id': 1, 'company_name': 'Acme'}, 'name': 'Widget',
             'hw_version': None, 'description': None},
        ]
        mock_list_test_suites.return_value = []

        sync_test_suites()

        design = Design.objects.get(register_id=133)
        self.assertEqual(design.hw_version, '')
        self.assertEqual(design.description, '')


class FetchTestSuitePackageTest(MediaIsolatedTestCase):
    def setUp(self):
        self.design = Design.objects.create(register_id=133, sku='ABC123', name='Widget', hw_version='1.0')
        self.test_suite = TestSuite.objects.create(
            register_id=6, design=self.design, version=2, status='SAVED', register_created_dt='2026-08-26T10:02:56Z'
        )

    @patch('test_suites.sync.fetch_test_suite')
    def test_fetches_and_stores_package(self, mock_fetch):
        mock_fetch.return_value = b'PK\x03\x04zip-bytes'

        fetch_test_suite_package(self.test_suite)

        self.test_suite.refresh_from_db()
        self.assertTrue(self.test_suite.package_file)
        self.assertIsNotNone(self.test_suite.package_fetched_dt)
        mock_fetch.assert_called_once_with(6)

    @patch('test_suites.sync.fetch_test_suite')
    def test_does_not_refetch_already_fetched_package(self, mock_fetch):
        self.test_suite.package_file.save('existing.zip', ContentFile(b'already here'), save=True)

        fetch_test_suite_package(self.test_suite)

        mock_fetch.assert_not_called()


class TestSuiteViewsTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='testuser', password='secret123')
        self.client.force_login(self.user)
        self.design = Design.objects.create(register_id=133, sku='ABC123', name='Widget', hw_version='1.0')
        self.test_suite = TestSuite.objects.create(
            register_id=6, design=self.design, version=2, status='SAVED', register_created_dt='2026-08-26T10:02:56Z'
        )

    def test_list_view_shows_design_and_version(self):
        response = self.client.get(reverse('test_suites:list'))

        self.assertContains(response, 'Widget')
        self.assertContains(response, 'ABC123')

    def test_list_view_excludes_designs_with_no_test_suites(self):
        Design.objects.create(register_id=999, sku='NOSUITE', name='No Suites Yet', hw_version='1.0')

        response = self.client.get(reverse('test_suites:list'))

        self.assertNotContains(response, 'No Suites Yet')

    @patch('test_suites.views.sync_test_suites')
    def test_update_view_triggers_sync(self, mock_sync):
        response = self.client.post(reverse('test_suites:update'))

        mock_sync.assert_called_once()
        self.assertRedirects(response, reverse('test_suites:list'))

    @patch('test_suites.views.fetch_test_suite_package')
    def test_fetch_view_triggers_fetch_for_one_suite(self, mock_fetch):
        response = self.client.post(reverse('test_suites:fetch', args=[self.test_suite.pk]))

        mock_fetch.assert_called_once_with(self.test_suite)
        self.assertRedirects(response, reverse('test_suites:list'))
