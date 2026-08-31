# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 SuperHouse Automation Pty Ltd <info@superhouse.tv>
"""Parses a downloaded Test Suite Package ZIP (test-suite-definition.json) into display-ready
objects for the read-only detail page (issue #3). STEP_TYPE_LABELS/STEP_TYPE_COLORS and
_config_summary() are an exact port of Register's testing.models.TestStep (STEP_TYPE_CHOICES /
STEP_TYPE_COLORS / get_config_summary()) - the point of this page is to look the same as
Register's own read-only test_suite_version_detail.html, so StepDisplay/CheckDisplay expose the
same get_color()/get_step_type_display()/get_config_summary() method names Register's template
calls, letting test_suites/templates/test_suites/detail.html mirror that template closely.
Register is the source of truth for step types; an unrecognised step_type (e.g. one Register
added after this file was last updated) falls back to a generic grey badge and a raw dump of its
config, rather than crashing."""
import json
import zipfile

DEFAULT_COLOR = '#6c757d'

STEP_TYPE_LABELS = {
    'DELAY': 'Delay',
    'UPLOAD_FIRMWARE': 'Upload Firmware',
    'BEEP': 'Beep',
    'READ_RAIL_VOLTAGE': 'Read Rail Voltage',
    'READ_RAIL_CURRENT': 'Read Rail Current',
    'CONTROL_POWER_RAIL': 'Control Power Rail',
    'PYTHON': 'Python',
    'IOMOD_ANALOG_READ': 'IOMOD Analog Read',
    'IOMOD_DIGITAL_READ': 'IOMOD Digital Read',
    'IOMOD_DIGITAL_WRITE': 'IOMOD Digital Write',
    'IOMOD_ANALOG_WRITE': 'IOMOD Analog Write',
    'LED_SPECTRAL_READING': 'LED Spectral Reading',
    'OPERATOR_INTERVENTION': 'Operator Intervention',
}

STEP_TYPE_COLORS = {
    'DELAY': '#6c757d',
    'UPLOAD_FIRMWARE': '#0d6efd',
    'BEEP': '#fd7e14',
    'READ_RAIL_VOLTAGE': '#198754',
    'READ_RAIL_CURRENT': '#20c997',
    'CONTROL_POWER_RAIL': '#dc3545',
    'PYTHON': '#6f42c1',
    'IOMOD_DIGITAL_READ': '#0dcaf0',
    'IOMOD_ANALOG_READ': '#0aa2c0',
    'IOMOD_DIGITAL_WRITE': '#d63384',
    'IOMOD_ANALOG_WRITE': '#ad1457',
    'LED_SPECTRAL_READING': '#ffc107',
    'OPERATOR_INTERVENTION': '#6610f2',
}


def _truncate(text, max_len):
    text = text.strip()
    if len(text) > max_len:
        return text[:max_len - 3] + '...'
    return text


def _range_summary(lo, hi):
    if lo is not None and hi is not None:
        return f'{lo}–{hi}'
    if lo is not None:
        return f'≥{lo}'
    if hi is not None:
        return f'≤{hi}'
    return 'any'


def _python_code_summary(code):
    lines = [line for line in code.splitlines() if line.strip()]
    if not lines:
        return 'No code'
    first = lines[0].strip()
    if len(first) > 60:
        first = first[:57] + '...'
    remaining = len(lines) - 1
    if remaining:
        return f"{first} (+{remaining} more line{'s' if remaining != 1 else ''})"
    return first


