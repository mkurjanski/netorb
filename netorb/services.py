"""
Business logic for collecting network state from devices via Nornir.

Collection flow:
  collect_all(task_type, job_id)
    └─ _make_nornir(devices)  → multi-host Nornir (ThreadedRunner, concurrent)
    └─ nr.run(task_fn)        → runs on all hosts in parallel
       ├─ task_interfaces()   → SSH → 'show interfaces | json'    → parse → upsert Interface rows
       ├─ task_routes()       → SSH → 'show ip route | json'      → parse → upsert IPv4Route rows
       ├─ task_bgp_sessions() → SSH → 'show ip bgp summary | json'→ parse → upsert BgpSession rows
       └─ task_arp()          → SSH → 'show ip arp | json'        → parse → upsert ArpEntry rows
    └─ PollResult.objects.create(...)  → one batch-level row
"""

import ipaddress
import json
import logging
import time
from contextlib import contextmanager
from datetime import timedelta

from django.conf import settings
from django.db.models import Func, IntegerField
from django.utils import timezone
from nornir.core import Nornir
from nornir.core.configuration import Config
from nornir.core.inventory import Defaults, Groups, Host, Hosts, Inventory
from nornir.core.plugins.connections import ConnectionPluginRegister
from nornir.plugins.runners import ThreadedRunner
from nornir_netmiko.connections.netmiko import Netmiko as NetmikoPlugin
from nornir_netmiko.tasks import netmiko_send_command

ConnectionPluginRegister.register("netmiko", NetmikoPlugin)

from .log_handler import DBLogHandler
from .models import ArpEntry, BgpSession, Device, Interface, IPv4Route, LldpNeighbor, PollResult

logger = logging.getLogger(__name__)


@contextmanager
def _db_logging(job_id: str):
    """Attach a DBLogHandler for the duration of a collection run."""
    handler = DBLogHandler(job_id=job_id)
    handler.setFormatter(logging.Formatter("%(name)s - %(message)s"))

    loggers = [logging.getLogger("netorb"), logging.getLogger("nornir")]
    saved_levels = []
    for lg in loggers:
        saved_levels.append(lg.level)
        if lg.level == logging.NOTSET or lg.level > logging.INFO:
            lg.setLevel(logging.INFO)
        lg.addHandler(handler)
    try:
        yield
    finally:
        for lg, saved in zip(loggers, saved_levels):
            lg.removeHandler(handler)
            lg.setLevel(saved)


def _make_nornir(devices) -> Nornir:
    """Build a multi-host Nornir instance from Device queryset.

    Each host stores its Device ORM object in host.data["device"] so that
    task functions can access it.
    """
    hosts = Hosts()
    for device in devices:
        hosts[device.ip_address] = Host(
            name=device.ip_address,
            hostname=device.ip_address,
            username=settings.NORNIR_USERNAME,
            password=settings.NORNIR_PASSWORD,
            platform="arista_eos",
            data={"device": device},
            groups=Groups(),
            defaults=Defaults(),
        )
    inventory = Inventory(hosts=hosts, groups=Groups(), defaults=Defaults())
    return Nornir(inventory=inventory, runner=ThreadedRunner(), config=Config(logging={"enabled": False}))


# ---------------------------------------------------------------------------
# Nornir tasks — each handles collection + DB sync for one data type.
# The Device ORM object is retrieved from task.host.data["device"].
# ---------------------------------------------------------------------------

def task_interfaces(task) -> None:
    device = task.host.data["device"]
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


def task_routes(task) -> None:
    device = task.host.data["device"]
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


