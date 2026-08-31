# Testomatic UI

A Django application providing the on-device web UI for [Testomatic](https://github.com/superhouse/testomatic) PCB test jigs. Multiple instances of this app run on different physical Testomatic devices; each instance is a consumer of the [Register](https://github.com/SuperHouse/register) API, not a standalone data store — Register (a separate Django project) is where device/design/test-record data actually lives.

## Relationship to Register

This project is developed **in conjunction with, and coupled to, Register**. It lives alongside Register's own checkout: `../register-macbook` (this machine) / `../register` (other checkouts) relative to this project's own folder. When working on a feature here that touches the Register API:

- Check Register's `CLAUDE.md` and `API.md` for the current shape of the endpoints, auth (`X-API-Key` header, keys are per-`authuser.User`), and access-control rules before assuming a shape.
- A change that needs a new or modified Register API endpoint means editing Register's code too (`pyproj/device/api.py`, `pyproj/testing/api.py`, `pyproj/api/`) — this project cannot add server-side endpoints of its own for Register's data.
- Prefer reusing Register's existing endpoints and schemas over inventing a parallel representation here.

This project has **its own** Django project (own `manage.py`, own `conf/`, own database), separate from Register's — it does not import Register's Python code or share its database. The coupling is at the API boundary and in shared visual identity (see Theme below), not at the code level.

## Project Layout

```
testomatic-ui/
├── conf/            # Django project settings, URLs (mirrors Register's "conf" app naming)
├── core/            # Dashboard view, base templates/theme, and register_client.py (see below)
│   ├── templates/core/
│   ├── templates/registration/   # login.html
│   ├── register_client.py        # Register API client
│   └── views.py / urls.py
├── test_suites/     # Local Design/Test Suite cache and the Test Suites page (see below)
├── static/          # CSS/JS/img shared visual theme with Register (see Theme below)
├── media/           # Downloaded Test Suite Package ZIPs (MEDIA_ROOT, gitignored)
├── manage.py
└── requirements.txt
```

## Running the Project

```bash
source venv/bin/activate
python manage.py runserver
```

Defaults to port 8001 (overridden in `core/management/commands/runserver.py`, not Django's usual 8000), so this can run alongside Register's dev server on the same machine.

- UI: http://127.0.0.1:8001/
- Admin: http://127.0.0.1:8001/admin/

## Theme

The UI intentionally matches Register's look: CoreUI 4.3.2 + CoreUI Icons + Bootstrap Icons (same CDN versions), the same sidebar/header/footer layout pattern (`base.html` → `base-with-sidebar.html` → `partial-sidebar.html`/`partial-topnav.html`/`partial-footer.html`), and `static/css/style.css` / `static/js/script.js` copied from Register's own copies. If Register's shared theme files change in a way that should apply here too (e.g. a new CoreUI version, a layout fix), port the change across by hand — the two projects don't share a file on disk, so there's no automatic sync.

The sidebar matches Register's structure exactly: the SuperHouse logo (`static/img/superhouse.png`, linking to superhouse.tv) at the top in `.sidebar-brand`, and a `.sidebar-footer` at the bottom (below the nav/logout, pushed down by `.sidebar-nav`'s `flex: 1`) with the Testomatic logo (`static/img/testomatic-logo-wide-transparent.png`, linking to testomatic.io) above a centered, muted version string.

## Data Model / Auth

`core` has `OperatorProfile` (see Operator Login below). `test_suites` has `Design` and `TestSuite` — see Test Suites below. Login is Django's standard session-based `django.contrib.auth.urls`, but authentication itself is handled by `core.auth_backends.RegisterAuthBackend` (see below), not a plain local password check.

## Operator Login

Operators log in with their **Register email and password**, not a locally-created account (issue #4) — though a `createsuperuser` account still works too (see below). Backed by a new Register endpoint, `POST /api/v1/auth/verify/` — see Register's own `CLAUDE.md`/`API.md` for that endpoint's contract.

- `AUTHENTICATION_BACKENDS` (`conf/settings.py`) lists `core.auth_backends.RegisterAuthBackend` before Django's `ModelBackend`. Django tries backends in order and uses the first that returns a user.
- `RegisterAuthBackend.authenticate()`: calls `core.register_client.verify_operator(email, password)` — a `POST` to Register, authenticated as *this device* (`X-API-Key`), not as the operator. Three outcomes:
  1. **Register confirms the credentials** — `get_or_create`s a local `auth.User` (`username` = the email), sets `is_staff = True` (Register already refused a non-staff user with a `403`, so this is safe), sets `first_name` to the Register `full_name` (so the existing `{{ user.get_full_name }}` in `partial-topnav.html` picks it up with no template change), and — the key part — calls `user.set_password(password)` to refresh the **locally cached, salted hash** of the current password. Also `update_or_create`s an `OperatorProfile` (`register_user_id`, `full_name`, `avatar_type`) linking the local account back to Register's own user PK, for a future test-report feature to attribute reports by.
  2. **Register explicitly rejects the credentials** (`401` wrong password, `403` not staff) — returns `None` immediately. A stale local cache never overrides an explicit rejection.
  3. **Register is unreachable** (`RegisterAPIError.status_code is None` — a network/timeout failure, distinct from an HTTP error response) — falls back to `user.check_password()` against whatever hash was cached the last time this operator successfully logged in through path 1. This is deliberate: Testomatic devices are sometimes used somewhere with intermittent connectivity, and login needs to keep working there. The known tradeoff: if an operator's Register access is revoked while a device is offline, the cached credentials still work on that device until it reconnects and a login re-syncs them.
- `ModelBackend` stays in the list too, so a local `createsuperuser` account (see README) keeps working independently of Register — useful for first-time device bring-up before `REGISTER_API_URL`/`REGISTER_API_KEY` are configured, and as a break-glass admin path.
- The login template (`core/templates/registration/login.html`) labels the identifier field "Email" rather than Django's default "Username" — the field's still POSTed as `username` (Django's `AuthenticationForm` isn't renamed), it's just relabelled.
- `core/avatar.py` (`get_initials`/`get_avatar_color`/`get_gravatar_url`) is a port of Register's `device/templatetags/avatar_tags.py`, so the topnav looks the same: a Gravatar image if the cached `OperatorProfile.avatar_type` is `gravatar`, otherwise an email-derived colour with initials on top. `core/context_processors.py:operator_avatar` (registered in `TEMPLATES`) supplies `operator_display_name`/`operator_avatar_url`/`operator_initials`/`operator_avatar_color` to every template — `partial-topnav.html` renders **name then avatar**, matching Register's own order (deliberately the opposite of what you'd naively pick). Falls back to Django's own `get_full_name()`/`get_username()` for a local-only account with no `OperatorProfile`.

## Register API Client

`core/register_client.py` wraps the Register endpoints this project consumes (see Register's `API.md`). All requests send `X-API-Key: REGISTER_API_KEY` and raise `RegisterAPIError` (with `.status_code`/`.message`) on any failure, including unconfigured settings.

- `list_designs(client_pk=None)` — `GET /api/v1/designs/`. A staff key sees every design.
- `list_test_suites(design_id=None)` — `GET /api/v1/test-suites/`. **Staff-only** on Register's side — a non-staff key gets a `403`. Only ever returns finalised (`SAVED`) suites, never `DRAFT`.
- `fetch_test_suite(suite_id)` — `GET /api/v1/test-suites/{id}/download/`, returns the raw ZIP bytes. Also staff-only.
- `list_design_assets(design_id=None, asset_type=None)` / `fetch_design_asset(asset_id)` — `GET /api/v1/design-assets/` / `.../download/` (issue #117). The latter returns `(bytes, content_type)`, not just bytes — a Design Asset isn't always the same file type.
- `verify_operator(email, password)` — `POST /api/v1/auth/verify/` (issue #4), authenticated as the device, not the operator. See Operator Login below for how `RegisterAPIError.status_code` (`None` vs. a real HTTP status) drives the online/offline login split.

Register also IP-allowlists API callers (`API_ALLOW_IPV4_SUBNET`) — a device's key needs both staff access and an allowlisted IP to reach the Test Suite/Design Asset endpoints.

## Test Suites

The `test_suites` app (nav: "Test Suites", `/test-suites/`) caches Register's Design/Test Suite data locally and downloads Test Suite Packages, so a device isn't dependent on Register being reachable to run a suite it already has.

- `Design` — local cache of a Register Design (`register_id`, `sku`, `name`, `hw_version`, `description`), plus `thumbnail` (a `FileField`, null until fetched). `sync.py:fetch_design_thumbnail()` fetches a design's `PCB_TOP` Design Asset over Register's issue #117 API (`core.register_client.list_design_assets()`/`fetch_design_asset()`) the first time it's missing, saved under `MEDIA_ROOT/design_thumbnails/<register_id>.<ext>` (extension guessed from the response's `Content-Type`, since a Design Asset isn't always a PNG). A design with no `PCB_TOP` asset stays `thumbnail=None` — not an error — and the list page falls back to a generic `cil-memory` icon.
- `TestSuite` — local cache of one Register Test Suite Package (`register_id`, `design` FK, `version`, `status`, `register_created_dt`), plus `package_file` (a `FileField` — the downloaded ZIP lives on disk under `MEDIA_ROOT/test_suite_packages/<sku>/<register_id>.zip`, not as a DB blob) and `package_fetched_dt` (null until fetched).
- `test_suites/sync.py:sync_test_suites()` — upserts `Design`/`TestSuite` metadata from Register (insert-only for `TestSuite`; Register never mutates a finalised suite), then fetches the package for the **latest version only** of each design's Test Suite. Older versions stay listed without a package unless fetched manually. Never deletes rows or files.
- Reached three ways: the `sync_test_suites` management command (cron-able), the "Update Now" button on `/test-suites/`, and per-row "Fetch" buttons for older versions (`fetch_test_suite_package()`) — all three call the same `sync.py` functions, one code path. `fetch_design_thumbnail()` only runs from inside `sync_test_suites()` itself (for any design that has a `TestSuite`), not as a separate manual action — there's no "Fetch" button for a missing thumbnail.
- The list page only shows designs that actually have a `TestSuite` (`Design.objects.filter(test_suites__isnull=False)`), not every design in Register's catalog.
- Tests that call the real `sync_test_suites()`/`fetch_test_suite_package()` (not fully mocked) must subclass `test_suites.tests.MediaIsolatedTestCase`, not `TestCase` directly — `FileField` writes aren't rolled back by Django's test transaction, so without it they'd leak files into the real `MEDIA_ROOT`.
- **`test_suites/test_suite_package.py`** (issue #3) — parses a fetched `TestSuite.package_file`'s ZIP (`test-suite-definition.json`) into `StepDisplay`/`CheckDisplay` objects for the read-only `/test-suites/<pk>/` detail page (`test_suite_detail` view, 404s if not yet fetched — only downloaded versions are clickable from the list page). `STEP_TYPE_LABELS`/`STEP_TYPE_COLORS`/`_config_summary()` are an **exact port** of Register's `testing.models.TestStep` (`STEP_TYPE_CHOICES`/`STEP_TYPE_COLORS`/`get_config_summary()`) — keep the two in sync by hand if Register adds/changes a step type; an unrecognised `step_type` falls back to a generic grey badge rather than crashing. `StepDisplay`/`CheckDisplay` expose the same `get_color()`/`get_step_type_display()`/`get_config_summary()` method names Register's own template calls, so `test_suites/templates/test_suites/detail.html` is a close structural copy of Register's read-only `testing/test_suite_version_detail.html` — same bordered/colored card-per-step layout, deliberately with no drag handle, delete button, or `onclick` navigation (the whole point of the page, per issue #3, is that nothing on it is editable or clickable).

## Configuration

Environment variables load from `.env` (see `.env.template`). Notable ones:

| Variable | Description |
|---|---|
| `SECRET_KEY` | Django secret key |
| `DEBUG` | `True`/`False` |
| `ALLOWED_HOSTS` | Comma-separated hostnames |
| `REGISTER_API_URL` | Base URL of the Register instance this device talks to |
| `REGISTER_API_KEY` | API key (see Register's `authuser.User.regenerate_api_key`) this device authenticates to Register with |

## Status

Still early: a themed shell, the Register API client, the Test Suites list/fetch/detail feature (issues #1, #2, #3), Design thumbnails on that list (Register issue #117), and Register-backed operator login with an offline fallback (issue #4) exist. Test execution and firmware programming don't exist yet. The GitHub repo is [github.com/SuperHouse/testomatic-ui](https://github.com/SuperHouse/testomatic-ui).
