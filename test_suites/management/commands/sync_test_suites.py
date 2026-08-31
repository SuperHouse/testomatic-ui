# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 SuperHouse Automation Pty Ltd <info@superhouse.tv>
from django.core.management.base import BaseCommand

from test_suites.sync import sync_test_suites


class Command(BaseCommand):
    help = "Sync the local Design/Test Suite cache from Register, and fetch each design's latest Test Suite Package."

    def handle(self, *args, **options):
        sync_test_suites()
        self.stdout.write(self.style.SUCCESS('Test Suites synced.'))
