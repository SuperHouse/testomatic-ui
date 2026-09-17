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
from django.utils import timezone

from testomatic.runner import RunReport, StepOutcome
from testomatic.steps import StepResult
from testomatic.suite import ManualCheck, TestStep

from core.models import DeviceSettings

from . import docket, views
from .models import Design, TestRun, TestSuite
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

    def test_list_view_shows_organisation_sku_name_and_version_columns(self):
        response = self.client.get(reverse('test_suites:list'))
        content = response.content.decode()

        self.assertIn('<td>Acme</td>', content)
        self.assertIn('<td>ABC123</td>', content)
        self.assertIn('<td>Widget</td>', content)
        self.assertIn('<td>1.0</td>', content)
        # Columns render in this order: Organisation, SKU, Name, Version.
        self.assertLess(content.index('>Acme<'), content.index('>ABC123<'))
        self.assertLess(content.index('>ABC123<'), content.index('>Widget<'))
        self.assertLess(content.index('>Widget<'), content.index('>1.0<'))

    def test_list_view_excludes_designs_with_no_test_suites(self):
        Design.objects.create(register_id=999, sku='NOSUITE', name='No Suites Yet', hw_version='1.0')

        response = self.client.get(reverse('test_suites:list'))

        self.assertNotContains(response, 'No Suites Yet')

    def test_list_view_shows_no_thumbnail_image_when_absent(self):
        # The thumbnail column has no fallback icon (deliberately removed in 3a3390c) - a design
        # with no thumbnail just renders an empty cell.
        response = self.client.get(reverse('test_suites:list'))

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

    def test_shows_on_docket_badge_when_step_is_included(self):
        # register#126: this badge mirrors Register's own design_detail.html/
        # test_suite_version_detail.html - positive logic (badge present = will print on the
        # Test Docket), not the old "Not on Docket" wording.
        content = package_zip_bytes(test_steps=[
            {'order': 1, 'step_type': 'BEEP', 'name': 'Buzz once', 'abort_on_fail': False,
             'include_on_docket': True, 'config': {'duration_ms': 500}},
        ])
        self.test_suite.package_file.save('6.zip', ContentFile(content), save=True)

        response = self.client.get(reverse('test_suites:detail', args=[self.test_suite.pk]))

        self.assertContains(response, 'On Docket')
        self.assertNotContains(response, 'Not on Docket')

    def test_no_badge_when_step_is_not_included(self):
        content = package_zip_bytes(test_steps=[
            {'order': 1, 'step_type': 'DELAY', 'name': 'Settle', 'abort_on_fail': False,
             'include_on_docket': False, 'config': {'delay_ms': 250}},
        ])
        self.test_suite.package_file.save('6.zip', ContentFile(content), save=True)

        response = self.client.get(reverse('test_suites:detail', args=[self.test_suite.pk]))

        self.assertNotContains(response, 'On Docket')

    def test_shows_old_version_badge_when_a_newer_version_exists(self):
        TestSuite.objects.create(
            register_id=7, design=self.design, version=3, status='SAVED', register_created_dt='2026-08-27T00:00:00Z'
        )
        self.test_suite.package_file.save('6.zip', ContentFile(package_zip_bytes()), save=True)

        response = self.client.get(reverse('test_suites:detail', args=[self.test_suite.pk]))

        self.assertContains(response, '<span class="badge bg-danger">Old Version</span>')
        self.assertNotContains(response, 'Current Version')


