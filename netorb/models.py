import pghistory
from django.contrib.postgres.fields import ArrayField
from django.db import models
from netfields import CidrAddressField


class Device(models.Model):
    hostname = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Human-readable hostname of the device (optional).",
    )
    ip_address = models.GenericIPAddressField(
        protocol="IPv4",
        unique=True,
        help_text="IPv4 address used to connect to the device.",
    )
    description = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Optional free-text description of the device.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["ip_address"]
        verbose_name = "Device"
        verbose_name_plural = "Devices"

    @property
    def display_name(self) -> str:
        """Return hostname if set, otherwise the IP address."""
        return self.hostname or self.ip_address

    def __str__(self):
        return self.display_name


@pghistory.track(
    pghistory.InsertEvent(),
    pghistory.UpdateEvent(),
    pghistory.DeleteEvent(),
    exclude=["collected_at"],
)
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


@pghistory.track(
    pghistory.InsertEvent(),
    pghistory.UpdateEvent(),
    pghistory.DeleteEvent(),
    exclude=["collected_at"],
)
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
    next_hops = ArrayField(
        models.GenericIPAddressField(protocol="IPv4"),
        default=list,
        blank=True,
        help_text="List of next-hop IPv4 addresses (empty for directly connected routes).",
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


class TaskLog(models.Model):
    class Level(models.TextChoices):
        DEBUG = "DEBUG", "Debug"
        INFO = "INFO", "Info"
        WARNING = "WARNING", "Warning"
        ERROR = "ERROR", "Error"

    job_id = models.CharField(
        max_length=64,
        db_index=True,
        help_text="django-q2 task ID that produced this entry.",
    )
    device = models.ForeignKey(
        "Device",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="task_logs",
        help_text="Device being polled when this entry was emitted.",
    )
    level = models.CharField(
        max_length=8,
        choices=Level.choices,
        default=Level.INFO,
    )
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["created_at"]
        verbose_name = "Task Log"
        verbose_name_plural = "Task Logs"

    def __str__(self):
        return f"[{self.level}] {self.job_id}: {self.message[:80]}"


class PollingTask(models.Model):
    class TaskType(models.TextChoices):
        INTERFACES = "interfaces", "Interfaces"
        ROUTES = "routes", "Routes"
        BGP_SESSIONS = "bgp_sessions", "BGP Sessions"
        ARP = "arp", "ARP"

    name = models.CharField(
        max_length=100,
        help_text="Human-readable name for this task.",
    )
    task_type = models.CharField(
        max_length=16,
        choices=TaskType.choices,
        default=TaskType.INTERFACES,
        unique=True,
        help_text="Which data to collect when this task runs.",
    )
    last_run_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When this task last ran.",
    )
    last_success = models.BooleanField(
        null=True,
        blank=True,
        help_text="Whether the last run completed without errors.",
    )

    class Meta:
        ordering = ["task_type"]
        verbose_name = "Polling Task"
        verbose_name_plural = "Polling Tasks"

    def __str__(self):
        return self.name


