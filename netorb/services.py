"""
Business logic for collecting network state from devices via Nornir.

Collection flow:
  collect_device(device, task_type)
    └─ _make_nornir()      → single-host Nornir instance
    ├─ task_interfaces()   → SSH → 'show interfaces | json' → parse → upsert Interface rows
    └─ task_routes()       → SSH → 'show ip route | json'  → parse → upsert IPv4Route + NextHop rows
"""

import json
import logging
import time
from contextlib import contextmanager
from datetime import datetime, timezone as dt_timezone

from django.conf import settings
from django.utils import timezone
from nornir.core import Nornir
from nornir.core.configuration import Config
from nornir.core.inventory import Defaults, Groups, Host, Hosts, Inventory
from nornir.core.plugins.connections import ConnectionPluginRegister
from nornir.plugins.runners import SerialRunner
from nornir_netmiko.connections.netmiko import Netmiko as NetmikoPlugin
from nornir_netmiko.tasks import netmiko_send_command

ConnectionPluginRegister.register("netmiko", NetmikoPlugin)

from .log_handler import DBLogHandler
from .models import ArpEntry, BgpSession, Device, Interface, IPv4Route, NextHop, PollResult

logger = logging.getLogger(__name__)


@contextmanager
def _db_logging(job_id: str, device: Device):
    """Attach a DBLogHandler for the duration of a collection run."""
    handler = DBLogHandler(job_id=job_id, device=device)
    handler.setFormatter(logging.Formatter("%(name)s - %(message)s"))
    logging.getLogger("netorb").addHandler(handler)
    logging.getLogger("nornir").addHandler(handler)
    try:
        yield
    finally:
        logging.getLogger("netorb").removeHandler(handler)
        logging.getLogger("nornir").removeHandler(handler)


def _make_nornir(device: Device) -> Nornir:
    """Build a single-host Nornir instance from a Device ORM object."""
    host = Host(
        name=device.hostname,
        hostname=device.hostname,
        username=settings.NORNIR_USERNAME,
        password=settings.NORNIR_PASSWORD,
        platform="arista_eos",
        groups=Groups(),
        defaults=Defaults(),
    )
    inventory = Inventory(hosts=Hosts({device.hostname: host}), groups=Groups(), defaults=Defaults())
    return Nornir(inventory=inventory, runner=SerialRunner(), config=Config(logging={"enabled": False}))


# ---------------------------------------------------------------------------
# Parent Nornir tasks — each handles collection + DB sync for one data type
# ---------------------------------------------------------------------------

def task_interfaces(task, device: Device) -> None:
    """Nornir parent task: collect interface state and sync to DB."""
    result = task.run(
        task=netmiko_send_command,
        command_string="show interfaces | json",
        read_timeout=60,
    )
    raw = json.loads(result[0].result)
    for name, attrs in raw.get("interfaces", {}).items():
        status = (
            Interface.OperStatus.UP
            if attrs.get("lineProtocolStatus") == "up"
            else Interface.OperStatus.DOWN
        )
        Interface.objects.update_or_create(
            device=device,
            name=name,
            defaults={"oper_status": status},
        )


def task_routes(task, device: Device) -> None:
    """Nornir parent task: collect IPv4 routes and sync to DB."""
    result = task.run(
        task=netmiko_send_command,
        command_string="show ip route | json",
    )
    route_data = json.loads(result[0].result)
    routes = route_data.get("vrfs", {}).get("default", {}).get("routes", {})
    for prefix, info in routes.items():
        route, _ = IPv4Route.objects.update_or_create(device=device, prefix=prefix)
        # Replace next hops on every sync to reflect current state.
        route.next_hops.all().delete()
        for via in info.get("vias", []):
            nh = via.get("nexthopAddr")
            # EOS uses the string "None" for directly connected routes.
            if nh and nh != "None":
                NextHop.objects.create(route=route, ip_address=nh)


def task_bgp_sessions(task, device: Device) -> None:
    """Nornir parent task: collect BGP session state and sync to DB."""
    result = task.run(
        task=netmiko_send_command,
        command_string="show ip bgp summary | json",
    )
    data = json.loads(result[0].result)
    for vrf_name, vrf_data in data.get("vrfs", {}).items():
        for peer_ip, peer in vrf_data.get("peers", {}).items():
            updown_time = peer.get("upDownTime")
            BgpSession.objects.update_or_create(
                device=device,
                vrf=vrf_name,
                peer_ip=peer_ip,
                defaults={
                    "peer_asn": peer.get("asn", 0),
                    "peer_state": peer.get("peerState", BgpSession.PeerState.UNKNOWN),
                    "prefixes_received": peer.get("prefixReceived", 0),
                    "prefixes_accepted": peer.get("prefixAccepted", 0),
                    "updown_time": datetime.fromtimestamp(updown_time, tz=dt_timezone.utc) if updown_time else None,
                },
            )


def task_arp(task, device: Device) -> None:
    """Nornir parent task: collect ARP table and sync to DB."""
    result = task.run(
        task=netmiko_send_command,
        command_string="show ip arp | json",
    )
    data = json.loads(result[0].result)
    neighbors = data.get("ipV4Neighbors", [])

    # Full replace — remove stale entries then upsert current ones.
    current_ips = {entry["address"] for entry in neighbors}
    ArpEntry.objects.filter(device=device).exclude(ip_address__in=current_ips).delete()

    for entry in neighbors:
        ArpEntry.objects.update_or_create(
            device=device,
            ip_address=entry["address"],
            defaults={
                "mac_address": entry.get("hwAddress", ""),
                "interface": entry.get("interface", ""),
                "age": entry.get("age", 0),
            },
        )


# ---------------------------------------------------------------------------
# Task dispatch
# ---------------------------------------------------------------------------

_TASK_MAP = {
    PollResult.CheckType.INTERFACES: task_interfaces,
    PollResult.CheckType.ROUTES: task_routes,
    PollResult.CheckType.BGP_SESSIONS: task_bgp_sessions,
    PollResult.CheckType.ARP: task_arp,
}


def _run_check(nr: Nornir, device: Device, job_id: str, check_type: str) -> bool:
    """Run a parent Nornir task, record its timing in PollResult, return success."""
    started_at = timezone.now()
    t0 = time.perf_counter()

    results = nr.run(task=_TASK_MAP[check_type], device=device)

    success = not results.failed
    if success:
        logger.info("%s collection complete for %s", check_type, device.hostname)
    else:
        for host, multi in results.items():
            for result in multi:
                if result.exception:
                    logger.error(
                        "%s collection failed for %s: %s: %s",
                        check_type, host, type(result.exception).__name__, result.exception,
                    )

    PollResult.objects.create(
        device=device,
        job_id=job_id,
        check_type=check_type,
        started_at=started_at,
        duration_ms=round((time.perf_counter() - t0) * 1000),
        success=success,
    )
    return success


def collect_device(device: Device, job_id: str = "", task_type: str = "interfaces") -> None:
    """Run the appropriate Nornir task for *device* and persist results to DB."""
    with _db_logging(job_id=job_id, device=device):
        nr = _make_nornir(device)
        logger.info("Starting %s collection for %s", task_type, device.hostname)
        _run_check(nr, device, job_id, task_type)
