# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 SuperHouse Automation Pty Ltd <info@superhouse.tv>
from django import forms

from .models import DeviceSettings, timezone_choices


class DeviceSettingsForm(forms.ModelForm):
    # Declared explicitly (rather than left to ModelForm's usual model-field introspection) so
    # the machine-specific zoneinfo choice list stays out of DeviceSettings.timezone's own
    # `choices=` and therefore out of migration state - see timezone_choices()'s docstring.
    timezone = forms.ChoiceField(choices=timezone_choices, widget=forms.Select(attrs={'class': 'form-select'}))

    class Meta:
        model = DeviceSettings
        fields = [
            'avrdude_path', 'openocd_path', 'stm32cubeprogrammer_path', 'printer_name',
            'device_details_url_stem', 'timezone',
        ]
        widgets = {
            'avrdude_path': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'avrdude'}),
            'openocd_path': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'openocd'}),
            'stm32cubeprogrammer_path': forms.TextInput(
                attrs={'class': 'form-control', 'placeholder': 'STM32_Programmer_CLI'}
            ),
            'printer_name': forms.TextInput(
                attrs={'class': 'form-control', 'placeholder': 'Printer_POS-80'}
            ),
            'device_details_url_stem': forms.TextInput(
                attrs={'class': 'form-control', 'placeholder': 'https://d.superlab.au/'}
            ),
        }