@pghistory.track(
    pghistory.InsertEvent(),
    pghistory.UpdateEvent(),
    pghistory.DeleteEvent(),
    exclude=["collected_at"],
)
class BgpSession(models.Model):
    class PeerState(models.TextChoices):
        ESTABLISHED = "Established", "Established"
        ACTIVE = "Active", "Active"
        IDLE = "Idle", "Idle"
        CONNECT = "Connect", "Connect"
        OPENSENT = "OpenSent", "OpenSent"
        OPENCONFIRM = "OpenConfirm", "OpenConfirm"
        UNKNOWN = "Unknown", "Unknown"

    device = models.ForeignKey(
        Device,
        on_delete=models.CASCADE,
        related_name="bgp_sessions",
        help_text="Device this BGP session was collected from.",
    )
    vrf = models.CharField(
        max_length=64,
        default="default",
        help_text="VRF this session belongs to.",
    )
    peer_ip = models.GenericIPAddressField(
        protocol="IPv4",
        help_text="BGP peer IP address.",
    )
    peer_asn = models.PositiveIntegerField(
        help_text="BGP peer AS number.",
    )
    peer_state = models.CharField(
        max_length=16,
        choices=PeerState.choices,
        default=PeerState.UNKNOWN,
        help_text="Current BGP session state.",
    )
    prefixes_received = models.PositiveIntegerField(
        default=0,
        help_text="Number of prefixes received from this peer.",
    )
    prefixes_accepted = models.PositiveIntegerField(
        default=0,
        help_text="Number of prefixes accepted from this peer.",
    )
    updown_time = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the session last changed state.",
    )
    collected_at = models.DateTimeField(
        auto_now=True,
        help_text="Timestamp of the last data collection.",
    )

    class Meta:
        ordering = ["device", "vrf", "peer_ip"]
        verbose_name = "BGP Session"
        verbose_name_plural = "BGP Sessions"
        constraints = [
            models.UniqueConstraint(
                fields=["device", "vrf", "peer_ip"],
                name="unique_device_vrf_peer",
            )
        ]

    def __str__(self):
        return f"{self.device.hostname} / {self.vrf} / {self.peer_ip} ({self.peer_state})"


@pghistory.track(
    pghistory.InsertEvent(),
    pghistory.UpdateEvent(),
    pghistory.DeleteEvent(),
    exclude=["collected_at"],
)
class ArpEntry(models.Model):
    device = models.ForeignKey(
        Device,
        on_delete=models.CASCADE,
        related_name="arp_entries",
        help_text="Device this ARP entry was collected from.",
    )
    ip_address = models.GenericIPAddressField(
        protocol="IPv4",
        help_text="IP address of the ARP entry.",
    )
    mac_address = models.CharField(
        max_length=32,
        help_text="MAC address in EOS dot-notation (e.g. aac1.ab30.123b).",
    )
    interface = models.CharField(
        max_length=64,
        help_text="Interface the ARP entry was learned on.",
    )
    age = models.PositiveIntegerField(
        help_text="Age of the ARP entry in seconds.",
    )
    collected_at = models.DateTimeField(
        auto_now=True,
        help_text="Timestamp of the last data collection.",
    )

    class Meta:
        ordering = ["device", "ip_address"]
        verbose_name = "ARP Entry"
        verbose_name_plural = "ARP Entries"
        constraints = [
            models.UniqueConstraint(
                fields=["device", "ip_address"],
                name="unique_device_arp_ip",
            )
        ]

    def __str__(self):
        return f"{self.device.hostname} / {self.ip_address} / {self.mac_address}"


class PollResult(models.Model):
    class CheckType(models.TextChoices):
        INTERFACES = "interfaces", "Interfaces"
        ROUTES = "routes", "Routes"
        BGP_SESSIONS = "bgp_sessions", "BGP Sessions"
        ARP = "arp", "ARP"

    device = models.ForeignKey(
        Device,
        on_delete=models.CASCADE,
        related_name="poll_results",
        help_text="Device that was polled.",
    )
    job_id = models.CharField(
        max_length=64,
        db_index=True,
        help_text="Job ID of the collection run.",
    )
    check_type = models.CharField(
        max_length=16,
        choices=CheckType.choices,
        help_text="Which data was collected in this check.",
    )
    started_at = models.DateTimeField(
        help_text="When this check started.",
    )
    duration_ms = models.PositiveIntegerField(
        help_text="How long the check took, in milliseconds.",
    )
    success = models.BooleanField(
        default=True,
        help_text="Whether the check completed without errors.",
    )

    class Meta:
        ordering = ["-started_at"]
        verbose_name = "Poll Result"
        verbose_name_plural = "Poll Results"

    def __str__(self):
        status = "ok" if self.success else "fail"
        return f"{self.device.hostname} / {self.check_type} / {self.duration_ms}ms [{status}]"


