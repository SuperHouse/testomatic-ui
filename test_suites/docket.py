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
converts the printable pixel width into a character budget, and text that needs to align (the
header/section rules, Automatic Checks' PASS/FAIL column) is padded or right-aligned against that
same budget via `_justify()`/`_rule()`, rather than each padding itself to its own longest entry -
this is what makes the docket actually use the full paper width (#11) instead of just the left
portion the widest line happens to reach. Automatic Checks are one line per check, name left and
PASS/FAIL right-aligned (#12) - always exactly "PASS"/"FAIL", so that column actually lines up
down the page - with a measured value (`StepResult.measured['display']`, set by the
testomatic-runner executor that took the reading - see power.py/iomod.py, on a passing *or*
failing result) shown as "name: value" on the left when the executor provides one (#13); a step
type with no reading to show (BEEP, firmware uploads, etc.) just shows the name. A failing check
still gets its own indented message line below, since failure text can run long and compressing
it risks losing diagnostic detail. Manual Checks no longer uses `_justify()` - see DocketLine's
`checkbox` flag and `_truncate_to_width()`, a pixel-measured (not character-count) alternative
adopted after `_justify()`'s fixed-width bracket text ("[  ]") left too little room for the two
longest labels on a real printout.

`build_docket_lines()`'s output isn't purely text: alongside `DocketLine` (which subclasses `str`,
so plain-text consumers like TestRun.docket_text keep working) it can include a `DocketImage` (the
Design thumbnail) and a `DocketResult` (the large pass/fail/aborted headline near the top of the
docket) - see each class's own docstring. The test date/time is printed in whatever timezone the
caller already converted it to (see views.py:_print_test_run_docket(), which uses this device's
own DeviceSettings.timezone) - this module has no timezone awareness of its own.
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
CHECKBOX_SIZE = 28  # a drawn tick-box, in place of literal "[  ]" text (issue #10 hand-tuning:
# takes noticeably less horizontal room than 4 monospace characters, which is what was forcing
# "Powers from prog header"/"Trigger activates valve" to truncate on a real printout even after
# _justify() reserved a minimum gap - see the two tests this replaced), still large enough to
# comfortably hand-tick with a pen
CHECKBOX_GAP = 10  # between a manual check's label text and its drawn box
CHECKBOX_THICKNESS = 2  # stroke width of the drawn box's outline, in px
THUMBNAIL_MAX_HEIGHT = 300  # cap on a pasted Design thumbnail's height, so a large source render
# doesn't dominate the receipt - width is already capped at the printable width like everything
# else (DOCKET_IMAGE_WIDTH - 2*MARGIN)
RESULT_FONT_SIZE = 60  # the large Passed/FAILED/Aborted headline near the top of the docket, so
# the overall outcome is visible without reading the rest of the report
RESULT_ICON_SIZE = 50  # a drawn tick/cross beside the headline word, not a font glyph - not every
# TTF has a checkmark/cross in it, and drawing it matches how the rule lines/checkboxes elsewhere
# on the docket are already drawn rather than relying on a specific font's glyph coverage
RESULT_ICON_THICKNESS = 8
RESULT_ICON_GAP = 20  # between the icon and the headline word

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
    render_docket_image() reads the extra bold/font_size/rule/checkbox attributes to choose a font,
    or draw a horizontal rule or a manual-check tick-box instead of/alongside text. A plain str (as
    some tests pass straight to render_docket_image()) works too: render_docket_image() falls back
    to non-bold/FONT_SIZE/not-a-rule/no-checkbox for anything without these attributes."""

    bold: bool
    font_size: int
    rule: bool
    checkbox: bool

    def __new__(cls, text='', bold=False, font_size=None, rule=False, checkbox=False):
        line = str.__new__(cls, text)
        line.bold = bold
        line.font_size = font_size or FONT_SIZE
        line.rule = rule
        line.checkbox = checkbox
        return line


class DocketImage:
    """A raster image embedded in the Test Docket's content list alongside DocketLine text lines -
    so far just a Design's thumbnail (a PCB render, register issue #117's PCB_TOP Design Asset).
    render_docket_image() pastes `image` centred instead of drawing text for one of these; a plain
    DocketImage instance (rather than a DocketLine subclassing str) is fine here since nothing
    needs this to behave like text - `build_docket_lines()`'s output already isn't just plain text
    once bold/rule/checkbox lines are mixed in, and views.py's TestRun.docket_text assignment
    filters to `isinstance(line, str)` before joining rather than needing every entry to be one.

    Scaled to fit within `max_width`x`max_height` at construction time (never upscaled), so the
    same already-sized image is used both to measure the docket's total height and to paste it,
    rather than computing the size twice. Composited onto a white background first regardless of
    the source's own mode, since a PCB render is often a transparent-background PNG and pasting
    that directly onto the docket's white canvas without flattening would print stray black where
    the alpha channel was transparent."""

    def __init__(self, image, max_width, max_height):
        image = image.convert('RGBA')
        background = Image.new('RGBA', image.size, (255, 255, 255, 255))
        image = Image.alpha_composite(background, image).convert('L')

        scale = min(max_width / image.width, max_height / image.height, 1)
        if scale < 1:
            image = image.resize((max(1, round(image.width * scale)), max(1, round(image.height * scale))))
        self.image = image


class DocketResult:
    """The Test Docket's large pass/fail/aborted headline, placed below the test date so the
    overall outcome is visible without reading the rest of the report. `icon` is 'tick' or
    'cross' - which shape render_docket_image() draws beside `word` (see _draw_result_icon()) -
    both drawn together as one centred unit at RESULT_FONT_SIZE/RESULT_ICON_SIZE, distinct from
    DocketLine since neither the oversized font nor the icon fit that class's model of one line
    of left-aligned text. RunReport only distinguishes passed/failed/aborted today - a future new
    outcome kind belongs here, in build_docket_lines()'s outcome_word/outcome_icon selection."""

    def __init__(self, word, icon):
        self.word = word
        self.icon = icon


def _draw_result_icon(draw, icon, left, top, size, thickness):
    """Draws a DocketResult's tick or cross, `size` px square with its top-left corner at
    (`left`, `top`) - a drawn shape rather than a font glyph, see DocketResult's docstring for
    why. `joint='curve'` on the tick's 2-segment polyline rounds the vertex instead of leaving a
    thickness-sized notch where the two strokes meet."""
    if icon == 'tick':
        points = [
            (left, top + size * 0.55),
            (left + size * 0.38, top + size * 0.85),
            (left + size, top + size * 0.15),
        ]
        draw.line(points, fill=0, width=thickness, joint='curve')
    else:
        draw.line([(left, top), (left + size, top + size)], fill=0, width=thickness)
        draw.line([(left, top + size), (left + size, top)], fill=0, width=thickness)


def _truncate_to_width(text, font, max_width):
    """`text`, shortened with a trailing ellipsis if it doesn't fit in `max_width` px of `font` -
    the pixel-accurate counterpart to _justify()'s character-count truncation, used where a line
    shares its row with something drawn (a manual check's tick-box) rather than more text, so
    there's no fixed character budget to truncate against."""
    if font.getlength(text) <= max_width:
        return text
    while text and font.getlength(text + '…') > max_width:
        text = text[:-1]
    return text + '…'


def _wrap_to_width(text, font, max_width):
    """Word-wraps `text` into a list of lines that each fit within `max_width` px of `font`,
    breaking only at spaces - used for the Device name, which (unlike every other line on the
    docket) used to have no overflow protection at all: a name too long for the printable width
    just got silently clipped off the canvas edge, since draw.text() doesn't wrap or truncate on
    its own. A single word that alone doesn't fit within `max_width` falls back to
    _truncate_to_width() for that one line rather than word-wrap leaving it to overflow anyway."""
    words = text.split()
    if not words:
        return ['']
    lines = []
    current = ''
    for word in words:
        candidate = f'{current} {word}'.strip()
        if font.getlength(candidate) <= max_width:
            current = candidate
            continue
        if current:
            lines.append(current)
        current = word if font.getlength(word) <= max_width else _truncate_to_width(word, font, max_width)
    lines.append(current)
    return lines


def _justify(left, right, width):
    """`left` and `right` on one line, `right` flush to the far end of a `width`-character line
    and `left` filling the rest - used for the Automatic Checks pass/fail column, so it stretches
    to the paper's full width (issue #11) instead of only as far as its own longest entry. (The
    Manual Checks checklist used to share this same helper against a literal "[  ]" - see
    _truncate_to_width()/CHECKBOX_SIZE instead: a real printout showed "Powers from prog
    header[  ]"/"Trigger activates valve[  ]" running straight into the checkbox with no gap even
    after the fix below, since 4 monospace characters of bracket left too little room; a drawn
    tick-box costs less horizontal space and a pixel-measured truncation replaced this character-
    count one for that column.) `left` is truncated with a trailing ellipsis if it doesn't fit,
    keeping at least one space before `right` even when `left` alone would otherwise exactly fill
    the available width - `right` is never truncated except in the degenerate case where it alone
    exceeds `width` (a screen this narrow isn't a real receipt printer)."""
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

    `finished_dt` is printed via a plain strftime() with no timezone conversion of its own - it's
    expected to already be in whatever zone the caller wants shown (see
    views.py:_print_test_run_docket(), which converts from TestRun.finished_dt's stored UTC into
    this device's own DeviceSettings.timezone before calling this function), so this stays
    unaware of DeviceSettings/device config, matching every other value here already being
    resolved by the caller.

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
    lines: list[DocketLine | DocketImage | DocketResult] = [
        DocketLine('Test Report'.center(line_chars)),
        DocketLine('www.SuperLab.au'.center(line_chars)),
        DocketLine(''),
        DocketLine(design.client_name),
    ]
    max_name_px = DOCKET_IMAGE_WIDTH - 2 * MARGIN
    for name_line in _wrap_to_width(design.name, _load_font(bold=True), max_name_px):
        lines.append(DocketLine(name_line, bold=True))
    lines.append(DocketLine(f'v{design.hw_version}'))

    if design.thumbnail:
        max_width = DOCKET_IMAGE_WIDTH - 2 * MARGIN
        lines.append(DocketImage(Image.open(design.thumbnail), max_width, THUMBNAIL_MAX_HEIGHT))

    lines.append(DocketLine(f'Serial #{serial_number}'))

    # register#124: a firmware step's name always appears here (no "Firmware:" header needed -
    # the step names themselves already say what they are), left-aligned like everything else.
    firmware_outcomes = [o for o in report.outcomes if o.step.step_type in FIRMWARE_STEP_TYPES]
    for outcome in firmware_outcomes:
        suffix = '' if outcome.result.passed else ' (FAILED)'
        lines.append(DocketLine(f'{outcome.step.name}{suffix}'))

    # the large pass/fail/aborted headline just below the date - see DocketResult's docstring for
    # why an aborted run gets its own word/icon rather than folding into failed.
    if report.aborted:
        outcome_word, outcome_icon = 'Aborted', 'cross'
    elif report.passed:
        outcome_word, outcome_icon = 'Passed', 'tick'
    else:
        outcome_word, outcome_icon = 'FAILED', 'cross'

    lines += [
        DocketLine('-' * line_chars, rule=True),
        DocketLine(f'Tested by {operator_name}'),
        DocketLine(finished_dt.strftime('%Y-%m-%d %H:%M:%S %z')),
        DocketResult(outcome_word, outcome_icon),
        DocketLine(''),
        DocketLine('-' * line_chars, rule=True),
        DocketLine('Automated Tests'.center(line_chars), bold=True),
    ]

    for outcome in report.outcomes:
        # issue #123: a step marked include_on_docket=False is left off the docket, but only
        # while it's passing - a failure is never silently missing from the printed record.
        if not outcome.step.include_on_docket and outcome.result.passed:
            continue
        # issue #13: a step that took a measurement (e.g. READ_RAIL_VOLTAGE) reports its value
        # alongside the step name, left of the PASS/FAIL column - not appended after PASS/FAIL as
        # it used to be, which left the PASS/FAIL word itself at a different column on every line
        # depending on whether/how long a value was, rather than forming a straight column like
        # every other right-aligned line on the docket (see power.py/iomod.py for which step
        # types set measured['display'], on a passing *or* failing result - a threshold check
        # like READ_RAIL_VOLTAGE still measures a value when the reading is the reason it failed).
        display = outcome.result.measured.get('display')
        name = f'{outcome.step.name}: {display}' if display else outcome.step.name
        if outcome.result.passed:
            lines.append(DocketLine(_justify(name, 'PASS', line_chars)))
        else:
            lines.append(DocketLine(_justify(name, 'FAIL', line_chars)))
            lines.append(DocketLine(f'  FAILED: {outcome.result.message}'))

    if report.aborted:
        lines.append(DocketLine(''))
        lines.append(DocketLine('ABORTED: abort-on-fail step failed, all power rails turned off'))

    lines.append(DocketLine(''))
    lines.append(DocketLine('-' * line_chars, rule=True))
    lines.append(DocketLine('Manual Checks'.center(line_chars), bold=True))
    if manual_checks:
        font = _load_font()
        max_label_px = DOCKET_IMAGE_WIDTH - 2 * MARGIN - CHECKBOX_SIZE - CHECKBOX_GAP
        for check in manual_checks:
            label = _truncate_to_width(check.text, font, max_label_px)
            lines.append(DocketLine(label, checkbox=True))

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

    Each `line` may be a plain str (drawn non-bold at FONT_SIZE), a DocketLine, whose bold/
    font_size/rule/checkbox attributes pick a font, draw a horizontal divider instead of text (a
    rule line), or draw a manual check's tick-box alongside its label text (a checkbox line) -
    `getattr(..., default)` reads them so a plain str (as some tests pass directly) doesn't need
    the DocketLine wrapper - a DocketImage, pasted centred instead of any of the above - or a
    DocketResult, drawing its icon and large word together as one centred unit."""
    fonts = {}  # (bold, font_size) -> ImageFont, loaded once per combination actually used

    def font_for(bold, font_size):
        key = (bold, font_size)
        if key not in fonts:
            fonts[key] = _load_font(bold=bold, size=font_size)
        return fonts[key]

    def line_height_of(line):
        if isinstance(line, DocketImage):
            return line.image.height
        if isinstance(line, DocketResult):
            return RESULT_FONT_SIZE + LINE_SPACING
        return getattr(line, 'font_size', FONT_SIZE) + LINE_SPACING

    qr_image = qrcode.make(device_details_url).resize((QR_SIZE, QR_SIZE)).convert('L')

    height = MARGIN * 3 + sum(line_height_of(line) for line in lines) + QR_SIZE
    image = Image.new('L', (DOCKET_IMAGE_WIDTH, height), color=255)
    draw = ImageDraw.Draw(image)

    y = MARGIN
    for line in lines:
        height_here = line_height_of(line)
        if isinstance(line, DocketImage):
            image.paste(line.image, ((DOCKET_IMAGE_WIDTH - line.image.width) // 2, y))
            y += height_here
            continue
        if isinstance(line, DocketResult):
            result_font = font_for(True, RESULT_FONT_SIZE)
            content_width = RESULT_ICON_SIZE + RESULT_ICON_GAP + result_font.getlength(line.word)
            icon_left = (DOCKET_IMAGE_WIDTH - content_width) / 2
            icon_top = y + (height_here - RESULT_ICON_SIZE) / 2
            _draw_result_icon(draw, line.icon, icon_left, icon_top, RESULT_ICON_SIZE, RESULT_ICON_THICKNESS)
            draw.text((icon_left + RESULT_ICON_SIZE + RESULT_ICON_GAP, y), line.word, font=result_font, fill=0)
            y += height_here
            continue
        if getattr(line, 'rule', False):
            rule_y = y + height_here // 2
            draw.line([(MARGIN, rule_y), (DOCKET_IMAGE_WIDTH - MARGIN, rule_y)], fill=0, width=RULE_THICKNESS)
        else:
            font = font_for(getattr(line, 'bold', False), getattr(line, 'font_size', FONT_SIZE))
            draw.text((MARGIN, y), line, font=font, fill=0)
            if getattr(line, 'checkbox', False):
                box_left = DOCKET_IMAGE_WIDTH - MARGIN - CHECKBOX_SIZE
                box_top = y + (height_here - CHECKBOX_SIZE) // 2
                draw.rectangle(
                    [box_left, box_top, box_left + CHECKBOX_SIZE, box_top + CHECKBOX_SIZE],
                    outline=0, width=CHECKBOX_THICKNESS,
                )
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
