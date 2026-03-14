from netfields import CidrAddressField
from django.db import models


class Device(models.Model):
    hostname = models.CharField(
        max_length=255,
        unique=True,
        help_text="Hostname or IP address of the monitored device.",
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


class PollingSchedule(models.Model):
    class TaskType(models.TextChoices):
        INTERFACES = "interfaces", "Interfaces"
        ROUTES = "routes", "Routes"
        ALL = "all", "All"

    task_type = models.CharField(
        max_length=16,
        choices=TaskType.choices,
        default=TaskType.ALL,
        unique=True,
        help_text="Which data to collect on each run (applies to all devices).",
    )
    interval_minutes = models.PositiveIntegerField(
        default=5,
        help_text="How often to poll all devices, in minutes.",
    )
    enabled = models.BooleanField(
        default=True,
        help_text="Uncheck to pause polling without deleting the schedule.",
    )
    last_run_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp of the last successful poll.",
    )
    next_run_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when the next poll is due.",
    )

    class Meta:
        ordering = ["task_type"]
        verbose_name = "Polling Schedule"
        verbose_name_plural = "Polling Schedules"

    def __str__(self):
        return f"{self.task_type} every {self.interval_minutes}m"


class PollResult(models.Model):
    class CheckType(models.TextChoices):
        INTERFACES = "interfaces", "Interfaces"
        ROUTES = "routes", "Routes"

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
