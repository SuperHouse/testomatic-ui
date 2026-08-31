# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 SuperHouse Automation Pty Ltd <info@superhouse.tv>
"""Avatar rendering for the logged-in operator in the topnav - a port of Register's
device/templatetags/avatar_tags.py (get_user_initials/get_avatar_color/get_gravatar_url), so the
two look the same: a Gravatar image if the cached OperatorProfile.avatar_type says so, otherwise
a colour derived from the user's email with their initials on top."""
import hashlib


def get_initials(full_name, email):
    if full_name:
        parts = full_name.strip().split()
        if len(parts) >= 2:
            return (parts[0][0] + parts[-1][0]).upper()
        if len(parts) == 1:
            return parts[0][0].upper()
    if email:
        return email[0].upper()
    return '?'


def get_avatar_color(email):
    if not email:
        return '#6c757d'

    hash_hex = hashlib.md5(email.encode()).hexdigest()
    r, g, b = int(hash_hex[0:2], 16), int(hash_hex[2:4], 16), int(hash_hex[4:6], 16)
    # Darken an overly light color, so white initials text stays readable on top of it.
    avg = (r + g + b) / 3
    if avg > 200:
        r, g, b = int(r * 0.7), int(g * 0.7), int(b * 0.7)
    return f'#{r:02x}{g:02x}{b:02x}'


def get_gravatar_url(email, size=40):
    if not email:
        return None
    email_hash = hashlib.md5(email.lower().strip().encode()).hexdigest()
    return f'https://www.gravatar.com/avatar/{email_hash}?s={size}&d=identicon'
