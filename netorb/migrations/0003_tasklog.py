from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("netorb", "0002_pollingschedule"),
    ]

    operations = [
        migrations.CreateModel(
            name="TaskLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("job_id", models.CharField(db_index=True, help_text="django-q2 task ID that produced this entry.", max_length=64)),
                (
                    "device",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        help_text="Device being polled when this entry was emitted.",
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="task_logs",
                        to="netorb.device",
                    ),
                ),
                (
                    "level",
                    models.CharField(
                        choices=[("DEBUG", "Debug"), ("INFO", "Info"), ("WARNING", "Warning"), ("ERROR", "Error")],
                        default="INFO",
                        max_length=8,
                    ),
                ),
                ("message", models.TextField()),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
            ],
            options={
                "verbose_name": "Task Log",
                "verbose_name_plural": "Task Logs",
                "ordering": ["created_at"],
            },
        ),
    ]
