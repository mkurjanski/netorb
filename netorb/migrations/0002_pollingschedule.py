from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("netorb", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="PollingSchedule",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "device",
                    models.ForeignKey(
                        help_text="Device to poll.",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="polling_schedules",
                        to="netorb.device",
                    ),
                ),
                (
                    "task_type",
                    models.CharField(
                        choices=[("interfaces", "Interfaces"), ("routes", "Routes"), ("all", "All")],
                        default="all",
                        help_text="Which data to collect on each run.",
                        max_length=16,
                    ),
                ),
                (
                    "interval_minutes",
                    models.PositiveIntegerField(
                        default=5,
                        help_text="How often to poll this device, in minutes.",
                    ),
                ),
                (
                    "enabled",
                    models.BooleanField(
                        default=True,
                        help_text="Uncheck to pause polling without deleting the schedule.",
                    ),
                ),
                (
                    "last_run_at",
                    models.DateTimeField(
                        blank=True,
                        null=True,
                        help_text="Timestamp of the last successful poll.",
                    ),
                ),
                (
                    "next_run_at",
                    models.DateTimeField(
                        blank=True,
                        null=True,
                        help_text="Timestamp when the next poll is due.",
                    ),
                ),
            ],
            options={
                "verbose_name": "Polling Schedule",
                "verbose_name_plural": "Polling Schedules",
                "ordering": ["device", "task_type"],
            },
        ),
        migrations.AddConstraint(
            model_name="pollingschedule",
            constraint=models.UniqueConstraint(
                fields=["device", "task_type"],
                name="unique_device_task_type",
            ),
        ),
    ]
