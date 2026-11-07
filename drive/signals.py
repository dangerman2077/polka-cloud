from django.contrib.auth import get_user_model
from django.db.models.signals import post_save
from django.db import transaction
from .storage import root_for_user_id
from django.dispatch import receiver
from .models import StorageQuota

@receiver(post_save, sender=get_user_model())
def create_user_storage_quota(sender, instance, created, **kwargs):
    if created:
        StorageQuota.objects.get_or_create(user=instance)
        transaction.on_commit(lambda: root_for_user_id(instance.pk))
