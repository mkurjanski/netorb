"""
Business logic for collecting network state from devices via Nornir.

Collection flow:
  collect_device(device)
    └─ _make_nornir()         → single-host Nornir instance (DictInventory)
    ├─ _collect_interfaces()  → show interfaces json → upsert Interface rows
    └─ _collect_routes()      → show ip route json   → upsert IPv4Route + NextHop rows
"""

import json
import logging

from django.conf import settings
from nornir import InitNornir
from nornir_netmiko.tasks import netmiko_send_command

from .models import Device, Interface, IPv4Route, NextHop

logger = logging.getLogger(__name__)


def _make_nornir(device: Device):
    """Build a single-host Nornir instance from a Device ORM object."""
    return InitNornir(
        runner={"plugin": "serial"},
        logging={"enabled": False},
        inventory={
            "plugin": "DictInventory",
            "options": {
                "hosts": {
                    device.hostname: {
                        "hostname": device.hostname,
                        "username": settings.NORNIR_USERNAME,
                        "password": settings.NORNIR_PASSWORD,
                        "platform": "arista_eos",
                    }
                },
                "groups": {},
                "defaults": {},
            },
        },
    )


def _collect_interfaces(task):
    """Nornir task: run 'show interfaces json' and return parsed interface dict."""
    result = task.run(
        task=netmiko_send_command,
        command_string="show interfaces json",
    )
    raw = json.loads(result[0].result)
    return {
        name: {"is_up": attrs.get("lineProtocolStatus") == "connected"}
        for name, attrs in raw.get("interfaces", {}).items()
    }


def _collect_routes(task):
    """Nornir task: run 'show ip route json' and return raw VRF route dict."""
    result = task.run(
        task=netmiko_send_command,
        command_string="show ip route json",
    )
    return json.loads(result[0].result)


def _sync_interfaces(device: Device, interfaces: dict) -> None:
    for name, attrs in interfaces.items():
        status = (
            Interface.OperStatus.UP if attrs["is_up"] else Interface.OperStatus.DOWN
        )
        Interface.objects.update_or_create(
            device=device,
            name=name,
            defaults={"oper_status": status},
        )


def _sync_routes(device: Device, route_data: dict) -> None:
    routes = route_data.get("vrfs", {}).get("default", {}).get("routes", {})
    for prefix, info in routes.items():
        route, _ = IPv4Route.objects.update_or_create(
            device=device,
            prefix=prefix,
        )
        # Replace next hops on every sync to reflect current state.
        route.next_hops.all().delete()
        for via in info.get("vias", []):
            nh = via.get("nexthopAddr")
            # EOS uses the string "None" for directly connected routes.
            if nh and nh != "None":
                NextHop.objects.create(route=route, ip_address=nh)


def collect_device(device: Device) -> None:
    """Collect interface status and routing table for *device* and persist to DB."""
    nr = _make_nornir(device)

    iface_results = nr.run(task=_collect_interfaces)
    route_results = nr.run(task=_collect_routes)

    for host, multi in iface_results.items():
        if multi.failed:
            logger.error("Interface collection failed for %s: %s", host, multi[0].exception)
        else:
            _sync_interfaces(device, multi[0].result)

    for host, multi in route_results.items():
        if multi.failed:
            logger.error("Route collection failed for %s: %s", host, multi[0].exception)
        else:
            _sync_routes(device, multi[0].result)
