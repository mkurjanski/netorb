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

## ContainerLab Topology

File: `topology.clab.yml`

Four Arista cEOS 4.30.7M switches wired in a ring. Two Linux end nodes are attached on opposite sides of the ring (node1 at sw1, node2 at sw3).

```
node1 -- sw1 -- sw2
         |        |
        sw4 -- sw3 -- node2
```

### Deploy

```bash
# Import cEOS image first (one-time)
docker import cEOS64-lab-4.30.7M.tar.xz ceos:4.30.7M

# Start topology
sudo containerlab deploy -t topology.clab.yml

# Destroy
sudo containerlab destroy -t topology.clab.yml
```