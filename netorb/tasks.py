"""
Django-Q2 task functions for scheduled device polling.

Scheduling (run once after migrations):
    from django_q.models import Schedule
    Schedule.objects.create(
        func="netorb.tasks.poll_all_devices",
        schedule_type=Schedule.MINUTES,
        minutes=5,
        repeats=-1,  # run indefinitely
        name="Poll all devices",
    )

Worker:
    python manage.py qcluster
"""

import logging

from .models import Device
from .services import collect_device

logger = logging.getLogger(__name__)


def poll_device(device_id: int) -> None:
    """Collect interface status and routes for a single device (by PK)."""
    try:
        device = Device.objects.get(pk=device_id)
    except Device.DoesNotExist:
        logger.error("poll_device: Device pk=%s not found", device_id)
        return
    logger.info("Polling device %s", device.hostname)
    collect_device(device)
    logger.info("Polling complete for %s", device.hostname)


def poll_all_devices() -> None:
    """Collect interface status and routes for every device in the inventory."""
    devices = Device.objects.all()
    if not devices.exists():
        logger.warning("poll_all_devices: no devices in inventory")
        return
    for device in devices:
        logger.info("Polling device %s", device.hostname)
        collect_device(device)
