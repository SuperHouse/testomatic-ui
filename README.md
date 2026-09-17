# Testomatic UI

A Django web application that runs on individual [Testomatic](https://github.com/superhouse/testomatic) PCB test jig devices, providing the on-device UI for testing and programming boards. It's a consumer of the [Register](https://github.com/SuperHouse/register) API.

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.template .env   # then edit .env
python manage.py migrate
```

### Logging in

Normally, log in at `/accounts/login/` with a **Register email and password** — any staff user in the Register instance configured via `REGISTER_API_URL`/`REGISTER_API_KEY` (see Configuration below) can log in this way, no separate account needs creating here first. A local copy of the account is created/updated on each successful login (including a cached password hash, so login keeps working if Register becomes briefly unreachable).

For local dev, or before `REGISTER_API_URL`/`REGISTER_API_KEY` are configured, a local-only account still works too:

```bash
python manage.py createsuperuser
```

Follow the prompts to create an account — same convention as Register. Log in with it at `/accounts/login/`; being a superuser also gives you access to `/admin/`.

## Running

```bash
source venv/bin/activate
python manage.py runserver
```

Defaults to port 8001 (not Django's usual 8000), so this can run alongside Register's dev server on the same machine.

- UI: http://127.0.0.1:8001/
- Admin: http://127.0.0.1:8001/admin/

## Printer Setup (CUPS)

The Test Docket (`test_suites/docket.py`, see `CLAUDE.md`) prints via `lp -d <printer_name>` to a
CUPS queue configured on the device (`DeviceSettings.printer_name`, e.g. `Printer_POS-80` for an
80mm thermal receipt printer). One CUPS default needs changing on a fresh install, or long dockets
will be truncated to a fixed page length instead of printing as one continuous receipt:

1. Open the CUPS web admin UI: `https://127.0.0.1:631`
2. **Printers** → select the queue (e.g. `Printer_POS-80`) → **Administration** → **Set Default
   Options** → **General** tab
3. **Media Size** defaults to `80(72mm) x 210mm` — this is a *fixed page length* (210mm ≈ 8.27in),
   confirmed against a printed CUPS test page whose reported printable area was `0.00 x 0.00 to
   2.83 x 8.26 inches`. A docket taller than this gets cut off rather than printing in full.
   Change it to `80(72mm) x 3276mm` (the driver's maximum), or a custom size, so any
   practically-sized docket fits on one continuous piece. `2.83in` printable width at 203dpi is
   ≈574.5px, matching `docket.py`'s `DOCKET_IMAGE_WIDTH = 576` closely enough that the image width
   doesn't need adjusting.
4. **Cut Options** (same **Set Default Options** page) generally do the right thing by default, but
   may need adjusting per installation depending on the specific printer/cutter hardware.

This is a per-device CUPS configuration step, not something `testomatic-ui`'s code can set — redo
it on every new device's printer queue during bring-up.

### Previewing a docket on a dev Mac

`docket.py` renders the Test Docket with DejaVu Sans Mono, which Raspberry Pi OS/Debian ships as
part of `fonts-dejavu-core`. A Mac has no such font by default, and Pillow silently falls back to
its own tiny built-in bitmap font instead — which has different character-width metrics, so a
preview rendered without the real font can't be trusted (text that fits/wraps/truncates on a real
device may not in the preview, or vice versa). Fix: `brew install --cask font-dejavu`, which
installs the identical `DejaVuSansMono.ttf`/`DejaVuSansMono-Bold.ttf` filenames into
`~/Library/Fonts/` — `docket.py` already checks that path as a fallback after the Pi's own.
