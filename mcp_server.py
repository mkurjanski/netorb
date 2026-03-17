#!/usr/bin/env python3
"""
MCP server: run 'show' commands against containerlab nodes via Netmiko.

Reads device list from the netorb Django DB. Credentials come from .env
(NORNIR_USERNAME / NORNIR_PASSWORD). Only 'show' commands are accepted.
"""

import os
import sys

# Bootstrap Django before importing any app code
sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django
django.setup()

from django.conf import settings
from netmiko import ConnectHandler, NetmikoTimeoutException, NetmikoAuthenticationException
from mcp.server.fastmcp import FastMCP

from netorb.models import Device

mcp = FastMCP("netorb-clab")


def _connect_and_run(hostname: str, command: str) -> str:
    try:
        conn = ConnectHandler(
            device_type="arista_eos",
            host=hostname,
            username=settings.NORNIR_USERNAME,
            password=settings.NORNIR_PASSWORD,
        )
        output = conn.send_command(command)
        conn.disconnect()
        return output
    except NetmikoTimeoutException:
        return f"[ERROR] Connection to {hostname} timed out."
    except NetmikoAuthenticationException:
        return f"[ERROR] Authentication failed for {hostname}."
    except Exception as e:
        return f"[ERROR] {hostname}: {e}"


@mcp.tool()
def run_show_command(hostname: str, command: str) -> str:
    """
    Run a 'show' command against one or all containerlab nodes via SSH.

    Args:
        hostname: Device hostname as stored in the netorb DB, or "all" to
                  target every device.
        command:  The show command to run (must begin with "show").

    Returns:
        Command output, prefixed per device when hostname="all".
    """
    if not command.strip().lower().startswith("show"):
        return "[ERROR] Only 'show' commands are permitted."

    if hostname == "all":
        devices = list(Device.objects.values_list("hostname", flat=True))
    else:
        if not Device.objects.filter(hostname=hostname).exists():
            known = ", ".join(Device.objects.values_list("hostname", flat=True))
            return f"[ERROR] Unknown device '{hostname}'. Known devices: {known}"
        devices = [hostname]

    if not devices:
        return "[ERROR] No devices found in the database."

    parts = []
    for host in devices:
        output = _connect_and_run(host, command)
        if len(devices) > 1:
            parts.append(f"=== {host} ===\n{output}")
        else:
            parts.append(output)

    return "\n\n".join(parts)


@mcp.tool()
def list_devices() -> str:
    """
    List all devices registered in the netorb database.

    Returns:
        Newline-separated list of device hostnames.
    """
    devices = list(Device.objects.values_list("hostname", flat=True))
    if not devices:
        return "No devices found in the database."
    return "\n".join(devices)


if __name__ == "__main__":
    mcp.run(transport="stdio")
