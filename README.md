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

### Create a user account

```bash
python manage.py createsuperuser
```

Follow the prompts to create an account — same convention as Register. Log in with it at `/accounts/login/` to reach the dashboard; being a superuser also gives you access to `/admin/`. Any additional accounts can be created the same way, or via `/admin/` once one account exists.

## Running

```bash
source venv/bin/activate
python manage.py runserver
```

Defaults to port 8001 (not Django's usual 8000), so this can run alongside Register's dev server on the same machine.

- UI: http://127.0.0.1:8001/
- Admin: http://127.0.0.1:8001/admin/
