import uuid
from django.contrib.auth.models import AbstractUser
from django.db import models, transaction
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.conf import settings


class Student(AbstractUser):
    vault = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    quota_mib = models.PositiveIntegerField('Квота, МиБ', default=1024)

    @property
    def folder(self):
        return settings.DATA / 'students' / self.vault.hex


@receiver(post_save, sender=Student)
def provision(sender, instance, created, **kwargs):
    if created:
        folder = instance.folder
        transaction.on_commit(lambda: folder.mkdir(parents=True, exist_ok=True, mode=0o700))