class TestSuiteRunViewTest(MediaIsolatedTestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='testuser', password='secret123')
        self.client.force_login(self.user)
        self.design = Design.objects.create(register_id=133, sku='ABC123', name='Widget', hw_version='1.0')
        self.test_suite = TestSuite.objects.create(
            register_id=6, design=self.design, version=2, status='SAVED', register_created_dt='2026-08-26T10:02:56Z'
        )
        self.test_suite.package_file.save('6.zip', ContentFile(package_zip_bytes()), save=True)

    def test_get_not_allowed(self):
        response = self.client.get(reverse('test_suites:run', args=[self.test_suite.pk]))
        self.assertEqual(response.status_code, 405)

    def test_404_when_not_yet_fetched(self):
        unfetched = TestSuite.objects.create(
            register_id=7, design=self.design, version=1, status='SAVED', register_created_dt='2026-08-26T00:00:00Z'
        )
        response = self.client.post(reverse('test_suites:run', args=[unfetched.pk]), {'serial_number': '999'})
        self.assertEqual(response.status_code, 404)

    def test_run_requires_serial_number(self):
        response = self.client.post(reverse('test_suites:run', args=[self.test_suite.pk]), {'serial_number': ''})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Scan or enter a serial number')
        self.assertNotContains(response, 'Test Run Result')

    @patch('test_suites.views._run_test_suite')
    def test_shows_pass_result(self, mock_run):
        mock_run.return_value = views.RunResult('[PASS] Buzz once: ok\n\nResult: PASS', True, None)

        response = self.client.post(
            reverse('test_suites:run', args=[self.test_suite.pk]), {'serial_number': '999'}
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<span class="badge bg-success">PASS</span>')
        self.assertContains(response, 'Result: PASS')

    @patch('test_suites.views._run_test_suite')
    def test_shows_fail_result(self, mock_run):
        mock_run.return_value = views.RunResult('[FAIL] Buzz once: nope\n\nResult: FAIL', False, None)

        response = self.client.post(
            reverse('test_suites:run', args=[self.test_suite.pk]), {'serial_number': '999'}
        )

        self.assertContains(response, '<span class="badge bg-danger">FAIL</span>')

    @patch('test_suites.views._run_test_suite')
    def test_shows_error_message_instead_of_result(self, mock_run):
        mock_run.return_value = views.RunResult(None, None, 'Test Runner hardware support is not available on this device: boom')

        response = self.client.post(
            reverse('test_suites:run', args=[self.test_suite.pk]), {'serial_number': '999'}
        )

        self.assertContains(response, 'Test Run Failed')
        self.assertContains(response, 'not available on this device')
        self.assertNotContains(response, 'Test Run Result')

    @patch('test_suites.views._run_test_suite')
    def test_still_shows_steps_and_checks_alongside_result(self, mock_run):
        mock_run.return_value = views.RunResult('Result: PASS', True, None)
        content = package_zip_bytes(
            test_steps=[{'order': 1, 'step_type': 'BEEP', 'name': 'Buzz once', 'abort_on_fail': False, 'config': {'duration_ms': 500}}],
        )
        self.test_suite.package_file.save('6.zip', ContentFile(content), save=True)

        response = self.client.post(
            reverse('test_suites:run', args=[self.test_suite.pk]), {'serial_number': '999'}
        )

        self.assertContains(response, 'Buzz once')

    @patch('test_suites.views._run_test_suite')
    def test_shows_bare_serial_number_from_barcode_scan(self, mock_run):
        mock_run.return_value = views.RunResult('Result: PASS', True, None)

        response = self.client.post(
            reverse('test_suites:run', args=[self.test_suite.pk]), {'serial_number': '12345'}
        )

        self.assertContains(response, 'Serial 12345')

    @patch('test_suites.views._run_test_suite')
    def test_strips_configured_url_stem_from_qr_code_scan(self, mock_run):
        mock_run.return_value = views.RunResult('Result: PASS', True, None)
        DeviceSettings.objects.update_or_create(
            pk=1, defaults={'device_details_url_stem': 'https://d.superlab.au/'}
        )

        response = self.client.post(
            reverse('test_suites:run', args=[self.test_suite.pk]),
            {'serial_number': 'https://d.superlab.au/12345'},
        )

        self.assertContains(response, 'Serial 12345')
        self.assertNotContains(response, 'd.superlab.au')

    def test_run_test_suite_reports_missing_hardware_library(self):
        # testomatic_io genuinely isn't installed in this dev/test environment - it's Pi/Linux-only,
        # pulled in only via testomatic-runner's "pi" extra - so this exercises the real ImportError
        # path rather than mocking it away.
        run_result = views._run_test_suite(self.test_suite)

        self.assertIsNone(run_result.output)
        self.assertIsNone(run_result.passed)
        self.assertIn('not available on this device', run_result.error)

    @patch('test_suites.docket.subprocess.run')
    @patch('test_suites.views._run_test_suite')
    def test_creates_test_run_and_shows_print_status_when_printer_configured(self, mock_run, mock_subprocess_run):
        DeviceSettings.objects.update_or_create(
            pk=1, defaults={'printer_name': 'Printer_POS-80', 'device_details_url_stem': 'https://d.superlab.au/'}
        )
        mock_run.return_value = views.RunResult('Result: PASS', True, None, _make_report(), [])

        response = self.client.post(
            reverse('test_suites:run', args=[self.test_suite.pk]), {'serial_number': '3990'}
        )

        self.assertEqual(TestRun.objects.count(), 1)
        test_run = TestRun.objects.get()
        self.assertEqual(test_run.serial_number, '3990')
        self.assertTrue(test_run.docket_image)
        self.assertContains(response, 'Docket printed to Printer_POS-80')
        self.assertContains(response, 'Reprint Docket')
        mock_subprocess_run.assert_called_once()

    @patch('test_suites.views._run_test_suite')
    def test_no_test_run_created_when_run_could_not_start(self, mock_run):
        mock_run.return_value = views.RunResult(
            None, None, 'Test Runner hardware support is not available on this device: boom'
        )

        self.client.post(reverse('test_suites:run', args=[self.test_suite.pk]), {'serial_number': '3990'})

        self.assertEqual(TestRun.objects.count(), 0)


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


def _make_report(passed=True, message='ok', aborted=False, include_on_docket=True, extra_outcomes=None):
    return RunReport(
        outcomes=[
            StepOutcome(
                step=TestStep(
                    order=1, step_type='BEEP', name='Buzz once', abort_on_fail=False,
                    config_schema_version=None, config={}, include_on_docket=include_on_docket,
                ),
                result=StepResult(passed=passed, message=message),
            ),
            *(extra_outcomes or []),
        ],
        aborted=aborted,
    )


def _firmware_outcome(name, step_type='UPLOAD_FIRMWARE_ESPTOOL', passed=True, include_on_docket=True):
    """A StepOutcome for one of the 4 UPLOAD_FIRMWARE_* step types (register#124's firmware
    versions on the docket - see docket.build_docket_lines)."""
    return StepOutcome(
        step=TestStep(
            order=2, step_type=step_type, name=name, abort_on_fail=False,
            config_schema_version=None, config={}, include_on_docket=include_on_docket,
        ),
        result=StepResult(passed=passed, message='ok' if passed else 'upload failed'),
    )


class DocketLinesTest(TestCase):
    def setUp(self):
        self.design = Design.objects.create(
            register_id=133, sku='ABC123', name='Widget', client_name='Acme', hw_version='9.1'
        )
        self.test_suite = TestSuite.objects.create(
            register_id=6, design=self.design, version=2, status='SAVED', register_created_dt='2026-08-26T10:02:56Z'
        )
        self.test_suite.refresh_from_db()  # register_created_dt is a real datetime only once re-fetched
        self.manual_checks = [
            ManualCheck(order=1, text='Serial number on back'),
            ManualCheck(order=2, text='Blue power LED works'),
        ]

    def _lines(self, report=None, manual_checks=None):
        return docket.build_docket_lines(
            self.test_suite, '3990', 'Jonathan Oxer', report or _make_report(), manual_checks or self.manual_checks,
            timezone.now(), 'https://d.superlab.au/3990',
        )

    def test_header_shows_client_device_serial_and_hw_version(self):
        lines = self._lines()

        self.assertIn('Acme', lines)
        self.assertIn('Widget', lines)
        self.assertIn('Serial: 3990', lines)
        self.assertIn('Version v9.1', lines)
        self.assertIn('Tested by Jonathan Oxer', lines)

    def test_device_name_is_bold(self):
        lines = self._lines()

        device_line = next(line for line in lines if line == 'Widget')
        self.assertTrue(device_line.bold)

    def test_omits_firmware_section_when_no_firmware_steps(self):
        content = '\n'.join(self._lines())

        self.assertNotIn('Firmware:', content)

    def test_lists_firmware_step_name_under_hardware_version(self):
        report = _make_report(extra_outcomes=[_firmware_outcome('Firmware v8.1.1')])
        lines = self._lines(report=report)

        self.assertNotIn('Firmware:', lines)
        hw_version_index = lines.index('Version v9.1')
        firmware_index = lines.index('Firmware v8.1.1')
        self.assertGreater(firmware_index, hw_version_index)

    def test_lists_every_firmware_step_including_ones_later_superseded(self):
        report = _make_report(extra_outcomes=[
            _firmware_outcome('Test image'),
            _firmware_outcome('Firmware v8.1.1'),
        ])
        content = '\n'.join(self._lines(report=report))

        self.assertIn('Test image', content)
        self.assertIn('Firmware v8.1.1', content)

    def test_marks_failed_firmware_step(self):
        report = _make_report(extra_outcomes=[_firmware_outcome('Firmware v8.1.1', passed=False)])
        content = '\n'.join(self._lines(report=report))

        self.assertIn('Firmware v8.1.1 (FAILED)', content)

    def test_firmware_step_shown_even_when_suppressed_and_passed(self):
        report = _make_report(
            extra_outcomes=[_firmware_outcome('Firmware v8.1.1', include_on_docket=False)]
        )
        content = '\n'.join(self._lines(report=report))

        self.assertIn('Firmware v8.1.1', content)

    def test_lists_passing_automatic_check_as_one_right_aligned_line(self):
        lines = self._lines(report=_make_report(passed=True))

        line_chars = docket._line_width_chars()
        self.assertIn(docket._justify('Buzz once', 'PASS', line_chars), lines)

    def test_lists_failing_automatic_check_with_message(self):
        lines = self._lines(report=_make_report(passed=False, message='no beep detected'))

        line_chars = docket._line_width_chars()
        self.assertIn(docket._justify('Buzz once', 'FAIL', line_chars), lines)
        self.assertIn('  FAILED: no beep detected', lines)

    def test_shows_measured_value_alongside_pass(self):
        outcome = StepOutcome(
            step=TestStep(
                order=2, step_type='READ_RAIL_VOLTAGE', name='5V Rail', abort_on_fail=False,
                config_schema_version=None, config={},
            ),
            result=StepResult(passed=True, message='ok', measured={'voltage': 5.01, 'display': '5.01V'}),
        )
        report = _make_report(extra_outcomes=[outcome])
        lines = self._lines(report=report)

        line_chars = docket._line_width_chars()
        self.assertIn(docket._justify('5V Rail', 'PASS  5.01V', line_chars), lines)

    def test_notes_aborted_run(self):
        content = '\n'.join(self._lines(report=_make_report(aborted=True)))

        self.assertIn('ABORTED', content)

    def test_omits_suppressed_step_that_passed(self):
        content = '\n'.join(self._lines(report=_make_report(passed=True, include_on_docket=False)))

        self.assertNotIn('Buzz once', content)

    def test_still_shows_suppressed_step_that_failed(self):
        lines = self._lines(
            report=_make_report(passed=False, message='no beep detected', include_on_docket=False)
        )

        line_chars = docket._line_width_chars()
        self.assertIn(docket._justify('Buzz once', 'FAIL', line_chars), lines)
        self.assertIn('  FAILED: no beep detected', lines)

    def test_lists_manual_checks_with_a_drawn_checkbox(self):
        # issue #10 follow-up: a real printout showed the old literal "[  ]" text ran the two
        # longest labels ("Powers from prog header"/"Trigger activates valve") straight into the
        # brackets with no gap, then truncated them once _justify() reserved that gap - a drawn
        # tick-box costs less horizontal room than 4 monospace bracket characters, so every label
        # (including those two) fits untruncated with room to spare.
        lines = self._lines(manual_checks=[
            ManualCheck(order=1, text='Serial number on back'),
            ManualCheck(order=2, text='Powers from prog header'),
            ManualCheck(order=3, text='Trigger activates valve'),
        ])

        checkbox_lines = [line for line in lines if line.checkbox]
        texts = [str(line) for line in checkbox_lines]
        self.assertIn('Serial number on back', texts)
        self.assertIn('Powers from prog header', texts)
        self.assertIn('Trigger activates valve', texts)
        self.assertTrue(all('…' not in text for text in texts))
        self.assertNotIn('[  ]', '\n'.join(lines))

    def test_manual_check_label_truncates_with_ellipsis_if_too_long_for_the_checkbox_row(self):
        long_text = 'A' * 100
        lines = self._lines(manual_checks=[ManualCheck(order=1, text=long_text)])

        checkbox_line = next(line for line in lines if line.checkbox)
        self.assertTrue(checkbox_line.endswith('…'))
        self.assertLess(len(checkbox_line), len(long_text))

    def test_footer_includes_suite_version_and_url(self):
        content = '\n'.join(self._lines())

        self.assertIn('Test version: v2', content)
        self.assertIn('https://d.superlab.au/3990', content)

    def test_footer_lines_use_smaller_font(self):
        lines = self._lines()

        for text in (
            next(l for l in lines if l.startswith('Test version:')),
            next(l for l in lines if l == 'https://d.superlab.au/3990'),
        ):
            self.assertEqual(text.font_size, docket.FOOTER_FONT_SIZE)

    def test_section_headers_are_bold_with_a_rule_line_above(self):
        lines = self._lines()

        tests_header = next(l for l in lines if l == 'Automated Tests'.center(docket._line_width_chars()))
        checks_header = next(l for l in lines if l == 'Manual Checks'.center(docket._line_width_chars()))
        self.assertTrue(tests_header.bold)
        self.assertTrue(checks_header.bold)

        tests_index = lines.index(tests_header)
        checks_index = lines.index(checks_header)
        self.assertTrue(lines[tests_index - 1].rule)
        self.assertTrue(lines[checks_index - 1].rule)


class DocketImageTest(TestCase):
    def test_renders_image_with_expected_width(self):
        lines = ['        Test Report', 'Client: Acme', 'Device: Widget']

        image = docket.render_docket_image(lines, 'https://d.superlab.au/3990')

        self.assertEqual(image.width, docket.DOCKET_IMAGE_WIDTH)
        self.assertGreater(image.height, 0)


class SaveTestRunTest(MediaIsolatedTestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='testuser', password='secret123')
        self.design = Design.objects.create(
            register_id=133, sku='ABC123', name='Widget', client_name='Acme', hw_version='9.1'
        )
        self.test_suite = TestSuite.objects.create(
            register_id=6, design=self.design, version=2, status='SAVED', register_created_dt='2026-08-26T10:02:56Z'
        )
        self.manual_checks = [ManualCheck(order=1, text='Serial number on back')]

    def test_creates_test_run_with_structured_report(self):
        run_result = views.RunResult('irrelevant text', True, None, _make_report(), self.manual_checks)

        test_run = views._save_test_run(self.test_suite, '3990', self.user, run_result, timezone.now())

        self.assertEqual(test_run.test_suite, self.test_suite)
        self.assertEqual(test_run.serial_number, '3990')
        self.assertEqual(test_run.operator, self.user)
        self.assertTrue(test_run.passed)
        self.assertFalse(test_run.aborted)
        self.assertEqual(test_run.report['outcomes'][0]['step']['name'], 'Buzz once')
        self.assertEqual(test_run.report['manual_checks'][0]['text'], 'Serial number on back')

    def test_records_aborted_and_failed_run(self):
        run_result = views.RunResult('irrelevant text', False, None, _make_report(passed=False, aborted=True), [])

        test_run = views._save_test_run(self.test_suite, '3990', self.user, run_result, timezone.now())

        self.assertFalse(test_run.passed)
        self.assertTrue(test_run.aborted)


class PrintTestRunDocketTest(MediaIsolatedTestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='testuser', password='secret123', first_name='Jonathan', last_name='Oxer'
        )
        self.design = Design.objects.create(
            register_id=133, sku='ABC123', name='Widget', client_name='Acme', hw_version='9.1'
        )
        self.test_suite = TestSuite.objects.create(
            register_id=6, design=self.design, version=2, status='SAVED', register_created_dt='2026-08-26T10:02:56Z'
        )
        self.test_suite.refresh_from_db()  # register_created_dt is a real datetime only once re-fetched
        self.run_result = views.RunResult('irrelevant text', True, None, _make_report(), [])
        self.test_run = TestRun.objects.create(
            test_suite=self.test_suite, serial_number='3990', operator=self.user,
            started_dt=timezone.now(), finished_dt=timezone.now(), passed=True, aborted=False,
            report={'outcomes': [], 'aborted': False, 'manual_checks': []},
        )

    @patch('test_suites.docket.subprocess.run')
    def test_prints_when_printer_configured(self, mock_subprocess_run):
        DeviceSettings.objects.update_or_create(pk=1, defaults={'printer_name': 'Printer_POS-80'})
        device_settings = DeviceSettings.get_solo()

        views._print_test_run_docket(self.test_run, self.run_result, device_settings)

        self.test_run.refresh_from_db()
        self.assertTrue(self.test_run.docket_image)
        self.assertIn('Buzz once', self.test_run.docket_text)
        self.assertIsNotNone(self.test_run.docket_printed_dt)
        mock_subprocess_run.assert_called_once()
        self.assertEqual(mock_subprocess_run.call_args[0][0][:3], ['lp', '-d', 'Printer_POS-80'])

    def test_saves_docket_but_skips_printing_when_no_printer_configured(self):
        device_settings = DeviceSettings.get_solo()  # printer_name blank by default

        views._print_test_run_docket(self.test_run, self.run_result, device_settings)

        self.test_run.refresh_from_db()
        self.assertTrue(self.test_run.docket_image)
        self.assertIsNone(self.test_run.docket_printed_dt)

    @patch('test_suites.docket.subprocess.run')
    def test_records_error_when_print_fails(self, mock_subprocess_run):
        import subprocess
        mock_subprocess_run.side_effect = subprocess.CalledProcessError(1, 'lp')
        DeviceSettings.objects.update_or_create(pk=1, defaults={'printer_name': 'Printer_POS-80'})
        device_settings = DeviceSettings.get_solo()

        views._print_test_run_docket(self.test_run, self.run_result, device_settings)

        self.test_run.refresh_from_db()
        self.assertIn('Docket print failed', self.test_run.docket_print_error)
        self.assertIsNone(self.test_run.docket_printed_dt)


class TestRunReprintViewTest(MediaIsolatedTestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='testuser', password='secret123')
        self.client.force_login(self.user)
        self.design = Design.objects.create(
            register_id=133, sku='ABC123', name='Widget', client_name='Acme', hw_version='9.1'
        )
        self.test_suite = TestSuite.objects.create(
            register_id=6, design=self.design, version=2, status='SAVED', register_created_dt='2026-08-26T10:02:56Z'
        )
        self.test_suite.package_file.save('6.zip', ContentFile(package_zip_bytes()), save=True)
        self.test_run = TestRun.objects.create(
            test_suite=self.test_suite, serial_number='3990', operator=self.user,
            started_dt=timezone.now(), finished_dt=timezone.now(), passed=True, aborted=False,
            report={'outcomes': [], 'aborted': False, 'manual_checks': []},
        )
        image = docket.render_docket_image(['Test Report'], 'https://d.superlab.au/3990')
        buffer = io.BytesIO()
        image.save(buffer, format='PNG')
        self.test_run.docket_image.save('3990.png', ContentFile(buffer.getvalue()), save=True)

    @patch('test_suites.docket.subprocess.run')
    def test_reprints_stored_image(self, mock_subprocess_run):
        DeviceSettings.objects.update_or_create(pk=1, defaults={'printer_name': 'Printer_POS-80'})

        response = self.client.post(reverse('test_suites:run_reprint', args=[self.test_run.pk]))

        self.assertEqual(response.status_code, 200)
        mock_subprocess_run.assert_called_once()
        self.assertEqual(mock_subprocess_run.call_args[0][0][:3], ['lp', '-d', 'Printer_POS-80'])
        self.test_run.refresh_from_db()
        self.assertIsNotNone(self.test_run.docket_printed_dt)

    def test_shows_error_when_no_printer_configured(self):
        response = self.client.post(reverse('test_suites:run_reprint', args=[self.test_run.pk]))

        self.assertContains(response, 'No printer is configured')
