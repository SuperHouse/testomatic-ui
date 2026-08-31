# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 SuperHouse Automation Pty Ltd <info@superhouse.tv>
"""Refreshes the local Design/TestSuite cache from Register. Shared by the sync_test_suites
management command (cron-able) and the "Update Now" view - one code path for both."""
import mimetypes

from django.core.files.base import ContentFile
from django.utils import timezone

from core.register_client import fetch_design_asset, fetch_test_suite, list_design_assets, list_designs, list_test_suites
from .models import Design, TestSuite


def sync_test_suites():
    """Upserts Design/TestSuite metadata from Register (insert-only for TestSuite - Register
    never mutates a finalised suite), then ensures the latest version of every design's Test
    Suite has its package downloaded. Never deletes rows or files, and never re-fetches or
    touches an already-fetched package, including one that's no longer the latest version."""
    for data in list_designs():
        Design.objects.update_or_create(
            register_id=data['id'],
            defaults={
                'sku': data['sku'],
                'name': data['name'],
                'client_name': (data.get('client') or {}).get('company_name') or '',
                'hw_version': data['hw_version'] or '',
                'description': data['description'] or '',
            },
        )

    designs_by_register_id = {design.register_id: design for design in Design.objects.all()}

    for data in list_test_suites():
        design = designs_by_register_id.get(data['design_id'])
        if design is None:
            # Test Suite for a design our API key can't/didn't see via list_designs() - skip
            # rather than fail the whole sync over one inconsistent row.
            continue
        TestSuite.objects.get_or_create(
            register_id=data['id'],
            defaults={
                'design': design,
                'version': data['version'],
                'status': data['status'],
                'register_created_dt': data['created_dt'],
            },
        )

    for design in Design.objects.all():
        latest = design.test_suites.order_by('-version').first()
        if latest is None:
            # No Test Suite for this design, so it won't appear on the Test Suites list -
            # skip its thumbnail too, rather than fetching one for every design in Register.
            continue
        if not latest.package_file:
            fetch_test_suite_package(latest)
        if not design.thumbnail:
            fetch_design_thumbnail(design)


def fetch_test_suite_package(test_suite):
    """Fetches and stores one specific TestSuite's package, regardless of whether it's the
    latest version for its design. Used by sync_test_suites() above for the latest version of
    each design, and directly by the manual per-row Fetch action for older versions."""
    if test_suite.package_file:
        return

    content = fetch_test_suite(test_suite.register_id)
    test_suite.package_file.save(f'{test_suite.register_id}.zip', ContentFile(content), save=False)
    test_suite.package_fetched_dt = timezone.now()
    test_suite.save()


def fetch_design_thumbnail(design):
    """Fetches and stores a design's PCB_TOP Design Asset as its thumbnail (Register issue
    #117), if one exists. Leaves design.thumbnail null (the UI falls back to a generic icon)
    when the design has no PCB_TOP asset - not an error, just nothing to show."""
    if design.thumbnail:
        return

    assets = list_design_assets(design_id=design.register_id, asset_type='PCB_TOP')
    if not assets:
        return

    content, content_type = fetch_design_asset(assets[0]['id'])
    extension = mimetypes.guess_extension(content_type) if content_type else None
    design.thumbnail.save(f'{design.register_id}{extension or ".png"}', ContentFile(content), save=True)
