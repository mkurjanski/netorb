"""
Task functions for device polling. Can be called directly or triggered from the admin.
"""

import logging
import uuid

from django.utils import timezone

from .models import PollingTask
from .services import collect_all

logger = logging.getLogger(__name__)


def run_polling_task(polling_task: PollingTask) -> None:
    """Run a PollingTask against all devices concurrently and update its status."""
    job_id = f"poll:{polling_task.task_type}:{uuid.uuid4().hex[:8]}"
    success = collect_all(task_type=polling_task.task_type, job_id=job_id)

    PollingTask.objects.filter(pk=polling_task.pk).update(
        last_run_at=timezone.now(),
        last_success=success,
    )
