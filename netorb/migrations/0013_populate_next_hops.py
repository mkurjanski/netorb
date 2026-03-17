from django.db import migrations


def copy_next_hops_to_array(apps, schema_editor):
    # Use raw SQL to avoid ORM name conflict: at this migration state IPv4Route
    # has both a next_hops ArrayField (added in 0012) and a reverse FK accessor
    # also named next_hops from the still-existing NextHop model.
    schema_editor.execute("""
        UPDATE netorb_ipv4route r
        SET next_hops = ARRAY(
            SELECT ip_address
            FROM netorb_nexthop
            WHERE route_id = r.id
        )
        WHERE EXISTS (
            SELECT 1 FROM netorb_nexthop WHERE route_id = r.id
        )
    """)


class Migration(migrations.Migration):

    dependencies = [
        ("netorb", "0012_ipv4route_next_hops"),
    ]

    operations = [
        migrations.RunPython(copy_next_hops_to_array, migrations.RunPython.noop),
    ]
