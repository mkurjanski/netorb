from django.db import migrations, models
import netfields.fields
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Device",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("hostname", models.CharField(help_text="Hostname or IP address of the monitored device.", max_length=255, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Device",
                "verbose_name_plural": "Devices",
                "ordering": ["hostname"],
            },
        ),
        migrations.CreateModel(
            name="Interface",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("device", models.ForeignKey(help_text="Device this interface belongs to.", on_delete=django.db.models.deletion.CASCADE, related_name="interfaces", to="netorb.device")),
                ("name", models.CharField(help_text="Interface name as reported by the device (e.g. Ethernet1).", max_length=255)),
                ("oper_status", models.CharField(choices=[("up", "Up"), ("down", "Down"), ("unknown", "Unknown")], default="unknown", help_text="Operational status of the interface.", max_length=16)),
                ("collected_at", models.DateTimeField(auto_now=True, help_text="Timestamp of the last data collection.")),
            ],
            options={
                "verbose_name": "Interface",
                "verbose_name_plural": "Interfaces",
                "ordering": ["device", "name"],
            },
        ),
        migrations.AddConstraint(
            model_name="interface",
            constraint=models.UniqueConstraint(fields=["device", "name"], name="unique_device_interface"),
        ),
        migrations.CreateModel(
            name="IPv4Route",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("device", models.ForeignKey(help_text="Device this route was collected from.", on_delete=django.db.models.deletion.CASCADE, related_name="ipv4_routes", to="netorb.device")),
                ("prefix", netfields.fields.CidrAddressField(help_text="Destination prefix in CIDR notation (e.g. 10.0.0.0/24).")),
                ("collected_at", models.DateTimeField(auto_now=True, help_text="Timestamp of the last data collection.")),
            ],
            options={
                "verbose_name": "IPv4 Route",
                "verbose_name_plural": "IPv4 Routes",
                "ordering": ["device", "prefix"],
            },
        ),
        migrations.AddConstraint(
            model_name="ipv4route",
            constraint=models.UniqueConstraint(fields=["device", "prefix"], name="unique_device_prefix"),
        ),
        migrations.CreateModel(
            name="NextHop",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("route", models.ForeignKey(help_text="Route this next hop belongs to.", on_delete=django.db.models.deletion.CASCADE, related_name="next_hops", to="netorb.ipv4route")),
                ("ip_address", models.GenericIPAddressField(help_text="Next hop IPv4 address.", protocol="IPv4")),
            ],
            options={
                "verbose_name": "Next Hop",
                "verbose_name_plural": "Next Hops",
                "ordering": ["route", "ip_address"],
            },
        ),
        migrations.AddConstraint(
            model_name="nexthop",
            constraint=models.UniqueConstraint(fields=["route", "ip_address"], name="unique_route_nexthop"),
        ),
    ]
