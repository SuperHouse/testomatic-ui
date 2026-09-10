# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 SuperHouse Automation Pty Ltd <info@superhouse.tv>


def extract_serial_number(raw_input: str, url_stem: str) -> str:
    """Extracts a bare DUT serial number from the run page's Serial Number field (issue #8).

    The barcode scanner feeding that field does double duty: scanning a plain barcode types the
    bare serial number, but scanning the QR code (which also serves as a customer-facing link)
    types a full URL instead - `url_stem` (core.models.DeviceSettings.device_details_url_stem)
    plus the serial number. Stripping that same stem back off, when present, recovers the bare
    serial number either way.

    A blank `url_stem`, or `raw_input` not starting with it, means `raw_input` is already the
    bare serial number - returned unchanged (aside from trimming whitespace and any leading '/'
    left over from a stem configured without its trailing slash).
    """
    raw_input = raw_input.strip()
    if url_stem and raw_input.startswith(url_stem):
        return raw_input[len(url_stem):].lstrip('/')
    return raw_input
