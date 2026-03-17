# NetOrb

## Overview

NetOrb is a simple network observability tool built with Django. It connects to Arista EOS devices via Nornir and SSH, collects operational state on demand, and presents it through a web UI with historical tracking and diff views.

Collected data sets:

1. Interfaces (name + operational status + IP)
2. IPv4 routing table (prefix + next hops)
3. BGP sessions (peer, ASN, state, prefix counts, up/down time)
4. ARP table (IP + MAC + interface)
5. LLDP neighbors (local port → remote device/port)

## Stack

- Python 3.12, Django 5.x, Django REST Framework
- PostgreSQL (local dev via Docker Compose)
- Nornir + nornir-netmiko for device collection
- django-q2 for background task execution (uses PostgreSQL as broker — no Redis required)
- pghistory for change tracking

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

## Views

| URL | Description |
|---|---|
| `/latest/` | Current snapshot of all data sets across all devices |
| `/interfaces/` | Interface list with filters |
| `/routes/` | IPv4 route table with filters |
| `/bgp-sessions/` | BGP session list with filters |
| `/arp/` | ARP table with filters |
| `/history/` | pghistory event log per data set |
| `/diff/` | Side-by-side diff between two point-in-time snapshots |
| `/topology/` | LLDP-derived network topology |
| `/path-tracer/` | Trace a path between two devices |
| `/tasks/` | Trigger on-demand collection per data type |
| `/poll-results/` | Collection run history with duration and success |
| `/logs/` | Live Nornir collection log viewer (SSE) |

## API Endpoints

All endpoints require authentication (session or token).

| Method | URL | Description |
|---|---|---|
| GET | `/api/interfaces/` | List all interfaces |
| GET | `/api/interfaces/{id}/` | Single interface |
| GET | `/api/routes/` | List all routes with next hops |
| GET | `/api/routes/{id}/` | Single route |

**Query parameters**

- `?device=<hostname>` — filter by device
- `?oper_status=up|down|unknown` — filter interfaces by status
- `?search=<term>` — search by name / hostname / prefix

## Poll Result Tracking

Every collection run records a `PollResult` entry per check type, capturing:

- **Check type** — interfaces, routes, BGP sessions, ARP, or LLDP
- **Started at** — wall-clock timestamp when the check began
- **Duration (ms)** — how long the check took end-to-end
- **Success** — whether the check completed without errors
- **Job ID** — links back to the `TaskLog` entries for that run

Results are viewable at `/poll-results/` with filters by check type. Rows are colour-coded by duration (yellow ≥ 5 s, red ≥ 10 s).

## Live Log Viewer

Navigate to `/logs/` to watch Nornir collection logs stream in real time. Logs can be filtered by job ID and are retained in the `TaskLog` table.

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

| Hostname | IP Address | Kind |
|---|---|---|
| sw1 | 172.20.20.2 | cEOS |
| sw2 | 172.20.20.3 | cEOS |
| sw3 | 172.20.20.4 | cEOS |
| sw4 | 172.20.20.5 | cEOS |
| node1 | 172.20.20.4 | Linux |
| node2 | 172.20.20.5 | Linux |

```bash
# Import cEOS image (one-time)
docker import cEOS64-lab-4.30.7M.tar.xz ceos:4.30.7M

# Deploy
sudo containerlab deploy -t topology.clab.yml

# Destroy
sudo containerlab destroy -t topology.clab.yml
```
