from netfields import CidrAddressField
from django.db import models


class Device(models.Model):
    hostname = models.CharField(
        max_length=255,
        unique=True,
        help_text="Hostname or IP address of the monitored device.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["hostname"]
        verbose_name = "Device"
        verbose_name_plural = "Devices"

    def __str__(self):
        return self.hostname


class Interface(models.Model):
    class OperStatus(models.TextChoices):
        UP = "up", "Up"
        DOWN = "down", "Down"
        UNKNOWN = "unknown", "Unknown"

    device = models.ForeignKey(
        Device,
        on_delete=models.CASCADE,
        related_name="interfaces",
        help_text="Device this interface belongs to.",
    )
    name = models.CharField(
        max_length=255,
        help_text="Interface name as reported by the device (e.g. Ethernet1).",
    )
    oper_status = models.CharField(
        max_length=16,
        choices=OperStatus.choices,
        default=OperStatus.UNKNOWN,
        help_text="Operational status of the interface.",
    )
    collected_at = models.DateTimeField(
        auto_now=True,
        help_text="Timestamp of the last data collection.",
    )

    class Meta:
        ordering = ["device", "name"]
        verbose_name = "Interface"
        verbose_name_plural = "Interfaces"
        constraints = [
            models.UniqueConstraint(
                fields=["device", "name"], name="unique_device_interface"
            )
        ]

    def __str__(self):
        return f"{self.device.hostname} / {self.name}"


class IPv4Route(models.Model):
    device = models.ForeignKey(
        Device,
        on_delete=models.CASCADE,
        related_name="ipv4_routes",
        help_text="Device this route was collected from.",
    )
    prefix = CidrAddressField(
        help_text="Destination prefix in CIDR notation (e.g. 10.0.0.0/24).",
    )
    collected_at = models.DateTimeField(
        auto_now=True,
        help_text="Timestamp of the last data collection.",
    )

    class Meta:
        ordering = ["device", "prefix"]
        verbose_name = "IPv4 Route"
        verbose_name_plural = "IPv4 Routes"
        constraints = [
            models.UniqueConstraint(
                fields=["device", "prefix"], name="unique_device_prefix"
            )
        ]

    def __str__(self):
        return f"{self.device.hostname} / {self.prefix}"


class NextHop(models.Model):
    route = models.ForeignKey(
        IPv4Route,
        on_delete=models.CASCADE,
        related_name="next_hops",
        help_text="Route this next hop belongs to.",
    )
    ip_address = models.GenericIPAddressField(
        protocol="IPv4",
        help_text="Next hop IPv4 address.",
    )

    class Meta:
        ordering = ["route", "ip_address"]
        verbose_name = "Next Hop"
        verbose_name_plural = "Next Hops"
        constraints = [
            models.UniqueConstraint(
                fields=["route", "ip_address"], name="unique_route_nexthop"
            )
        ]

    def __str__(self):
        return f"{self.route} -> {self.ip_address}"
