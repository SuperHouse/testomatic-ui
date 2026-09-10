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

    Three unrelated groups of fields so far, shown as separate cards on /settings/ (see
    device_settings_edit.html):

    - The 3 firmware-upload tool executable paths for the tools with no PyPI distribution:
      testomatic-runner's ExecutionContext (see testomatic.steps.base.ExecutionContext in the
      sibling testomatic-runner repo) defaults each UPLOAD_FIRMWARE_* executor's tool to the bare
      name on $PATH unless overridden - these fields are this device's override, blank meaning
      "use the default on $PATH". test_suites.views._run_test_suite() reads this record and
      passes the 3 paths through to TestRunner(...). There is deliberately no esptool_path
      field: esptool is a pure-Python PyPI package, so testomatic-runner's "pi" extra installs it
      (and its esptool.py console script) directly onto this device's $PATH, unlike
      avrdude/openocd/STM32CubeProgrammer, which have no PyPI distribution and still need a
      system-level install plus an optional path override here.
    - `printer_name` (issue #7): the CUPS print queue this device prints a test docket to, e.g.
      'Printer_POS-80', for a `lp -d <printer_name> ...` call once the docket-printing feature
      itself (issue #6) exists. Not consumed by anything yet - this is just the config option,
      added ahead of the printing logic since #7 was split off #6 as a self-contained sub-issue.
    - `device_details_url_stem` (issue #8): the base URL this device prepends to a DUT's serial
      number to build the customer-facing "device details" link printed (as text and a QR code)
      on the Test Docket, e.g. 'https://d.superlab.au/' + '12345'. Also used the other direction:
      test_suites.serial_number.extract_serial_number() strips this same stem back off when the
      serial-number field on the run page is populated by scanning the QR code rather than a
      plain barcode (see that function's own docstring). Deliberately just one fallback value for
      now, not per-customer/per-design - some customers want a vanity redirect URL instead, which
      is real but explicitly deferred; whatever per-customer/per-design override scheme gets
      built later would still need this field as its fallback, so it isn't wasted work.

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
    openocd_path = models.CharField(
        max_length=500, blank=True,
        help_text="Path to the openocd executable. Leave blank to use 'openocd' on $PATH.",
    )
    stm32cubeprogrammer_path = models.CharField(
        max_length=500, blank=True,
        help_text="Path to the STM32_Programmer_CLI executable. Leave blank to use "
                   "'STM32_Programmer_CLI' on $PATH.",
    )
    printer_name = models.CharField(
        max_length=200, blank=True,
        help_text="CUPS print queue name for the test docket printer, e.g. 'Printer_POS-80' "
                   "(used as 'lp -d <printer_name> ...'). Leave blank if no printer is "
                   "configured on this device.",
    )
    device_details_url_stem = models.CharField(
        max_length=500, blank=True,
        help_text="Base URL this device prepends to a DUT's serial number to build the device "
                   "details link/QR code on the Test Docket, e.g. 'https://d.superlab.au/'.",
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
