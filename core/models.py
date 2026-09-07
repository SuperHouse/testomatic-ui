# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 SuperHouse Automation Pty Ltd <info@superhouse.tv>
from django.conf import settings
from django.db import models


class OperatorProfile(models.Model):
    """Links a local auth.User to the Register user it was created from (issue #4), so that a
    future test-report feature can attribute a report to a specific Register user, not just a
    local account. full_name/avatar_type are refreshed on every successful Register-backed
    login (see core.auth_backends.RegisterAuthBackend) - they can go stale between logins if the
    device is offline for a while, which is an accepted tradeoff of allowing offline login at
    all (see the local password cache on the User itself)."""
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='operator_profile')
    register_user_id = models.PositiveIntegerField(unique=True)
    full_name = models.CharField(max_length=200, blank=True)
    avatar_type = models.CharField(max_length=20, blank=True)
    synced_dt = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.full_name or self.user.email or self.user.username


class DeviceSettings(models.Model):
    """A singleton (get_solo(), same pattern as Register's erp.AssemblyCostSettings) holding
    this physical Testomatic device's own configuration - as opposed to a Test Suite's own
    config, which comes from Register and is the same regardless of which device runs it.

    Currently just the 4 firmware-upload tool executable paths: testomatic-runner's
    ExecutionContext (see testomatic.steps.base.ExecutionContext in the sibling testomatic-runner
    repo) defaults each UPLOAD_FIRMWARE_* executor's tool to the bare name on $PATH unless
    overridden - these fields are this device's override, blank meaning "use the default on
    $PATH". test_suites.views._run_test_suite() reads this record and passes the 4 paths through
    to TestRunner(...).

    Deliberately does NOT hold anything for the serial port / debug-probe fields
    (UPLOAD_FIRMWARE_AVRDUDE's port, UPLOAD_FIRMWARE_OPENOCD's adapter_serial, etc.) - those stay
    entirely suite-side (set in Register, delivered in the Test Suite Package's own config) for
    now. Whether some of those should instead live here as device-side config is an open
    question, tracked as Register issue #122 - deliberately deferred until the system has been
    exercised end-to-end using the current suite-side-only approach."""
    avrdude_path = models.CharField(
        max_length=500, blank=True,
        help_text="Path to the avrdude executable. Leave blank to use 'avrdude' on $PATH.",
    )
    esptool_path = models.CharField(
        max_length=500, blank=True,
        help_text="Path to the esptool.py executable. Leave blank to use 'esptool.py' on $PATH.",
    )
    openocd_path = models.CharField(
        max_length=500, blank=True,
        help_text="Path to the openocd executable. Leave blank to use 'openocd' on $PATH.",
    )
    stm32cubeprogrammer_path = models.CharField(
        max_length=500, blank=True,
        help_text="Path to the STM32_Programmer_CLI executable. Leave blank to use "
                   "'STM32_Programmer_CLI' on $PATH.",
    )

    class Meta:
        verbose_name = 'Device settings'
        verbose_name_plural = 'Device settings'

    def __str__(self):
        return 'Device settings'

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
