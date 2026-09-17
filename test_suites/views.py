# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 SuperHouse Automation Pty Ltd <info@superhouse.tv>
import dataclasses
import io
import zoneinfo

from django.contrib.auth.decorators import login_required
from django.core.files.base import ContentFile
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.models import DeviceSettings

from . import docket
from .models import Design, TestRun, TestSuite
from .serial_number import extract_serial_number
from .sync import fetch_test_suite_package, sync_test_suites
from .test_suite_package import parse_test_suite_package


@login_required
def test_suite_list(request):
    q = request.GET.get('q', '').strip()
    designs = Design.objects.filter(test_suites__isnull=False).distinct().prefetch_related('test_suites')
    if q:
        designs = designs.filter(
            Q(sku__icontains=q) | Q(name__icontains=q) | Q(hw_version__icontains=q) | Q(client_name__icontains=q)
        )
    return render(request, 'test_suites/list.html', {'designs': designs, 'q': q})


@login_required
def test_suite_versions(request, design_id):
    design = get_object_or_404(Design, pk=design_id)
    return render(request, 'test_suites/versions.html', {'design': design, 'test_suites': design.test_suites.all()})


@login_required
def test_suite_update(request):
    if request.method == 'POST':
        sync_test_suites()
    return redirect('test_suites:list')


@login_required
def test_suite_fetch(request, suite_id):
    if request.method == 'POST':
        test_suite = get_object_or_404(TestSuite, pk=suite_id)
        fetch_test_suite_package(test_suite)
    return redirect('test_suites:list')


@login_required
def test_suite_detail(request, pk):
    test_suite = get_object_or_404(TestSuite, pk=pk)
    if not test_suite.package_file:
        raise Http404('This Test Suite Package has not been downloaded yet.')

    return render(request, 'test_suites/detail.html', _detail_context(test_suite))


@login_required
@require_POST
def test_suite_run(request, pk):
    test_suite = get_object_or_404(TestSuite, pk=pk)
    if not test_suite.package_file:
        raise Http404('This Test Suite Package has not been downloaded yet.')

    context = _detail_context(test_suite)

    raw_serial_number = request.POST.get('serial_number', '').strip()
    if not raw_serial_number:
        context['serial_number_error'] = 'Scan or enter a serial number before running the Test Suite.'
        return render(request, 'test_suites/detail.html', context)

    device_settings = context['device_settings']
    serial_number = extract_serial_number(raw_serial_number, device_settings.device_details_url_stem)
    context['serial_number'] = serial_number

    started_dt = timezone.now()
    run_result = _run_test_suite(test_suite)
    context['run_output'] = run_result.output
    context['run_passed'] = run_result.passed
    context['run_error'] = run_result.error

    if run_result.report is not None:
        test_run = _save_test_run(test_suite, serial_number, request.user, run_result, started_dt)
        _print_test_run_docket(test_run, run_result, device_settings)
        context['test_run'] = test_run

    return render(request, 'test_suites/detail.html', context)


@login_required
@require_POST
def test_run_reprint(request, pk):
    test_run = get_object_or_404(TestRun, pk=pk)
    device_settings = DeviceSettings.get_solo()

    if not device_settings.printer_name:
        test_run.docket_print_error = 'No printer is configured on this device (see Tester Settings).'
    else:
        try:
            with test_run.docket_image.open('rb') as f:
                image = docket.load_docket_image(f)
            docket.print_docket_image(image, device_settings.printer_name)
            test_run.docket_printed_dt = timezone.now()
            test_run.docket_print_error = ''
        except Exception as exc:
            test_run.docket_print_error = f'Reprint failed: {exc}'
    test_run.save(update_fields=['docket_printed_dt', 'docket_print_error'])

    context = _detail_context(test_run.test_suite)
    context['test_run'] = test_run
    return render(request, 'test_suites/detail.html', context)


def _detail_context(test_suite):
    with test_suite.package_file.open('rb') as f:
        package = parse_test_suite_package(f)

    return {
        'test_suite': test_suite,
        'notes': package.notes,
        'steps': package.steps,
        'manual_checks': package.manual_checks,
        'device_settings': DeviceSettings.get_solo(),
    }


@dataclasses.dataclass
class RunResult:
    output: str | None
    passed: bool | None
    error: str | None
    report: object | None = None  # testomatic.runner.RunReport - untyped here to avoid importing
    manual_checks: list = dataclasses.field(default_factory=list)  # testomatic.suite.ManualCheck