def _config_summary(step_type, config):
    c = config
    if step_type == 'DELAY':
        return f"{c.get('delay_ms', '?')} ms"
    if step_type == 'UPLOAD_FIRMWARE':
        return f"{c.get('upload_tool', '?')} via {c.get('port', '?')} — {c.get('firmware_file', '?')}"
    if step_type == 'BEEP':
        return f"{c.get('count', 1)} × {c.get('duration_ms', '?')} ms"
    if step_type == 'READ_RAIL_VOLTAGE':
        return f"{c.get('rail', '?')}: {c.get('min_v', '?')}–{c.get('max_v', '?')} V"
    if step_type == 'READ_RAIL_CURRENT':
        return f"{c.get('rail', '?')}: {c.get('min_ma', '?')}–{c.get('max_ma', '?')} mA"
    if step_type == 'CONTROL_POWER_RAIL':
        return f"{c.get('rail', '?')}: {c.get('action', '?')}"
    if step_type == 'PYTHON':
        return _python_code_summary(c.get('python_code', ''))
    if step_type == 'IOMOD_ANALOG_READ':
        return (f"IOMOD {c.get('iomod', '?')} Pin {c.get('pin', '?')}: "
                f"expect {_range_summary(c.get('expect_min'), c.get('expect_max'))}")
    if step_type == 'IOMOD_DIGITAL_READ':
        return f"IOMOD {c.get('iomod', '?')} Pin {c.get('pin', '?')}: expect {c.get('expect', '?')}"
    if step_type == 'IOMOD_DIGITAL_WRITE':
        return f"IOMOD {c.get('iomod', '?')} Pin {c.get('pin', '?')}: write {c.get('digital_write', '?')}"
    if step_type == 'IOMOD_ANALOG_WRITE':
        return f"IOMOD {c.get('iomod', '?')} Pin {c.get('pin', '?')}: write {c.get('analog_write', '?')}"
    if step_type == 'LED_SPECTRAL_READING':
        mux = f"MUX {c.get('mux_addr')}:{c.get('mux_chan', '?')} " if c.get('mux_addr') else ''
        return (
            f"{mux}I2C {c.get('i2c_addr', '?')} — "
            f"R {_range_summary(c.get('r_min'), c.get('r_max'))}, "
            f"G {_range_summary(c.get('g_min'), c.get('g_max'))}, "
            f"B {_range_summary(c.get('b_min'), c.get('b_max'))}, "
            f"Lux {_range_summary(c.get('lux_min'), c.get('lux_max'))}, "
            f"IR {_range_summary(c.get('ir_min'), c.get('ir_max'))}"
        )
    if step_type == 'OPERATOR_INTERVENTION':
        return _truncate(c.get('message', ''), 80) or 'No message'
    return str(config)


class StepDisplay:
    def __init__(self, data):
        self.order = data.get('order')
        self.step_type = data.get('step_type', '')
        self.name = data.get('name', '')
        self.abort_on_fail = bool(data.get('abort_on_fail'))
        self.config = data.get('config') or {}

    def get_color(self):
        return STEP_TYPE_COLORS.get(self.step_type, DEFAULT_COLOR)

    def get_step_type_display(self):
        return STEP_TYPE_LABELS.get(self.step_type, self.step_type.replace('_', ' ').title())

    def get_config_summary(self):
        return _config_summary(self.step_type, self.config)


class CheckDisplay:
    def __init__(self, data):
        self.order = data.get('order')
        self.text = data.get('text', '')

    def get_color(self):
        # Manual checks share Operator Intervention's colour in Register too - see
        # testing.models.ManualCheck.get_color().
        return STEP_TYPE_COLORS['OPERATOR_INTERVENTION']


class TestSuitePackage:
    def __init__(self, notes, steps, manual_checks):
        self.notes = notes
        self.steps = steps
        self.manual_checks = manual_checks


def parse_test_suite_package(file):
    """file: an open, readable binary file-like object (e.g. TestSuite.package_file.open('rb'))
    containing a Test Suite Package ZIP, as produced by Register's build_test_suite_package_response()."""
    with zipfile.ZipFile(file) as archive:
        [name] = [n for n in archive.namelist() if n.endswith('test-suite-definition.json')]
        data = json.loads(archive.read(name))

    steps = [StepDisplay(d) for d in data.get('test_steps', [])]
    manual_checks = [CheckDisplay(d) for d in data.get('manual_checks', [])]
    notes = (data.get('test_suite') or {}).get('notes')
    return TestSuitePackage(notes, steps, manual_checks)
