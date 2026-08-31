# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 SuperHouse Automation Pty Ltd <info@superhouse.tv>
"""Authenticates an operator against Register (issue #4), caching a locally-hashed password so
the device keeps working if Register becomes unreachable - Testomatic testers are sometimes used
somewhere with intermittent connectivity. Register is authoritative whenever it's reachable: an
explicit rejection (wrong password, or not staff) is never overridden by a locally cached
credential. Only a genuine failure to reach Register at all - not a rejection - falls back to
the local check (RegisterAPIError.status_code is None for that case; see register_client)."""
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend

from .models import OperatorProfile
from .register_client import RegisterAPIError, verify_operator

User = get_user_model()


class RegisterAuthBackend(ModelBackend):
    """get_user() and permission checks are inherited from ModelBackend unchanged - only
    authenticate() differs, since credentials are checked against Register first rather than
    only ever against a local password hash."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        if not username or not password:
            return None

        try:
            profile_data = verify_operator(username, password)
        except RegisterAPIError as exc:
            if exc.status_code is None:
                return self._authenticate_locally(username, password)
            return None  # Register explicitly rejected these credentials - no local fallback.

        return self._sync_local_user(username, profile_data, password)

    def _sync_local_user(self, email, profile_data, password):
        """Creates or updates the local account to match Register - including refreshing the
        cached password hash, so the local fallback below stays correct after a password change
        in Register, per issue #4's "update opportunistically on the next successful auth"."""
        user, _ = User.objects.get_or_create(username=email)
        user.email = email
        # first_name (last_name left blank) so the existing {{ user.get_full_name }} display in
        # partial-topnav.html picks this up with no template change needed.
        user.first_name = profile_data.get('full_name') or ''
        user.is_staff = True  # verify_operator() already refused a non-staff user
        user.set_password(password)
        user.save()

        OperatorProfile.objects.update_or_create(
            user=user,
            defaults={
                'register_user_id': profile_data['id'],
                'full_name': profile_data.get('full_name') or '',
                'avatar_type': profile_data.get('avatar_type') or '',
            },
        )
        return user

    def _authenticate_locally(self, email, password):
        try:
            user = User.objects.get(username=email)
        except User.DoesNotExist:
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
