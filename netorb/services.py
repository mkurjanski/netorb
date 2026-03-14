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
import time
from contextlib import contextmanager

from django.conf import settings
from django.utils import timezone
from nornir.core import Nornir
from nornir.core.configuration import Config
from nornir.core.inventory import Defaults, Groups, Host, Hosts, Inventory
from nornir.plugins.runners import SerialRunner
from nornir_netmiko.tasks import netmiko_send_command

from .log_handler import DBLogHandler
from .models import Device, Interface, IPv4Route, NextHop, PollResult

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


def _collect_interfaces(task):
    """Nornir task: run 'show interfaces json' and return parsed interface dict."""
    result = task.run(
        task=netmiko_send_command,
        command_string="show interfaces json",
        read_timeout=60,
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


def _run_check(nr, task_fn, device: Device, job_id: str, check_type: str) -> bool:
    """Run a single Nornir task, record its timing in PollResult, return success."""
    started_at = timezone.now()
    t0 = time.perf_counter()
    success = True

    results = nr.run(task=task_fn)

    for host, multi in results.items():
        if multi.failed:
            for result in multi:
                if result.exception:
                    logger.error("%s collection failed for %s: %s: %s", check_type, host, type(result.exception).__name__, result.exception)
            success = False
        else:
            if check_type == PollResult.CheckType.INTERFACES:
                _sync_interfaces(device, multi[0].result)
            else:
                _sync_routes(device, multi[0].result)
            logger.info("%s synced for %s", check_type.capitalize(), host)

    duration_ms = round((time.perf_counter() - t0) * 1000)
    PollResult.objects.create(
        device=device,
        job_id=job_id,
        check_type=check_type,
        started_at=started_at,
        duration_ms=duration_ms,
        success=success,
    )
    return success


def collect_device(device: Device, job_id: str = "") -> None:
    """Collect interface status and routing table for *device* and persist to DB."""
    with _db_logging(job_id=job_id, device=device):
        nr = _make_nornir(device)
        logger.info("Starting collection for %s", device.hostname)

        _run_check(nr, _collect_interfaces, device, job_id, PollResult.CheckType.INTERFACES)
        _run_check(nr, _collect_routes, device, job_id, PollResult.CheckType.ROUTES)

        logger.info("Collection complete for %s", device.hostname)