def _run_test_suite(test_suite):
    """Executes test_suite's downloaded package against real hardware via testomatic-runner.

    Returns a RunResult: `error` is set instead of `output`/`passed`/`report` if testomatic_io
    isn't available on this device (only installed via testomatic-runner's "pi" extra, on a real
    Testomatic Pi - see testomatic-runner's CLAUDE.md) or the suite couldn't be parsed/executed.
    `report`/`manual_checks` carry the structured result so the caller can persist a TestRun and
    format/print a Test Docket (see _save_test_run()/_print_test_run_docket() below) without
    re-parsing `output`'s already-formatted text.

    Passes this device's own DeviceSettings (core.models) firmware-upload tool paths through to
    TestRunner, so an UPLOAD_FIRMWARE_* step's executor (testomatic-runner's steps/firmware.py)
    uses this device's configured tool locations instead of assuming each is on $PATH.
    """
    try:
        from testomatic.runner import TestRunner, format_report
        from testomatic.suite import load_suite
        from testomatic_io import Chassis, TestModule
    except ImportError as exc:
        return RunResult(None, None, f'Test Runner hardware support is not available on this device: {exc}')

    device_settings = DeviceSettings.get_solo()

    try:
        suite = load_suite(test_suite.package_file.path)
        chassis = Chassis()
        chassis.init()
        test_module = TestModule()
        test_module.init()
        report = TestRunner(
            chassis, test_module,
            avrdude_path=device_settings.avrdude_path or None,
            openocd_path=device_settings.openocd_path or None,
            stm32cubeprogrammer_path=device_settings.stm32cubeprogrammer_path or None,
        ).run(suite)
    except Exception as exc:  # a parse/hardware-init failure must not crash the whole page
        return RunResult(None, None, f'Test run failed: {exc}')

    return RunResult(format_report(report, suite.manual_checks), report.passed, None, report, suite.manual_checks)


def _save_test_run(test_suite, serial_number, user, run_result, started_dt):
    """Persists the structured result of a completed run (issue #6) - only called when
    run_result.report is not None, i.e. testomatic-runner actually executed the suite."""
    report = run_result.report
    return TestRun.objects.create(
        test_suite=test_suite,
        serial_number=serial_number,
        operator=user,
        started_dt=started_dt,
        finished_dt=timezone.now(),
        passed=report.passed,
        aborted=report.aborted,
        report={
            'outcomes': [dataclasses.asdict(outcome) for outcome in report.outcomes],
            'aborted': report.aborted,
            'manual_checks': [dataclasses.asdict(check) for check in run_result.manual_checks],
        },
    )


def _print_test_run_docket(test_run, run_result, device_settings):
    """Formats test_run's Test Docket (issue #8) and prints it if a printer is configured.

    docket_text/docket_image are always saved regardless of whether printing itself succeeds, so
    a printer that's offline right now can still be fixed and reprinted from later via
    test_run_reprint() - reprinting resends this saved image rather than re-rendering, so a
    docket's exact appearance stays stable even if this function's rendering changes later.
    """
    device_details_url = device_settings.device_details_url_stem + test_run.serial_number
    operator_name = test_run.operator.get_full_name() or test_run.operator.get_username()
    # TestRun.finished_dt is stored in UTC (settings.USE_TZ) - converted to this device's own
    # configured timezone here, rather than docket.py knowing anything about DeviceSettings, so
    # the docket shows the time a human at this device actually experienced, not UTC.
    finished_dt = timezone.localtime(test_run.finished_dt, zoneinfo.ZoneInfo(device_settings.timezone))

    lines = docket.build_docket_lines(
        test_run.test_suite, test_run.serial_number, operator_name,
        run_result.report, run_result.manual_checks, finished_dt, device_details_url,
    )
    image = docket.render_docket_image(lines, device_details_url)

    # a Design thumbnail (docket.DocketImage) has no plain-text form, so it's skipped here rather
    # than breaking str.join() - docket_text is a record of the printed words, not a full replica.
    test_run.docket_text = '\n'.join(line for line in lines if isinstance(line, str))
    buffer = io.BytesIO()
    image.save(buffer, format='PNG')
    test_run.docket_image.save(f'{test_run.pk}.png', ContentFile(buffer.getvalue()), save=False)

    if device_settings.printer_name:
        try:
            docket.print_docket_image(image, device_settings.printer_name)
            test_run.docket_printed_dt = timezone.now()
        except Exception as exc:
            test_run.docket_print_error = f'Docket print failed: {exc}'

    test_run.save()
