# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 SuperHouse Automation Pty Ltd <info@superhouse.tv>
import io
import json
import zipfile

from django.test import SimpleTestCase

from .test_suite_package import parse_test_suite_package


def _package_zip(test_steps=None, manual_checks=None, notes=None):
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
    buffer.seek(0)
    return buffer


class ParseTestSuitePackageTest(SimpleTestCase):
    def test_reads_notes(self):
        package = parse_test_suite_package(_package_zip(notes='Handle with care'))
        self.assertEqual(package.notes, 'Handle with care')

    def test_empty_steps_and_checks(self):
        package = parse_test_suite_package(_package_zip())
        self.assertEqual(package.steps, [])
        self.assertEqual(package.manual_checks, [])

    def test_manual_check_text_and_color(self):
        package = parse_test_suite_package(_package_zip(manual_checks=[{'order': 1, 'text': 'Check the case'}]))
        [check] = package.manual_checks
        self.assertEqual(check.text, 'Check the case')
        self.assertEqual(check.get_color(), '#6610f2')  # same as OPERATOR_INTERVENTION


class StepDisplayConfigSummaryTest(SimpleTestCase):
    def _step(self, step_type, config, abort_on_fail=False):
        package = parse_test_suite_package(_package_zip(test_steps=[
            {'order': 1, 'step_type': step_type, 'name': 'Step', 'abort_on_fail': abort_on_fail, 'config': config},
        ]))
        [step] = package.steps
        return step

    def test_delay(self):
        step = self._step('DELAY', {'delay_ms': 500})
        self.assertEqual(step.get_config_summary(), '500 ms')
        self.assertEqual(step.get_color(), '#6c757d')
        self.assertEqual(step.get_step_type_display(), 'Delay')

    def test_beep_defaults_count_to_one(self):
        step = self._step('BEEP', {'duration_ms': 200})
        self.assertEqual(step.get_config_summary(), '1 × 200 ms')

    def test_beep_with_count(self):
        step = self._step('BEEP', {'duration_ms': 200, 'count': 3})
        self.assertEqual(step.get_config_summary(), '3 × 200 ms')

    def test_python_single_line(self):
        step = self._step('PYTHON', {'python_code': 'print("hello")'})
        self.assertEqual(step.get_config_summary(), 'print("hello")')

    def test_python_multi_line_shows_remaining_count(self):
        step = self._step('PYTHON', {'python_code': 'a = 1\nb = 2\nc = 3'})
        self.assertEqual(step.get_config_summary(), 'a = 1 (+2 more lines)')

    def test_iomod_analog_read_with_both_bounds(self):
        step = self._step('IOMOD_ANALOG_READ', {'iomod': 'A', 'pin': '3', 'expect_min': 10, 'expect_max': 20})
        self.assertEqual(step.get_config_summary(), 'IOMOD A Pin 3: expect 10–20')

    def test_iomod_analog_read_with_only_min_bound(self):
        step = self._step('IOMOD_ANALOG_READ', {'iomod': 'A', 'pin': '3', 'expect_min': 10})
        self.assertEqual(step.get_config_summary(), 'IOMOD A Pin 3: expect ≥10')

    def test_iomod_analog_read_with_no_bounds(self):
        step = self._step('IOMOD_ANALOG_READ', {'iomod': 'A', 'pin': '3'})
        self.assertEqual(step.get_config_summary(), 'IOMOD A Pin 3: expect any')

    def test_led_spectral_reading_without_mux(self):
        step = self._step('LED_SPECTRAL_READING', {'i2c_addr': '0x29', 'r_min': 1, 'r_max': 2})
        summary = step.get_config_summary()
        self.assertTrue(summary.startswith('I2C 0x29 —'))
        self.assertIn('R 1–2', summary)
        self.assertIn('G any', summary)

    def test_led_spectral_reading_with_mux(self):
        step = self._step('LED_SPECTRAL_READING', {'i2c_addr': '0x29', 'mux_addr': '0x70', 'mux_chan': 2})
        self.assertTrue(step.get_config_summary().startswith('MUX 0x70:2 I2C 0x29 —'))

    def test_operator_intervention_truncates_long_message(self):
        step = self._step('OPERATOR_INTERVENTION', {'message': 'x' * 100})
        summary = step.get_config_summary()
        self.assertEqual(len(summary), 80)
        self.assertTrue(summary.endswith('...'))

    def test_operator_intervention_empty_message(self):
        step = self._step('OPERATOR_INTERVENTION', {'message': ''})
        self.assertEqual(step.get_config_summary(), 'No message')

    def test_abort_on_fail_flag(self):
        step = self._step('DELAY', {'delay_ms': 1}, abort_on_fail=True)
        self.assertTrue(step.abort_on_fail)

    def test_unknown_step_type_falls_back_gracefully(self):
        step = self._step('SOME_FUTURE_TYPE', {'foo': 'bar'})
        self.assertEqual(step.get_color(), '#6c757d')
        self.assertEqual(step.get_step_type_display(), 'Some Future Type')
        self.assertIn('foo', step.get_config_summary())
