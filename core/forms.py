# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 SuperHouse Automation Pty Ltd <info@superhouse.tv>
from django import forms

from .models import DeviceSettings


class DeviceSettingsForm(forms.ModelForm):
    class Meta:
        model = DeviceSettings
        fields = ['avrdude_path', 'openocd_path', 'stm32cubeprogrammer_path']
        widgets = {
            'avrdude_path': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'avrdude'}),
            'openocd_path': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'openocd'}),
            'stm32cubeprogrammer_path': forms.TextInput(
                attrs={'class': 'form-control', 'placeholder': 'STM32_Programmer_CLI'}
            ),
        }
