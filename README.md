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
