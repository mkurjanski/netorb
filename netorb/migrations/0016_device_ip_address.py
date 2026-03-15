from django.db import migrations, models


def copy_hostname_to_ip_address(apps, schema_editor):
    Device = apps.get_model("netorb", "Device")
    for device in Device.objects.all():
        device.ip_address = device.hostname
        device.save(update_fields=["ip_address"])


class Migration(migrations.Migration):

    dependencies = [
        ("netorb", "0015_arpentryevent_bgpsessionevent_interfaceevent_and_more"),
    ]

    operations = [
        # Add ip_address as nullable first so we can populate it
        migrations.AddField(
            model_name="device",
            name="ip_address",
            field=models.GenericIPAddressField(
                protocol="IPv4",
                null=True,
                blank=True,
                help_text="IPv4 address used to connect to the device.",
            ),
        ),
        # Copy existing hostname values (which were IPs) into ip_address
        migrations.RunPython(copy_hostname_to_ip_address, migrations.RunPython.noop),
        # Make ip_address not null and unique
        migrations.AlterField(
            model_name="device",
            name="ip_address",
            field=models.GenericIPAddressField(
                protocol="IPv4",
                unique=True,
                help_text="IPv4 address used to connect to the device.",
            ),
        ),
        # Make hostname optional (was unique + required)
        migrations.AlterField(
            model_name="device",
            name="hostname",
            field=models.CharField(
                max_length=255,
                blank=True,
                default="",
                help_text="Human-readable hostname of the device (optional).",
            ),
        ),
    ]
