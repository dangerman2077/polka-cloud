from django.conf import settings
from django.db import models

class StorageQuota(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                related_name='storage_quota', verbose_name='Пользователь')
    quota_mb = models.PositiveIntegerField(default=1024, verbose_name='Лимит, МиБ',
                                            help_text='0 = запретить загрузку новых данных')

    class Meta:
        verbose_name = 'Квота хранилища'
        verbose_name_plural = 'Квоты хранилищ'

    @property
    def quota_bytes(self):
        return self.quota_mb * 1024 * 1024

    def __str__(self):
        return f'{self.user.username}: {self.quota_mb} МиБ'
