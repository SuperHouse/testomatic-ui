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
