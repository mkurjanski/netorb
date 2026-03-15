"""
Business logic for collecting network state from devices via Nornir.

Collection flow:
  collect_device(device, task_type)
    └─ _make_nornir()        → single-host Nornir instance
    ├─ task_interfaces()     → SSH → 'show interfaces | json'    → parse → upsert Interface rows
    ├─ task_routes()         → SSH → 'show ip route | json'      → parse → upsert IPv4Route rows
    ├─ task_bgp_sessions()   → SSH → 'show ip bgp summary | json'→ parse → upsert BgpSession rows
    └─ task_arp()            → SSH → 'show ip arp | json'        → parse → upsert ArpEntry rows
"""

import ipaddress
import json
import logging
import time
from contextlib import contextmanager
from datetime import datetime, timezone as dt_timezone

from django.conf import settings
from django.db.models import Func, IntegerField
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
from .models import ArpEntry, BgpSession, Device, Interface, IPv4Route, PollResult

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
        name=device.ip_address,
        hostname=device.ip_address,
        username=settings.NORNIR_USERNAME,
        password=settings.NORNIR_PASSWORD,
        platform="arista_eos",
        groups=Groups(),
        defaults=Defaults(),
    )
    inventory = Inventory(hosts=Hosts({device.ip_address: host}), groups=Groups(), defaults=Defaults())
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
        primary_ip = ""
        iface_addrs = attrs.get("interfaceAddress", [])
        if iface_addrs:
            pip = iface_addrs[0].get("primaryIp", {})
            addr = pip.get("address", "0.0.0.0")
            if addr != "0.0.0.0":
                primary_ip = f"{addr}/{pip.get('maskLen', 0)}"
        Interface.objects.update_or_create(
            device=device,
            name=name,
            defaults={"oper_status": status, "primary_ip": primary_ip},
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
        next_hops = []
        for via in info.get("vias", []):
            nh_addr = via.get("nexthopAddr")
            # EOS uses the string "None" for directly connected routes.
            if nh_addr in (None, "None"):
                continue
            next_hops.append({
                "nexthop": nh_addr,
                "interface": via.get("interface", ""),
            })
        IPv4Route.objects.update_or_create(
            device=device,
            prefix=prefix,
            defaults={"next_hops": next_hops},
        )


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
        logger.info("%s collection complete for %s", check_type, device.display_name)
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
        logger.info("Starting %s collection for %s", task_type, device.display_name)
        _run_check(nr, device, job_id, task_type)


# ---------------------------------------------------------------------------
# Path tracer
# ---------------------------------------------------------------------------

class _MaskLen(Func):
    function = "masklen"
    output_field = IntegerField()


def _longest_prefix_match(device: Device, dest_ip: str):
    """Return the most-specific IPv4Route on *device* that contains *dest_ip*, or None."""
    return (
        IPv4Route.objects
        .filter(device=device, prefix__net_contains_or_equals=dest_ip)
        .annotate(mask_len=_MaskLen("prefix"))
        .order_by("-mask_len")
        .first()
    )


def _find_interface_by_ip(ip: str):
    """Find the Interface whose primary_ip matches *ip* (ignoring mask), or None."""
    matches = Interface.objects.filter(
        primary_ip__startswith=ip + "/"
    ).select_related("device")
    return matches.first()


def trace_path(source: Device, dest_ip: str, max_depth: int = 20) -> list[list[dict]]:
    """
    Trace all paths from *source* towards *dest_ip* using collected routing data.

    Returns a list of paths. Each path is a list of hop dicts:
        {
            "device":    Device instance,
            "prefix":    matched route prefix (str) or None,
            "next_hop":  next-hop IP (str) or None,
            "via_iface": Interface the next-hop was resolved on (on the next device), or None,
            "reason":    None while the path continues, or a termination reason string,
        }
    """
    # Validate dest_ip
    try:
        ipaddress.ip_address(dest_ip)
    except ValueError:
        return [[{"device": source, "prefix": None, "next_hop": None,
                  "outbound_iface": None, "inbound_iface": None,
                  "reason": f"invalid destination IP: {dest_ip}"}]]

    def _trace(device, visited, inbound_iface_name=None):
        """Recursively trace paths. inbound_iface_name is the interface name
        on *this* device that received traffic from the previous hop."""
        if device.pk in visited:
            return [[{"device": device, "prefix": None, "next_hop": None,
                       "outbound_iface": None, "inbound_iface": None,
                       "reason": "loop detected"}]]

        if len(visited) >= max_depth:
            return [[{"device": device, "prefix": None, "next_hop": None,
                       "outbound_iface": None, "inbound_iface": None,
                       "reason": "max depth reached"}]]

        visited = visited | {device.pk}

        route = _longest_prefix_match(device, dest_ip)
        if not route:
            return [[{"device": device, "prefix": None, "next_hop": None,
                       "outbound_iface": None, "inbound_iface": inbound_iface_name,
                       "reason": "no route"}]]

        prefix_str = str(route.prefix)

        if not route.next_hops:
            return [[{"device": device, "prefix": prefix_str, "next_hop": None,
                       "outbound_iface": None, "inbound_iface": inbound_iface_name,
                       "reason": "directly connected"}]]

        # Check if destination is in a directly-connected subnet on this device
        dest_iface = _find_interface_by_ip(dest_ip)
        if dest_iface and dest_iface.device_id == device.pk:
            return [[{"device": device, "prefix": prefix_str, "next_hop": None,
                       "outbound_iface": None, "inbound_iface": inbound_iface_name,
                       "reason": "destination is local"}]]

        paths = []
        for nh_entry in route.next_hops:
            nh_ip = nh_entry["nexthop"]
            out_iface = nh_entry.get("interface", "")
            remote_iface = _find_interface_by_ip(nh_ip)
            hop = {
                "device": device,
                "prefix": prefix_str,
                "next_hop": nh_ip,
                "outbound_iface": out_iface,
                "inbound_iface": inbound_iface_name,
                "reason": None,
            }

            if not remote_iface:
                hop["reason"] = "next hop not in inventory"
                paths.append([hop])
                continue

            next_device = remote_iface.device
            sub_paths = _trace(next_device, visited, inbound_iface_name=remote_iface.name)
            for sp in sub_paths:
                paths.append([hop] + sp)

        return paths

    return _trace(source, frozenset())
