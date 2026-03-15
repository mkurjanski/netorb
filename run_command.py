#!/usr/bin/env python
"""Run an arbitrary CLI command against a network device.

Usage:
    ./run_command.py <host> "<command>"
    ./run_command.py 172.20.20.2 "show version"
    ./run_command.py 172.20.20.2 "show ip bgp summary"
"""

import sys
from pathlib import Path

from decouple import Config, RepositoryEnv
from nornir.core import Nornir
from nornir.core.configuration import Config as NornirConfig
from nornir.core.inventory import Defaults, Groups, Host, Hosts, Inventory
from nornir.core.plugins.connections import ConnectionPluginRegister
from nornir.plugins.runners import SerialRunner
from nornir_netmiko.connections.netmiko import Netmiko as NetmikoPlugin
from nornir_netmiko.tasks import netmiko_send_command

ConnectionPluginRegister.register("netmiko", NetmikoPlugin)

ENV = Config(RepositoryEnv(Path(__file__).parent / ".env"))


def run(host: str, command: str) -> str:
    host_obj = Host(
        name=host,
        hostname=host,
        username=ENV("NORNIR_USERNAME", default="admin"),
        password=ENV("NORNIR_PASSWORD", default=""),
        platform="arista_eos",
        groups=Groups(),
        defaults=Defaults(),
    )
    nr = Nornir(
        inventory=Inventory(hosts=Hosts({host: host_obj}), groups=Groups(), defaults=Defaults()),
        runner=SerialRunner(),
        config=NornirConfig(logging={"enabled": False}),
    )
    results = nr.run(task=netmiko_send_command, command_string=command)
    for _host, result in results.items():
        if result.failed:
            raise RuntimeError(f"Command failed on {_host}: {result[0].exception}")
        return result[0].result


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    print(run(sys.argv[1], sys.argv[2]))
