from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("netorb", "0013_populate_next_hops"),
    ]

    operations = [
        migrations.DeleteModel(
            name="NextHop",
        ),
    ]
