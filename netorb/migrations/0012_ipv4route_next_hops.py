from django.contrib.postgres.fields import ArrayField
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("netorb", "0011_alter_pollingtask_task_type_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="ipv4route",
            name="next_hops",
            field=ArrayField(
                models.GenericIPAddressField(protocol="IPv4"),
                blank=True,
                default=list,
                help_text="List of next-hop IPv4 addresses (empty for directly connected routes).",
            ),
        ),
    ]
