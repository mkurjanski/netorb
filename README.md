# Netorb

## Getting Started

### Install deps (needs python3.12-venv — run once with sudo)
sudo apt install python3.12-venv
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

### Start Postgres
docker compose up -d

### Run migrations
python manage.py migrate

### Start server
python manage.py runserver