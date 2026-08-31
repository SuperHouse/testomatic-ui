# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 SuperHouse Automation Pty Ltd <info@superhouse.tv>
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from .models import Design, TestSuite
from .sync import fetch_test_suite_package, sync_test_suites


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
