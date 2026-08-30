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
├── core/            # Main app: dashboard view, base templates/theme
│   ├── templates/core/
│   ├── templates/registration/   # login.html
│   └── views.py / urls.py
├── static/          # CSS/JS/img shared visual theme with Register (see Theme below)
├── manage.py
└── requirements.txt
```

## Running the Project

```bash
source venv/bin/activate
python manage.py runserver
```

- UI: http://127.0.0.1:8000/
- Admin: http://127.0.0.1:8000/admin/

## Theme

The UI intentionally matches Register's look: CoreUI 4.3.2 + CoreUI Icons + Bootstrap Icons (same CDN versions), the same sidebar/header/footer layout pattern (`base.html` → `base-with-sidebar.html` → `partial-sidebar.html`/`partial-topnav.html`/`partial-footer.html`), and `static/css/style.css` / `static/js/script.js` copied from Register's own copies. If Register's shared theme files change in a way that should apply here too (e.g. a new CoreUI version, a layout fix), port the change across by hand — the two projects don't share a file on disk, so there's no automatic sync.

The sidebar brand uses the Testomatic logo (`static/img/testomatic-logo-wide-transparent.png`) rather than Register's SuperHouse logo, since this app *is* the Testomatic-branded product surface, unlike Register which links out to Testomatic as a related project.

## Data Model / Auth

No custom models yet beyond Django's defaults — this is a fresh skeleton. Auth currently uses Django's standard `django.contrib.auth` `User` model and session-based login (`django.contrib.auth.urls`), which is separate from Register's user accounts. Whether/how a Testomatic device's local login should relate to a Register user (e.g. via the API key a device holds) is an open question for when real features are added.

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

This is an early skeleton (Django admin + a themed shell + a placeholder dashboard). No Testomatic-specific features (test execution, firmware programming, Register sync) exist yet — those will be designed and added once a GitHub repo is set up for this project.
