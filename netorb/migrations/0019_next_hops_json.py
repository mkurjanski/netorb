# Hand-written migration: convert next_hops from inet[] (ArrayField) to jsonb (JSONField).
# PostgreSQL cannot cast inet[] to jsonb directly, so we use raw SQL.

from django.db import migrations, models


def convert_column(apps, schema_editor):
    """Convert inet[] → jsonb with a text intermediary, then reshape data."""
    with schema_editor.connection.cursor() as cursor:
        for table in ("netorb_ipv4route", "netorb_ipv4routeevent"):
            # Step 1: add a temporary jsonb column
            cursor.execute(f'ALTER TABLE {table} ADD COLUMN next_hops_new jsonb DEFAULT \'[]\'::jsonb')
            # Step 2: copy data — convert each inet element to a {"nexthop": "...", "interface": ""} object
            # host(elem) strips the /32 mask that inet::text would add
            cursor.execute(f"""
                UPDATE {table}
                SET next_hops_new = COALESCE(
                    (SELECT jsonb_agg(jsonb_build_object('nexthop', host(elem), 'interface', ''))
                     FROM unnest(next_hops) AS elem),
                    '[]'::jsonb
                )
            """)
            # Step 3: drop old column and rename
            cursor.execute(f'ALTER TABLE {table} DROP COLUMN next_hops CASCADE')
            cursor.execute(f'ALTER TABLE {table} RENAME COLUMN next_hops_new TO next_hops')


class Migration(migrations.Migration):

    dependencies = [
        ('netorb', '0018_remove_interface_insert_insert_and_more'),
    ]

    operations = [
        migrations.RunPython(convert_column, migrations.RunPython.noop),
        # Tell Django the field is now JSONField (state-only, column already changed above)
        migrations.AlterField(
            model_name='ipv4route',
            name='next_hops',
            field=models.JSONField(blank=True, default=list, help_text='List of next-hop objects, e.g. [{"nexthop": "10.0.0.1", "interface": "Ethernet1"}].'),
        ),
        migrations.AlterField(
            model_name='ipv4routeevent',
            name='next_hops',
            field=models.JSONField(blank=True, default=list, help_text='List of next-hop objects, e.g. [{"nexthop": "10.0.0.1", "interface": "Ethernet1"}].'),
        ),
    ]
