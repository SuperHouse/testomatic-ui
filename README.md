# Testomatic UI

A Django web application that runs on individual [Testomatic](https://github.com/superhouse/testomatic) PCB test jig devices, providing the on-device UI for testing and programming boards. It's a consumer of the [Register](https://github.com/SuperHouse/register) API.

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.template .env   # then edit .env
python manage.py migrate
python manage.py createsuperuser
```

## Running

```bash
source venv/bin/activate
python manage.py runserver
```

- UI: http://127.0.0.1:8000/
- Admin: http://127.0.0.1:8000/admin/
