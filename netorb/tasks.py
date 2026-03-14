"""
Task functions for device polling. Can be called directly or triggered from the admin.
"""

import logging
import uuid

from django.utils import timezone

from .models import Device, PollingTask
from .services import collect_device

logger = logging.getLogger(__name__)


def run_polling_task(polling_task: PollingTask) -> None:
    """Run a PollingTask against all devices and update its last_run_at / last_success."""
    devices = Device.objects.all()
    if not devices.exists():
        logger.warning("run_polling_task: no devices in inventory")
        return

    job_id = f"poll:{polling_task.task_type}:{uuid.uuid4().hex[:8]}"
    success = True

    for device in devices:
        try:
            collect_device(device, job_id=job_id, task_type=polling_task.task_type)
        except Exception as exc:
            logger.error("Collection failed for %s: %s", device.hostname, exc)
            success = False

    PollingTask.objects.filter(pk=polling_task.pk).update(
        last_run_at=timezone.now(),
        last_success=success,
    )
