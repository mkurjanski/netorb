from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django_q.models import Schedule

from .models import PollingSchedule

_TASK_FUNC = "netorb.tasks.poll_all_devices"


def _schedule_name(ps: PollingSchedule) -> str:
    return f"netorb:poll:{ps.task_type}"


def _sync(ps: PollingSchedule) -> None:
    name = _schedule_name(ps)
    if not ps.enabled:
        Schedule.objects.filter(name=name).delete()
        return
    Schedule.objects.update_or_create(
        name=name,
        defaults={
            "func": _TASK_FUNC,
            "schedule_type": Schedule.MINUTES,
            "minutes": ps.interval_minutes,
            "repeats": -1,
        },
    )


@receiver(post_save, sender=PollingSchedule)
def on_polling_schedule_saved(sender, instance, **kwargs):
    _sync(instance)


@receiver(post_delete, sender=PollingSchedule)
def on_polling_schedule_deleted(sender, instance, **kwargs):
    Schedule.objects.filter(name=_schedule_name(instance)).delete()
