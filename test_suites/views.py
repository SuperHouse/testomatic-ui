# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 SuperHouse Automation Pty Ltd <info@superhouse.tv>
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .models import Design, TestSuite
from .sync import fetch_test_suite_package, sync_test_suites
from .test_suite_package import parse_test_suite_package


@login_required
def test_suite_list(request):
    designs = Design.objects.filter(test_suites__isnull=False).distinct().prefetch_related('test_suites')
    return render(request, 'test_suites/list.html', {'designs': designs})


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
    context['run_output'], context['run_passed'], context['run_error'] = _run_test_suite(test_suite)
    return render(request, 'test_suites/detail.html', context)


def _detail_context(test_suite):
    with test_suite.package_file.open('rb') as f:
        package = parse_test_suite_package(f)

    return {
        'test_suite': test_suite,
        'notes': package.notes,
        'steps': package.steps,
        'manual_checks': package.manual_checks,
    }


def _run_test_suite(test_suite):
    """Executes test_suite's downloaded package against real hardware via testomatic-runner.

    Returns (output_text, passed, error_message) - error_message is set instead of output/passed
    if testomatic_io isn't available on this device (only installed via testomatic-runner's "pi"
    extra, on a real Testomatic Pi - see testomatic-runner's CLAUDE.md) or the suite couldn't be
    parsed/executed. Not stored anywhere yet - the operator sees it once, for this request only.
    """
    try:
        from testomatic.runner import TestRunner, format_report
        from testomatic.suite import load_suite
        from testomatic_io import Chassis, TestModule
    except ImportError as exc:
        return None, None, f'Test Runner hardware support is not available on this device: {exc}'

    try:
        suite = load_suite(test_suite.package_file.path)
        chassis = Chassis()
        chassis.init()
        test_module = TestModule()
        test_module.init()
        report = TestRunner(chassis, test_module).run(suite)
    except Exception as exc:  # a parse/hardware-init failure must not crash the whole page
        return None, None, f'Test run failed: {exc}'

    return format_report(report, suite.manual_checks), report.passed, None
