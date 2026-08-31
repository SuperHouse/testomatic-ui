# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 SuperHouse Automation Pty Ltd <info@superhouse.tv>
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render

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

    with test_suite.package_file.open('rb') as f:
        package = parse_test_suite_package(f)

    return render(request, 'test_suites/detail.html', {
        'test_suite': test_suite,
        'notes': package.notes,
        'steps': package.steps,
        'manual_checks': package.manual_checks,
    })
