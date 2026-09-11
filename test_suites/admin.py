# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 SuperHouse Automation Pty Ltd <info@superhouse.tv>
from django.contrib import admin

from .models import Design, TestRun, TestSuite


@admin.register(Design)
class DesignAdmin(admin.ModelAdmin):
    list_display = ('sku', 'name', 'hw_version', 'register_id', 'synced_dt')
    search_fields = ('sku', 'name')


@admin.register(TestSuite)
class TestSuiteAdmin(admin.ModelAdmin):
    list_display = ('design', 'version', 'status', 'register_created_dt', 'package_fetched_dt')
    list_filter = ('status',)


@admin.register(TestRun)
class TestRunAdmin(admin.ModelAdmin):
    list_display = ('test_suite', 'serial_number', 'operator', 'passed', 'aborted', 'finished_dt', 'docket_printed_dt')
    list_filter = ('passed', 'aborted')
    search_fields = ('serial_number',)
    readonly_fields = (
        'test_suite', 'serial_number', 'operator', 'started_dt', 'finished_dt', 'passed', 'aborted',
        'report', 'docket_text', 'docket_image', 'docket_printed_dt', 'docket_print_error',
    )
