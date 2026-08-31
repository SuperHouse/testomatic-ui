# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 SuperHouse Automation Pty Ltd <info@superhouse.tv>
from django.contrib.staticfiles.management.commands.runserver import Command as StaticfilesRunserverCommand


class Command(StaticfilesRunserverCommand):
    # Register's dev server uses Django's default of 8000; default to 8001
    # here so both projects' dev servers can run at once on one machine.
    default_port = '8001'
