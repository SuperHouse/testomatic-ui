from django.contrib import admin

from .models import DeviceSettings


@admin.register(DeviceSettings)
class DeviceSettingsAdmin(admin.ModelAdmin):
    """Singleton, same convention as Register's erp.AssemblyCostSettingsAdmin - no add once a
    row exists, no delete."""

    def has_add_permission(self, request):
        return not DeviceSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