def task_bgp_sessions(task) -> None:
    device = task.host.data["device"]
    result = task.run(
        task=netmiko_send_command,
        command_string="show ip bgp summary | json",
    )
    data = json.loads(result[0].result)
    now = timezone.now()
    for vrf_name, vrf_data in data.get("vrfs", {}).items():
        for peer_ip, peer in vrf_data.get("peers", {}).items():
            uptime_seconds = peer.get("upDownTime")
            time_of_last_change = (now - timedelta(seconds=uptime_seconds)) if uptime_seconds else None
            BgpSession.objects.update_or_create(
                device=device,
                vrf=vrf_name,
                peer_ip=peer_ip,
                defaults={
                    "peer_asn": peer.get("asn", 0),
                    "peer_state": peer.get("peerState", BgpSession.PeerState.UNKNOWN),
                    "prefixes_received": peer.get("prefixReceived", 0),
                    "prefixes_accepted": peer.get("prefixAccepted", 0),
                    "time_of_last_change": time_of_last_change,
                },
            )


def task_arp(task) -> None:
    device = task.host.data["device"]
    result = task.run(
        task=netmiko_send_command,
        command_string="show ip arp | json",
    )
    data = json.loads(result[0].result)
    neighbors = data.get("ipV4Neighbors", [])

    current_ips = {entry["address"] for entry in neighbors}
    ArpEntry.objects.filter(device=device).exclude(ip_address__in=current_ips).delete()

    for entry in neighbors:
        ArpEntry.objects.update_or_create(
            device=device,
            ip_address=entry["address"],
            defaults={
                "mac_address": entry.get("hwAddress", ""),
                "interface": entry.get("interface", ""),
            },
        )


def task_lldp(task) -> None:
    device = task.host.data["device"]
    result = task.run(
        task=netmiko_send_command,
        command_string="show lldp neighbors | json",
    )
    data = json.loads(result[0].result)
    neighbors = data.get("lldpNeighbors", [])

    # Full replace — remove stale entries then upsert current ones.
    current_keys = {
        (n["port"], n["neighborDevice"], n["neighborPort"]) for n in neighbors
    }
    for existing in LldpNeighbor.objects.filter(device=device):
        key = (existing.local_port, existing.neighbor_device, existing.neighbor_port)
        if key not in current_keys:
            existing.delete()

    for n in neighbors:
        LldpNeighbor.objects.update_or_create(
            device=device,
            local_port=n["port"],
            neighbor_device=n["neighborDevice"],
            neighbor_port=n["neighborPort"],
        )


# ---------------------------------------------------------------------------
# Collection entry point
# ---------------------------------------------------------------------------

_TASK_MAP = {
    PollResult.CheckType.INTERFACES: task_interfaces,
    PollResult.CheckType.ROUTES: task_routes,
    PollResult.CheckType.BGP_SESSIONS: task_bgp_sessions,
    PollResult.CheckType.ARP: task_arp,
    PollResult.CheckType.LLDP: task_lldp,
}


def collect_all(task_type: str, job_id: str = "") -> bool:
    """Run a Nornir task concurrently against all devices in inventory.

    Creates a single batch-level PollResult row.
    Returns True if all devices succeeded.
    """
    devices = list(Device.objects.all())
    if not devices:
        logger.warning("collect_all: no devices in inventory")
        return True

    with _db_logging(job_id=job_id):
        nr = _make_nornir(devices)
        logger.info("Starting %s collection for %d devices", task_type, len(devices))

        started_at = timezone.now()
        t0 = time.perf_counter()

        results = nr.run(task=_TASK_MAP[task_type])

        duration_ms = round((time.perf_counter() - t0) * 1000)
        all_ok = not results.failed

        for host_ip, multi in results.items():
            device = nr.inventory.hosts[host_ip].data["device"]
            if multi.failed:
                for result in multi:
                    if result.exception:
                        logger.error(
                            "%s failed for %s: %s: %s",
                            task_type, device.display_name,
                            type(result.exception).__name__, result.exception,
                        )
            else:
                logger.info("%s complete for %s", task_type, device.display_name)

        PollResult.objects.create(
            job_id=job_id,
            check_type=task_type,
            started_at=started_at,
            duration_ms=duration_ms,
            success=all_ok,
        )

        logger.info(
            "%s collection finished in %d ms — %d/%d ok",
            task_type, duration_ms,
            sum(1 for m in results.values() if not m.failed), len(devices),
        )

    return all_ok


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
