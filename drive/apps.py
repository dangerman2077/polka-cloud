from django.apps import AppConfig

class DriveConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'drive'

    def ready(self):
        import drive.signals  # noqa: F401
