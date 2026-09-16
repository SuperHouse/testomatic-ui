# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 SuperHouse Automation Pty Ltd <info@superhouse.tv>
"""Formats and prints a Test Docket after a Test Suite run (issue #8).

The docket is rendered as a single bitmap image (not plain text) so a QR code can sit alongside
the text on one seamless thermal-printer receipt - see build_docket_lines()/render_docket_image()
below. DOCKET_IMAGE_WIDTH/FONT_SIZE assume an 80mm receipt printer at 203dpi (matching the sample
"Printer_POS-80" queue name already in DeviceSettings.printer_name's help text); this hasn't been
tested against real thermal-printer hardware yet and will likely need tuning once it has.

Layout (issue #10 and its sub-issues #11-#13): since the font is monospace, `_line_width_chars()`
converts the printable pixel width into a character budget, and every list in
`build_docket_lines()` (Automatic Checks, Manual Checks, plus the header/section rules) is padded
or right-aligned against that same budget via `_justify()`/`_rule()`, rather than each padding
itself to its own longest entry - this is what makes the docket actually use the full paper width
(#11) instead of just the left portion the widest line happens to reach. Automatic Checks are one
line per check, name left and PASS/FAIL right-aligned (#12), with a passing check's measured
value (`StepResult.measured['display']`, set by the testomatic-runner executor that took the
reading - see power.py/iomod.py) shown alongside PASS when the executor provides one (#13); a
step type with no reading to show (BEEP, firmware uploads, etc.) just shows PASS/FAIL. A failing
check still gets its own indented message line below, since failure text can run long and
compressing it risks losing diagnostic detail.
"""
import subprocess
import tempfile
from pathlib import Path

import qrcode
from PIL import Image, ImageDraw, ImageFont
from testomatic.steps.firmware import FIRMWARE_STEP_TYPES

DOCKET_IMAGE_WIDTH = 576
FONT_SIZE = 33  # issue #10: was 22 - bumped ~50% for legibility on a printed receipt
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


def _line_width_chars():
    """How many monospace characters fit across the printable width (issue #11) - measured from
    the actual loaded font's own glyph metrics rather than a hardcoded guess, so this stays
    correct if FONT_SIZE or DOCKET_IMAGE_WIDTH changes, and stays in sync with what
    render_docket_image() will actually draw (it loads the same font the same way)."""
    char_width = _load_font().getlength('0')
    return max(1, int((DOCKET_IMAGE_WIDTH - 2 * MARGIN) / char_width))


def _justify(left, right, width):
    """`left` and `right` on one line, `right` flush to the far end of a `width`-character line
    and `left` filling the rest - used for both the Automatic Checks pass/fail column and the
    Manual Checks checkbox column, so both stretch to the paper's full width (issue #11) instead
    of only as far as their own longest entry. `left` is truncated with a trailing ellipsis if it
    doesn't fit; `right` is never truncated except in the degenerate case where it alone exceeds
    `width` (a screen this narrow isn't a real receipt printer)."""
    if len(right) >= width:
        return right[:width]
    available = width - len(right)
    if len(left) > available:
        left = (left[:available - 1] + '…') if available > 1 else left[:available]
    return left.ljust(available) + right


def _rule(label, width, fill='='):
    """A `label` centred within a `fill`-character rule line, `width` characters wide - used for
    the section headers/footer so they stretch to the same width as everything else (issue #11)."""
    return f' {label} '.center(width, fill)


def build_docket_lines(test_suite, serial_number, operator_name, report, manual_checks, finished_dt, device_details_url):
    """Builds the Test Docket's plain-text content: header (including firmware versions - see
    below), automatic checks (from `report`, testomatic-runner's RunReport), a manual-checks
    checklist, and a footer - laid out to match the legacy prototype's output (see
    testomatic-ui#8 and 3990-MCM-20251019104515.txt).

    Firmware versions (register#124): there's no separate "firmware version" field anywhere in
    testomatic-ui/testomatic-runner/Register - the decision (see register#124's discussion) is to
    report every UPLOAD_FIRMWARE_* step's own *name* instead, since that's already unique per
    step and a Test Suite author is expected to name each one after what it uploads (e.g.
    "Firmware v8.1.1", not "Upload Firmware" - this matters more now that the name ends up on the
    printed docket). All such steps are reported, including a step whose firmware is later
    overwritten by a subsequent step in the same run (e.g. a bootloader/test image flashed early,
    replaced by the production image at the end) - nothing here tries to collapse multiple
    firmware steps for what's presumably the same MCU down to "the" final version. This list is
    a special case, independent of `include_on_docket`: unlike the pass/fail line each step gets
    in "Automatic checks" below (which a passing step can opt out of via that flag), a firmware
    step's name always appears here regardless, since it's reporting what's physically on the
    board rather than a pass/fail result.
    """
    line_chars = _line_width_chars()
    design = test_suite.design
    lines = [
        'Test Report'.center(line_chars),
        'www.SuperLab.au'.center(line_chars),
        '',
        f'Client: {design.client_name}',
        f'Device: {design.name}',
        f'Serial: {serial_number}',
        f'H/W version: {design.hw_version}',
    ]

    firmware_outcomes = [o for o in report.outcomes if o.step.step_type in FIRMWARE_STEP_TYPES]
    if firmware_outcomes:
        lines.append('Firmware:')
        for outcome in firmware_outcomes:
            suffix = '' if outcome.result.passed else ' (FAILED)'
            lines.append(f'  {outcome.step.name}{suffix}')

    lines += [
        f'Tested by: {operator_name}',
        finished_dt.strftime('%Y-%m-%d %H:%M:%S %z'),
        '',
        _rule('Automatic checks', line_chars),
    ]

    for outcome in report.outcomes:
        # issue #123: a step marked include_on_docket=False is left off the docket, but only
        # while it's passing - a failure is never silently missing from the printed record.
        if not outcome.step.include_on_docket and outcome.result.passed:
            continue
        if outcome.result.passed:
            # issue #13: a step that took a measurement (e.g. READ_RAIL_VOLTAGE) reports it
            # alongside PASS; a step with nothing to measure (BEEP, firmware uploads, ...) just
            # shows PASS - see power.py/iomod.py for which step types set measured['display'].
            display = outcome.result.measured.get('display')
            result_text = f'PASS  {display}' if display else 'PASS'
            lines.append(_justify(outcome.step.name, result_text, line_chars))
        else:
            lines.append(_justify(outcome.step.name, 'FAIL', line_chars))
            lines.append(f'  FAILED: {outcome.result.message}')

    if report.aborted:
        lines.append('')
        lines.append('ABORTED: abort-on-fail step failed, all power rails turned off')

    lines.append('')
    lines.append(_rule('Manual checks', line_chars))
    if manual_checks:
        for check in manual_checks:
            lines.append(_justify(check.text, '[  ]', line_chars))

    lines.append('')
    lines.append(f'Test version: v{test_suite.version} ({test_suite.register_created_dt.date()})')
    lines.append(device_details_url)
    lines.append(_rule('test end', line_chars, fill='-'))
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
