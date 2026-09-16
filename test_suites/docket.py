# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 SuperHouse Automation Pty Ltd <info@superhouse.tv>
"""Formats and prints a Test Docket after a Test Suite run (issue #8).

The docket is rendered as a single bitmap image (not plain text) so a QR code can sit alongside
the text on one seamless thermal-printer receipt - see build_docket_lines()/render_docket_image()
below. DOCKET_IMAGE_WIDTH/FONT_SIZE assume an 80mm receipt printer at 203dpi (matching the sample
"Printer_POS-80" queue name already in DeviceSettings.printer_name's help text); this hasn't been
tested against real thermal-printer hardware yet and will likely need tuning once it has.
"""
import subprocess
import tempfile
from pathlib import Path

import qrcode
from PIL import Image, ImageDraw, ImageFont

DOCKET_IMAGE_WIDTH = 576
FONT_SIZE = 22
LINE_SPACING = 6
MARGIN = 16
QR_SIZE = 240

# Common monospace TTF locations, tried in order - the first is what Raspberry Pi OS/Debian ships
# as part of the fonts-dejavu-core package. Falls back to Pillow's tiny built-in bitmap font (see
# _load_font()) if none of these exist, which is legible but not print-quality - a real device
# should have fonts-dejavu-core installed.
_FONT_PATHS = [
    '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf',
]


def _load_font():
    for path in _FONT_PATHS:
        if Path(path).exists():
            return ImageFont.truetype(path, FONT_SIZE)
    return ImageFont.load_default()


def build_docket_lines(test_suite, serial_number, operator_name, report, manual_checks, finished_dt, device_details_url):
    """Builds the Test Docket's plain-text content: header, automatic checks (from `report`,
    testomatic-runner's RunReport), a manual-checks checklist, and a footer - laid out to match
    the legacy prototype's output (see testomatic-ui#8 and 3990-MCM-20251019104515.txt).

    F/W version is deliberately omitted here: no field anywhere in testomatic-ui/testomatic-runner
    carries a firmware version today, and a real design decision is needed for designs with
    multiple MCUs (one overarching version vs. reporting each binary's version individually)
    before it can be added - out of scope for this pass.
    """
    design = test_suite.design
    lines = [
        '        Test Report',
        '      www.SuperLab.au',
        '',
        f'Client: {design.client_name}',
        f'Device: {design.name}',
        f'Serial: {serial_number}',
        f'H/W version: {design.hw_version}',
        f'Tested by: {operator_name}',
        finished_dt.strftime('%Y-%m-%d %H:%M:%S %z'),
        '',
        '=== Automatic checks =======',
    ]

    for outcome in report.outcomes:
        # issue #123: a step marked include_on_docket=False is left off the docket, but only
        # while it's passing - a failure is never silently missing from the printed record.
        if not outcome.step.include_on_docket and outcome.result.passed:
            continue
        lines.append(f'{outcome.step.name}:')
        if outcome.result.passed:
            lines.append('  ok')
        else:
            lines.append(f'  FAILED: {outcome.result.message}')

    if report.aborted:
        lines.append('')
        lines.append('ABORTED: abort-on-fail step failed, all power rails turned off')

    lines.append('')
    lines.append('=== Manual checks ==========')
    if manual_checks:
        text_width = max(len(check.text) for check in manual_checks)
        for check in manual_checks:
            lines.append(f'{check.text.ljust(text_width)} [  ]')

    lines.append('')
    lines.append(f'Test version: v{test_suite.version} ({test_suite.register_created_dt.date()})')
    lines.append(device_details_url)
    lines.append('-------- test end --------')
    return lines


def render_docket_image(lines, device_details_url):
    """Renders `lines` and a QR code for `device_details_url` onto a single bitmap, ready to be
    handed to print_docket_image(). Returns a PIL.Image.Image."""
    font = _load_font()
    line_height = FONT_SIZE + LINE_SPACING
    qr_image = qrcode.make(device_details_url).resize((QR_SIZE, QR_SIZE)).convert('L')

    height = MARGIN * 3 + len(lines) * line_height + QR_SIZE
    image = Image.new('L', (DOCKET_IMAGE_WIDTH, height), color=255)
    draw = ImageDraw.Draw(image)

    y = MARGIN
    for line in lines:
        draw.text((MARGIN, y), line, font=font, fill=0)
        y += line_height

    qr_x = (DOCKET_IMAGE_WIDTH - QR_SIZE) // 2
    image.paste(qr_image, (qr_x, y + MARGIN))

    return image


def load_docket_image(file):
    """Loads a previously-saved docket image (e.g. TestRun.docket_image) for reprinting."""
    image = Image.open(file)
    image.load()
    return image


def print_docket_image(image, printer_name):
    """Sends `image` to the CUPS queue `printer_name` via `lp`. Raises subprocess.CalledProcessError
    or OSError (e.g. lp not installed) on failure - callers must catch, since a print failure must
    never break the request that triggered it."""
    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
        image.save(f, format='PNG')
        path = f.name
    try:
        subprocess.run(['lp', '-d', printer_name, path], check=True, capture_output=True)
    finally:
        Path(path).unlink(missing_ok=True)
