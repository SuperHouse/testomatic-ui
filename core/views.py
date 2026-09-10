# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 SuperHouse Automation Pty Ltd <info@superhouse.tv>
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import redirect, render

from .forms import DeviceSettingsForm
from .models import DeviceSettings


@login_required
def home(request):
    return render(request, 'core/home.html')


@staff_member_required
def device_settings_edit(request):
    """Edits this device's own DeviceSettings singleton: the firmware-upload tool paths
    test_suites.views._run_test_suite() reads when it constructs a TestRunner, plus the test
    docket printer name (issue #7). See DeviceSettings' own docstring for why this is
    device-side config, separate from a Test Suite's own (Register-defined) config."""
    device_settings = DeviceSettings.get_solo()

    if request.method == 'POST':
        form = DeviceSettingsForm(request.POST, instance=device_settings)
        if form.is_valid():
            form.save()
            messages.success(request, 'Device settings saved.')
            return redirect('device_settings_edit')
    else:
        form = DeviceSettingsForm(instance=device_settings)

    return render(request, 'core/device_settings_edit.html', {'form': form})
