# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 SuperHouse Automation Pty Ltd <info@superhouse.tv>
from pathlib import Path

from django.db import models


def design_thumbnail_upload_path(instance, filename):
    return f'design_thumbnails/{instance.register_id}{Path(filename).suffix}'


class Design(models.Model):
    """Local cache of a Register Design (device/models.py Design), refreshed via
    core.register_client.list_designs(). thumbnail is null until fetch_design_thumbnail() (see
    test_suites.sync) finds a PCB_TOP Design Asset for it over Register's issue #117 API - a
    design with no PCB_TOP asset (or fetched before #117 existed) stays null, and the UI falls
    back to a generic icon."""
    register_id = models.PositiveIntegerField(unique=True)
    sku = models.CharField(max_length=255)
    name = models.CharField(max_length=255)
    client_name = models.CharField(max_length=255, blank=True)
    hw_version = models.CharField(max_length=50, blank=True)
    description = models.TextField(blank=True)
    thumbnail = models.FileField(upload_to=design_thumbnail_upload_path, null=True, blank=True)
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

    def is_current_version(self):
        """Whether this is the highest version number synced for its design - compared against
        every synced version, not just fetched ones, since a newer version can exist in our
        metadata before its package has been downloaded."""
        return self.version == self.design.test_suites.aggregate(models.Max('version'))['version__max']
