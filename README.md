# NetOrb

## Overview

NetOrb is a simple network observability tool built with Django. It connects to Arista EOS devices via Nornir, collects operational state on a schedule, and exposes the data through a REST API and a live log viewer.

Collected data sets:

1. Interface table (name + operational status)
2. IPv4 routing table (prefix + next hops)

## Stack

- Python 3.12, Django 5.x, Django REST Framework
- PostgreSQL (local dev via Docker Compose)
- Nornir + nornir-netmiko for device collection
- django-q2 for scheduled task execution (uses PostgreSQL as broker — no Redis required)

## Getting Started

```bash
# Install system dep (one-time, requires sudo)
sudo apt install python3.12-venv

# Create and activate virtualenv
python3 -m venv .venv && source .venv/bin/activate

# Install Python dependencies
pip install -r requirements.txt

# Start PostgreSQL
docker compose up -d

# Apply migrations
python manage.py migrate

# Create a superuser
python manage.py createsuperuser

# Start the development server
python manage.py runserver

# Start the django-q2 worker (separate terminal)
python manage.py qcluster
```

## Configuration

Copy `.env.example` to `.env` and fill in values:

| Variable | Default | Description |
|---|---|---|
| `SECRET_KEY` | — | Django secret key |
| `DEBUG` | `False` | Enable debug mode |
| `DB_PASSWORD` | — | PostgreSQL password |
| `NORNIR_USERNAME` | `admin` | SSH username for devices |
| `NORNIR_PASSWORD` | — | SSH password for devices |

## API Endpoints

All endpoints require authentication (session or token).

| Method | URL | Description |
|---|---|---|
| GET | `/api/interfaces/` | List all interfaces |
| GET | `/api/interfaces/{id}/` | Single interface |
| GET | `/api/routes/` | List all routes with next hops |
| GET | `/api/routes/{id}/` | Single route |

**Query parameters**

- `?device=<hostname>` — filter by device (interfaces and routes)
- `?oper_status=up|down|unknown` — filter interfaces by status
- `?search=<term>` — search by name / hostname / prefix

## Scheduled Polling

Polling schedules are managed via the Django admin (`/admin/`) or the shell.

```python
# Create a schedule that polls all devices every 5 minutes
from django_q.models import Schedule
Schedule.objects.create(
    func="netorb.tasks.poll_all_devices",
    schedule_type=Schedule.MINUTES,
    minutes=5,
    repeats=-1,
    name="Poll all devices",
)
```

`PollingSchedule` records (per device, per task type) are also stored in the database and updated by the worker after each run.

## Live Log Viewer

Navigate to `/logs/` while logged in to watch Nornir collection logs stream in real time. Logs can be filtered by job ID and are retained in the `TaskLog` table.

The SSE stream is also available directly:

```
GET /logs/stream/?last_id=<int>&job_id=<str>
```

## ContainerLab Topology

File: `topology.clab.yml`

Four Arista cEOS 4.30.7M switches wired in a ring. Two Linux end nodes on opposite sides (node1 at sw1, node2 at sw3).

```
node1 -- sw1 -- sw2
         |        |
        sw4 -- sw3 -- node2
```

```bash
# Import cEOS image (one-time)
docker import cEOS64-lab-4.30.7M.tar.xz ceos:4.30.7M

# Deploy
sudo containerlab deploy -t topology.clab.yml

# Destroy
sudo containerlab destroy -t topology.clab.yml
```
