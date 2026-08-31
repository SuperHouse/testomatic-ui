# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 SuperHouse Automation Pty Ltd <info@superhouse.tv>
"""Client for the Register API endpoints this project consumes (Register's API.md): the Test
Suite Package endpoints (staff-only on Register's side), the Design list endpoint, and the
Design Asset endpoints. Requires REGISTER_API_URL / REGISTER_API_KEY to be configured (see
.env.template)."""
import requests
from django.conf import settings

REQUEST_TIMEOUT_SECONDS = 10


class RegisterAPIError(Exception):
    """Raised for any failure talking to Register: unconfigured settings, a network error, or a
    non-2xx response. status_code is None for the first two cases."""

    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _require_config():
    if not settings.REGISTER_API_URL or not settings.REGISTER_API_KEY:
        raise RegisterAPIError('REGISTER_API_URL and REGISTER_API_KEY must both be configured')


def _get(path, params=None):
    _require_config()

    url = f'{settings.REGISTER_API_URL}/api/v1/{path}'
    headers = {'X-API-Key': settings.REGISTER_API_KEY}

    try:
        response = requests.get(url, headers=headers, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        raise RegisterAPIError(f'Could not reach Register: {exc}') from exc

    if response.status_code != 200:
        message = response.text
        try:
            message = response.json().get('message', message)
        except ValueError:
            pass
        raise RegisterAPIError(message, status_code=response.status_code)

    return response


def list_test_suites(design_id=None):
    """Returns every finalised (SAVED) Test Suite Package, or just those for one design when
    design_id is given, as a list of dicts (id, design_id, version, status, created_dt)."""
    params = {'design_id': design_id} if design_id is not None else None
    return _get('test-suites/', params=params).json()


def fetch_test_suite(suite_id):
    """Downloads one Test Suite Package by its id (as returned by list_test_suites), returning
    the raw ZIP archive bytes (containing test-suite-definition.json)."""
    return _get(f'test-suites/{suite_id}/download/').content


def list_designs(client_pk=None):
    """Returns every Design visible to this API key (every design, for a staff key), or just
    those for one client when client_pk is given, as a list of dicts (id, sku, client, name,
    hw_version, description)."""
    params = {'client_pk': client_pk} if client_pk is not None else None
    return _get('designs/', params=params).json()


def list_design_assets(design_id=None, asset_type=None):
    """Returns Design Assets (e.g. a Design's PCB_TOP/PCB_BOTTOM images), optionally filtered by
    design and/or asset type, as a list of dicts (id, design_id, asset_type, name,
    uploaded_dt)."""
    params = {}
    if design_id is not None:
        params['design_id'] = design_id
    if asset_type is not None:
        params['asset_type'] = asset_type
    return _get('design-assets/', params=params or None).json()


def fetch_design_asset(asset_id):
    """Downloads one Design Asset's file by its id (as returned by list_design_assets).
    Returns (raw file bytes, content-type) - unlike fetch_test_suite, the content-type isn't
    fixed (a Design Asset can be a PNG, JPEG, etc.), so the caller needs it to pick a correct
    file extension when saving."""
    response = _get(f'design-assets/{asset_id}/download/')
    return response.content, response.headers.get('Content-Type')
