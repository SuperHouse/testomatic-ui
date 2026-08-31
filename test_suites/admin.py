# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 SuperHouse Automation Pty Ltd <info@superhouse.tv>
from django.contrib import admin

from .models import Design, TestSuite


@admin.register(Design)
class DesignAdmin(admin.ModelAdmin):
    list_display = ('sku', 'name', 'hw_version', 'register_id', 'synced_dt')
    search_fields = ('sku', 'name')


@admin.register(TestSuite)
class TestSuiteAdmin(admin.ModelAdmin):
    list_display = ('design', 'version', 'status', 'register_created_dt', 'package_fetched_dt')
    list_filter = ('status',)
