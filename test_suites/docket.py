# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 SuperHouse Automation Pty Ltd <info@superhouse.tv>
"""Formats and prints a Test Docket after a Test Suite run (issue #8).

The docket is rendered as a single bitmap image (not plain text) so a QR code can sit alongside
the text on one seamless thermal-printer receipt - see build_docket_lines()/render_docket_image()
below. DOCKET_IMAGE_WIDTH/FONT_SIZE assume an 80mm receipt printer at 203dpi (matching the sample
"Printer_POS-80" queue name already in DeviceSettings.printer_name's help text) - confirmed against
a real Printer_POS-80 test print (2026-09-17): its CUPS queue reports a printable area of 2.83in
wide, which at 203dpi is ~574.5px, matching DOCKET_IMAGE_WIDTH=576 closely enough that no width
change is needed. The one real-hardware surprise was the printable *length*, not width: CUPS's
Media Size defaults to a fixed 210mm (~8.27in) page rather than a continuous roll - see the
README's "Printer Setup (CUPS)" section for the per-device fix (Media Size -> 80(72mm) x 3276mm).
Cut Options may also need per-installation tuning; also documented there. That page-length limit
also explained an initially-puzzling *width* symptom on the first test print: the docket's native
bitmap (576x2082px) is much taller relative to its width than the printable box was at 210mm, so
CUPS's aspect-preserving fit-to-page scaling shrank the whole image - including its width, leaving
an oversized blank margin on one side - to keep the too-tall content on one page. A second test
print after the Media Size fix confirmed this: with height no longer the constraint, it printed
using the paper's full width as expected, with no code change needed. (This also means the PNG
saved by render_docket_image() doesn't need explicit DPI metadata - the fit-to-page math above
matches observed behaviour using pixel dimensions and the printer's native 203dpi alone, with no
sign CUPS/the driver falls back to a guessed DPI for an untagged PNG.)

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
FOOTER_FONT_SIZE = 22  # smaller trailing "Test version"/URL/test-end block, set off from the body
LINE_SPACING = 6
MARGIN = 16
QR_SIZE = 240
RULE_THICKNESS = 3  # drawn section-divider lines (Automated Tests/Manual Checks), in px

# Common monospace TTF locations, tried in order - the first is what Raspberry Pi OS/Debian ships
# as part of the fonts-dejavu-core package. The second is where `brew install --cask font-dejavu`
# puts the same font family on macOS (the same TTF filenames, so this is the one dev-machine
# addition that keeps the "tried in order" list working unmodified on the Pi) - handy so a docket
# preview rendered on a dev Mac actually looks like what prints on the device, instead of silently
# falling back to Pillow's tiny built-in bitmap font (see _load_font()) below.
_FONT_PATHS = [
    '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf',
    str(Path.home() / 'Library/Fonts/DejaVuSansMono.ttf'),
]
_FONT_PATHS_BOLD = [
    '/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf',
    str(Path.home() / 'Library/Fonts/DejaVuSansMono-Bold.ttf'),
]


def _load_font(bold=False, size=FONT_SIZE):
    for path in (_FONT_PATHS_BOLD if bold else _FONT_PATHS):
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _line_width_chars(bold=False, font_size=FONT_SIZE):
    """How many monospace characters fit across the printable width (issue #11) - measured from
    the actual loaded font's own glyph metrics rather than a hardcoded guess, so this stays
    correct if FONT_SIZE or DOCKET_IMAGE_WIDTH changes, and stays in sync with what
    render_docket_image() will actually draw (it loads the same font the same way). `bold`/
    `font_size` let a caller measure against a non-default font - e.g. the smaller footer block -
    since DejaVu Sans Mono Bold isn't guaranteed to share the regular weight's advance width."""
    char_width = _load_font(bold=bold, size=font_size).getlength('0')
    return max(1, int((DOCKET_IMAGE_WIDTH - 2 * MARGIN) / char_width))


class DocketLine(str):
    """One line of Test Docket content, tagged with how render_docket_image() should draw it.
    Subclasses str instead of being a separate dataclass so the existing plain-text consumers of
    build_docket_lines()'s output keep working with no change - TestRun.docket_text's
    '\\n'.join(lines), and every test that does `self.assertIn('some text', lines)` - while
    render_docket_image() reads the extra bold/font_size/rule attributes to choose a font or draw
    a horizontal rule instead of text. A plain str (as some tests pass straight to
    render_docket_image()) works too: render_docket_image() falls back to non-bold/FONT_SIZE/not-
    a-rule for anything without these attributes."""

    bold: bool
    font_size: int
    rule: bool

    def __new__(cls, text='', bold=False, font_size=None, rule=False):
        line = str.__new__(cls, text)
        line.bold = bold
        line.font_size = font_size or FONT_SIZE
        line.rule = rule
        return line


def _justify(left, right, width):
    """`left` and `right` on one line, `right` flush to the far end of a `width`-character line
    and `left` filling the rest - used for both the Automatic Checks pass/fail column and the
    Manual Checks checkbox column, so both stretch to the paper's full width (issue #11) instead
    of only as far as their own longest entry. `left` is truncated with a trailing ellipsis if it
    doesn't fit, keeping at least one space before `right` even when `left` alone would otherwise
    exactly fill the available width (confirmed on a real printout: "Powers from prog header[  ]"
    and "Trigger activates valve[  ]" both ran straight into the checkbox with no gap, since each
    label happened to be exactly as long as `available`) - `right` is never truncated except in
    the degenerate case where it alone exceeds `width` (a screen this narrow isn't a real receipt
    printer)."""
    if len(right) >= width:
        return right[:width]
    available = width - len(right) - 1  # always keep at least one space before `right`
    if len(left) > available:
        left = (left[:available - 1] + '…') if available > 1 else left[:available]
    return left.ljust(available) + ' ' + right


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
        DocketLine('Test Report'.center(line_chars)),
        DocketLine('www.SuperLab.au'.center(line_chars)),
        DocketLine(''),
        DocketLine(design.client_name),
        DocketLine(design.name, bold=True),
        DocketLine(f'Serial: {serial_number}'),
        DocketLine(f'Version v{design.hw_version}'),
    ]

    # register#124: a firmware step's name always appears here (no "Firmware:" header needed -
    # the step names themselves already say what they are), left-aligned like everything else.
    firmware_outcomes = [o for o in report.outcomes if o.step.step_type in FIRMWARE_STEP_TYPES]
    for outcome in firmware_outcomes:
        suffix = '' if outcome.result.passed else ' (FAILED)'
        lines.append(DocketLine(f'{outcome.step.name}{suffix}'))

    lines += [
        DocketLine(f'Tested by {operator_name}'),
        DocketLine(finished_dt.strftime('%Y-%m-%d %H:%M:%S %z')),
        DocketLine(''),
        DocketLine('-' * line_chars, rule=True),
        DocketLine('Automated Tests'.center(line_chars), bold=True),
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
            lines.append(DocketLine(_justify(outcome.step.name, result_text, line_chars)))
        else:
            lines.append(DocketLine(_justify(outcome.step.name, 'FAIL', line_chars)))
            lines.append(DocketLine(f'  FAILED: {outcome.result.message}'))

    if report.aborted:
        lines.append(DocketLine(''))
        lines.append(DocketLine('ABORTED: abort-on-fail step failed, all power rails turned off'))

    lines.append(DocketLine(''))
    lines.append(DocketLine('-' * line_chars, rule=True))
    lines.append(DocketLine('Manual Checks'.center(line_chars), bold=True))
    if manual_checks:
        for check in manual_checks:
            lines.append(DocketLine(_justify(check.text, '[  ]', line_chars)))

    footer_line_chars = _line_width_chars(font_size=FOOTER_FONT_SIZE)
    lines.append(DocketLine(''))
    lines.append(DocketLine(
        f'Test version: v{test_suite.version} ({test_suite.register_created_dt.date()})',
        font_size=FOOTER_FONT_SIZE,
    ))
    lines.append(DocketLine(device_details_url, font_size=FOOTER_FONT_SIZE))
    lines.append(DocketLine(_rule('test end', footer_line_chars, fill='-'), font_size=FOOTER_FONT_SIZE))
    return lines


def render_docket_image(lines, device_details_url):
    """Renders `lines` and a QR code for `device_details_url` onto a single bitmap, ready to be
    handed to print_docket_image(). Returns a PIL.Image.Image.

    Each `line` may be a plain str (drawn non-bold at FONT_SIZE) or a DocketLine, whose bold/
    font_size/rule attributes pick a font or, for a rule line, draw a horizontal divider instead
    of text - `getattr(..., default)` reads them so a plain str (as some tests pass directly)
    doesn't need the DocketLine wrapper."""
    fonts = {}  # (bold, font_size) -> ImageFont, loaded once per combination actually used

    def font_for(bold, font_size):
        key = (bold, font_size)
        if key not in fonts:
            fonts[key] = _load_font(bold=bold, size=font_size)
        return fonts[key]

    def line_height_of(line):
        return getattr(line, 'font_size', FONT_SIZE) + LINE_SPACING

    qr_image = qrcode.make(device_details_url).resize((QR_SIZE, QR_SIZE)).convert('L')

    height = MARGIN * 3 + sum(line_height_of(line) for line in lines) + QR_SIZE
    image = Image.new('L', (DOCKET_IMAGE_WIDTH, height), color=255)
    draw = ImageDraw.Draw(image)

    y = MARGIN
    for line in lines:
        height_here = line_height_of(line)
        if getattr(line, 'rule', False):
            rule_y = y + height_here // 2
            draw.line([(MARGIN, rule_y), (DOCKET_IMAGE_WIDTH - MARGIN, rule_y)], fill=0, width=RULE_THICKNESS)
        else:
            font = font_for(getattr(line, 'bold', False), getattr(line, 'font_size', FONT_SIZE))
            draw.text((MARGIN, y), line, font=font, fill=0)
        y += height_here

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
