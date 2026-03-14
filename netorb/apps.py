from django.apps import AppConfig


class NetorbConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "netorb"

    def ready(self):
        import netorb.signals  # noqa: F401
