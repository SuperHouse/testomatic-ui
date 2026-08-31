# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 SuperHouse Automation Pty Ltd <info@superhouse.tv>
from django.db import models


class Design(models.Model):
    """Local cache of a Register Design (device/models.py Design), refreshed via
    core.register_client.list_designs(). No thumbnail field yet - Register doesn't expose one
    over the API (see issue #117 on the Register repo); the UI shows a generic icon instead."""
    register_id = models.PositiveIntegerField(unique=True)
    sku = models.CharField(max_length=255)
    name = models.CharField(max_length=255)
    hw_version = models.CharField(max_length=50, blank=True)
    description = models.TextField(blank=True)
    synced_dt = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['sku', 'name']

    def __str__(self):
        return f'{self.sku} {self.name}'.strip()


def test_suite_package_upload_path(instance, filename):
    return f'test_suite_packages/{instance.design.sku}/{instance.register_id}.zip'


class TestSuite(models.Model):
    """Local cache of one Register Test Suite Package (testing/models.py TestSuite), keyed on
    Register's own primary key. Register never mutates a finalised (SAVED) suite, so syncing is
    insert-only - see test_suites.sync. package_file is null until the ZIP has been downloaded;
    sync.py only auto-fetches the latest version per design, so an older version's package_file
    stays null unless fetched manually."""
    SAVED = 'SAVED'
    DRAFT = 'DRAFT'
    STATUS_CHOICES = [(SAVED, 'Saved'), (DRAFT, 'Draft')]

    register_id = models.PositiveIntegerField(unique=True)
    design = models.ForeignKey(Design, related_name='test_suites', on_delete=models.CASCADE)
    version = models.PositiveIntegerField()
    status = models.CharField(max_length=10, choices=STATUS_CHOICES)
    register_created_dt = models.DateTimeField()
    package_file = models.FileField(upload_to=test_suite_package_upload_path, null=True, blank=True)
    package_fetched_dt = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['design', '-version']

    def __str__(self):
        return f'{self.design} v{self.version}'
