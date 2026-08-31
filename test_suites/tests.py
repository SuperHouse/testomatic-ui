# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 SuperHouse Automation Pty Ltd <info@superhouse.tv>
import io
import json
import shutil
import tempfile
import zipfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import Design, TestSuite
from .sync import fetch_design_thumbnail, fetch_test_suite_package, sync_test_suites


def package_zip_bytes(test_steps=None, manual_checks=None, notes=None):
    data = {
        'export_schema_version': 1,
        'design': {'id': 133, 'sku': 'ABC123', 'name': 'Widget', 'hw_version': '1.0'},
        'test_suite': {'id': 6, 'version': 2, 'status': 'SAVED', 'notes': notes, 'created_dt': '2026-08-26T10:02:56Z'},
        'test_steps': test_steps or [],
        'manual_checks': manual_checks or [],
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('widget-hw1_0-test-suite-v2/test-suite-definition.json', json.dumps(data))
    return buffer.getvalue()


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


@patch('test_suites.sync.list_design_assets', return_value=[])
@patch('test_suites.sync.fetch_test_suite')
@patch('test_suites.sync.list_test_suites')
@patch('test_suites.sync.list_designs')
class SyncTestSuitesTest(MediaIsolatedTestCase):
    def test_creates_designs_and_test_suites(self, mock_list_designs, mock_list_test_suites, mock_fetch, mock_list_design_assets):
        mock_list_designs.return_value = DESIGNS
        mock_list_test_suites.return_value = SUITES
        mock_fetch.return_value = b'PK\x03\x04zip-bytes'

        sync_test_suites()

        design = Design.objects.get(register_id=133)
        self.assertEqual(design.sku, 'ABC123')
        self.assertEqual(design.name, 'Widget')
        self.assertEqual(design.client_name, 'Acme')
        self.assertEqual(TestSuite.objects.count(), 2)

    def test_only_fetches_latest_version_per_design(self, mock_list_designs, mock_list_test_suites, mock_fetch, mock_list_design_assets):
        mock_list_designs.return_value = DESIGNS
        mock_list_test_suites.return_value = SUITES
        mock_fetch.return_value = b'PK\x03\x04zip-bytes'

        sync_test_suites()

        latest = TestSuite.objects.get(register_id=6)  # version 2
        older = TestSuite.objects.get(register_id=2)  # version 1
        self.assertTrue(latest.package_file)
        self.assertFalse(older.package_file)
        mock_fetch.assert_called_once_with(6)

    def test_is_insert_only_for_existing_test_suites(self, mock_list_designs, mock_list_test_suites, mock_fetch, mock_list_design_assets):
        mock_list_designs.return_value = DESIGNS
        mock_list_test_suites.return_value = SUITES
        mock_fetch.return_value = b'PK\x03\x04zip-bytes'
        sync_test_suites()
        mock_fetch.reset_mock()

        sync_test_suites()  # second sync, nothing new

        self.assertEqual(TestSuite.objects.count(), 2)
        mock_fetch.assert_not_called()

    def test_skips_test_suite_for_unknown_design(self, mock_list_designs, mock_list_test_suites, mock_fetch, mock_list_design_assets):
        mock_list_designs.return_value = []
        mock_list_test_suites.return_value = SUITES

        sync_test_suites()

        self.assertEqual(TestSuite.objects.count(), 0)

    def test_handles_null_description_and_hw_version(self, mock_list_designs, mock_list_test_suites, mock_fetch, mock_list_design_assets):
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

    def test_handles_missing_client(self, mock_list_designs, mock_list_test_suites, mock_fetch, mock_list_design_assets):
        mock_list_designs.return_value = [
            {'id': 133, 'sku': 'ABC123', 'client': None, 'name': 'Widget', 'hw_version': '1.0', 'description': ''},
        ]
        mock_list_test_suites.return_value = []

        sync_test_suites()

        design = Design.objects.get(register_id=133)
        self.assertEqual(design.client_name, '')

    def test_fetches_thumbnail_for_design_with_a_test_suite(self, mock_list_designs, mock_list_test_suites, mock_fetch, mock_list_design_assets):
        mock_list_designs.return_value = DESIGNS
        mock_list_test_suites.return_value = SUITES
        mock_fetch.return_value = b'PK\x03\x04zip-bytes'
        mock_list_design_assets.return_value = [
            {'id': 42, 'design_id': 133, 'asset_type': 'PCB_TOP', 'name': 'top', 'uploaded_dt': '2026-08-01T00:00:00Z'},
        ]

        with patch('test_suites.sync.fetch_design_asset', return_value=(b'png-bytes', 'image/png')) as mock_fetch_asset:
            sync_test_suites()

        design = Design.objects.get(register_id=133)
        self.assertTrue(design.thumbnail)
        mock_list_design_assets.assert_called_once_with(design_id=133, asset_type='PCB_TOP')
        mock_fetch_asset.assert_called_once_with(42)

    def test_no_thumbnail_fetch_for_design_without_a_test_suite(self, mock_list_designs, mock_list_test_suites, mock_fetch, mock_list_design_assets):
        mock_list_designs.return_value = DESIGNS
        mock_list_test_suites.return_value = []  # design 133 has no Test Suite

        sync_test_suites()

        mock_list_design_assets.assert_not_called()


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


class FetchDesignThumbnailTest(MediaIsolatedTestCase):
    def setUp(self):
        self.design = Design.objects.create(register_id=133, sku='ABC123', name='Widget', hw_version='1.0')

    @patch('test_suites.sync.fetch_design_asset')
    @patch('test_suites.sync.list_design_assets')
    def test_fetches_and_stores_thumbnail(self, mock_list_assets, mock_fetch_asset):
        mock_list_assets.return_value = [
            {'id': 42, 'design_id': 133, 'asset_type': 'PCB_TOP', 'name': 'top', 'uploaded_dt': '2026-08-01T00:00:00Z'},
        ]
        mock_fetch_asset.return_value = (b'png-bytes', 'image/png')

        fetch_design_thumbnail(self.design)

        self.design.refresh_from_db()
        self.assertTrue(self.design.thumbnail)
        self.assertTrue(self.design.thumbnail.name.endswith('.png'))
        mock_list_assets.assert_called_once_with(design_id=133, asset_type='PCB_TOP')
        mock_fetch_asset.assert_called_once_with(42)

    @patch('test_suites.sync.fetch_design_asset')
    @patch('test_suites.sync.list_design_assets')
    def test_leaves_thumbnail_null_when_no_pcb_top_asset(self, mock_list_assets, mock_fetch_asset):
        mock_list_assets.return_value = []

        fetch_design_thumbnail(self.design)

        self.design.refresh_from_db()
        self.assertFalse(self.design.thumbnail)
        mock_fetch_asset.assert_not_called()

    @patch('test_suites.sync.fetch_design_asset')
    @patch('test_suites.sync.list_design_assets')
    def test_does_not_refetch_existing_thumbnail(self, mock_list_assets, mock_fetch_asset):
        self.design.thumbnail.save('existing.png', ContentFile(b'already here'), save=True)

        fetch_design_thumbnail(self.design)

        mock_list_assets.assert_not_called()
        mock_fetch_asset.assert_not_called()


class TestSuiteViewsTest(MediaIsolatedTestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='testuser', password='secret123')
        self.client.force_login(self.user)
        self.design = Design.objects.create(
            register_id=133, sku='ABC123', name='Widget', client_name='Acme', hw_version='1.0'
        )
        self.test_suite = TestSuite.objects.create(
            register_id=6, design=self.design, version=2, status='SAVED', register_created_dt='2026-08-26T10:02:56Z'
        )

    def test_list_view_shows_design_and_version(self):
        response = self.client.get(reverse('test_suites:list'))

        self.assertContains(response, 'Widget')
        self.assertContains(response, 'ABC123')

    def test_list_view_header_shows_org_then_bold_name_then_version(self):
        response = self.client.get(reverse('test_suites:list'))

        self.assertContains(response, '<h5 class="mb-0">Acme <b>Widget</b> v1.0</h5>')

    def test_list_view_excludes_designs_with_no_test_suites(self):
        Design.objects.create(register_id=999, sku='NOSUITE', name='No Suites Yet', hw_version='1.0')

        response = self.client.get(reverse('test_suites:list'))

        self.assertNotContains(response, 'No Suites Yet')

    def test_list_view_shows_generic_icon_when_no_thumbnail(self):
        response = self.client.get(reverse('test_suites:list'))

        self.assertContains(response, 'cil-memory')
        self.assertNotContains(response, '<img src="/media/design_thumbnails/')

    def test_list_view_shows_thumbnail_image_when_present(self):
        self.design.thumbnail.save('133.png', ContentFile(b'png-bytes'), save=True)

        response = self.client.get(reverse('test_suites:list'))

        self.assertContains(response, '<img src="/media/design_thumbnails/')

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

    def test_list_view_row_is_not_clickable_when_not_fetched(self):
        response = self.client.get(reverse('test_suites:list'))

        # The page's <style> block mentions "clickable-row" in its selector regardless, so
        # check for the class actually being applied to a <tr>, not the bare substring.
        self.assertNotContains(response, '<tr class="clickable-row"')

    def test_list_view_row_is_clickable_when_fetched(self):
        self.test_suite.package_file.save('6.zip', ContentFile(package_zip_bytes()), save=True)

        response = self.client.get(reverse('test_suites:list'))

        detail_url = reverse('test_suites:detail', args=[self.test_suite.pk])
        self.assertContains(response, f"onclick=\"window.location='{detail_url}'\"")


class TestSuiteDetailViewTest(MediaIsolatedTestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='testuser', password='secret123')
        self.client.force_login(self.user)
        self.design = Design.objects.create(register_id=133, sku='ABC123', name='Widget', hw_version='1.0')
        self.test_suite = TestSuite.objects.create(
            register_id=6, design=self.design, version=2, status='SAVED', register_created_dt='2026-08-26T10:02:56Z'
        )

    def test_404_when_not_yet_fetched(self):
        response = self.client.get(reverse('test_suites:detail', args=[self.test_suite.pk]))
        self.assertEqual(response.status_code, 404)

    def test_shows_steps_and_manual_checks(self):
        content = package_zip_bytes(
            test_steps=[
                {'order': 1, 'step_type': 'BEEP', 'name': 'Buzz once', 'abort_on_fail': True, 'config': {'duration_ms': 500}},
            ],
            manual_checks=[{'order': 1, 'text': 'Check the enclosure for cracks'}],
            notes='Handle the board with an anti-static strap',
        )
        self.test_suite.package_file.save('6.zip', ContentFile(content), save=True)

        response = self.client.get(reverse('test_suites:detail', args=[self.test_suite.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Buzz once')
        self.assertContains(response, '1 × 500 ms')
        self.assertContains(response, 'Abort On Fail')
        self.assertContains(response, 'Check the enclosure for cracks')
        self.assertContains(response, 'Handle the board with an anti-static strap')

    def test_nothing_is_clickable_or_editable(self):
        content = package_zip_bytes(
            test_steps=[{'order': 1, 'step_type': 'DELAY', 'name': 'Wait', 'abort_on_fail': False, 'config': {'delay_ms': 1}}],
        )
        self.test_suite.package_file.save('6.zip', ContentFile(content), save=True)

        response = self.client.get(reverse('test_suites:detail', args=[self.test_suite.pk]))

        # The base template's sidebar always has a logout <form>, so check for editing-specific
        # markup rather than the presence of any <form at all.
        self.assertNotContains(response, 'onclick')
        self.assertNotContains(response, 'bi-grip-vertical')
        self.assertNotContains(response, 'btn-outline-danger')
        self.assertNotContains(response, reverse('test_suites:fetch', args=[self.test_suite.pk]))

    def test_shows_current_version_badge_when_it_is_the_highest_version(self):
        self.test_suite.package_file.save('6.zip', ContentFile(package_zip_bytes()), save=True)

        response = self.client.get(reverse('test_suites:detail', args=[self.test_suite.pk]))

        self.assertContains(response, '<span class="badge bg-success">Current Version</span>')
        self.assertNotContains(response, 'Old Version')

    def test_shows_old_version_badge_when_a_newer_version_exists(self):
        TestSuite.objects.create(
            register_id=7, design=self.design, version=3, status='SAVED', register_created_dt='2026-08-27T00:00:00Z'
        )
        self.test_suite.package_file.save('6.zip', ContentFile(package_zip_bytes()), save=True)

        response = self.client.get(reverse('test_suites:detail', args=[self.test_suite.pk]))

        self.assertContains(response, '<span class="badge bg-danger">Old Version</span>')
        self.assertNotContains(response, 'Current Version')


class TestSuiteIsCurrentVersionTest(MediaIsolatedTestCase):
    def setUp(self):
        self.design = Design.objects.create(register_id=133, sku='ABC123', name='Widget', hw_version='1.0')

    def test_true_when_only_version(self):
        v1 = TestSuite.objects.create(
            register_id=1, design=self.design, version=1, status='SAVED', register_created_dt='2026-08-26T00:00:00Z'
        )
        self.assertTrue(v1.is_current_version())

    def test_false_for_older_version_when_a_newer_one_exists(self):
        v1 = TestSuite.objects.create(
            register_id=1, design=self.design, version=1, status='SAVED', register_created_dt='2026-08-26T00:00:00Z'
        )
        TestSuite.objects.create(
            register_id=2, design=self.design, version=2, status='SAVED', register_created_dt='2026-08-27T00:00:00Z'
        )
        self.assertFalse(v1.is_current_version())

    def test_true_for_newest_version(self):
        TestSuite.objects.create(
            register_id=1, design=self.design, version=1, status='SAVED', register_created_dt='2026-08-26T00:00:00Z'
        )
        v2 = TestSuite.objects.create(
            register_id=2, design=self.design, version=2, status='SAVED', register_created_dt='2026-08-27T00:00:00Z'
        )
        self.assertTrue(v2.is_current_version())

    def test_unaffected_by_whether_the_newer_version_has_been_fetched(self):
        """A newer version's metadata can exist (synced) before its package has been downloaded
        - is_current_version() must still say the older, already-fetched one isn't current."""
        v1 = TestSuite.objects.create(
            register_id=1, design=self.design, version=1, status='SAVED', register_created_dt='2026-08-26T00:00:00Z'
        )
        v1.package_file.save('1.zip', ContentFile(package_zip_bytes()), save=True)
        TestSuite.objects.create(  # v2, not yet fetched
            register_id=2, design=self.design, version=2, status='SAVED', register_created_dt='2026-08-27T00:00:00Z'
        )
        self.assertFalse(v1.is_current_version())
