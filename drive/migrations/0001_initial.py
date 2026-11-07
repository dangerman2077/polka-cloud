from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    initial = True
    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.CreateModel(
            name='StorageQuota',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('quota_mb', models.PositiveIntegerField(default=1024, help_text='0 = запретить загрузку новых данных', verbose_name='Лимит, МиБ')),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='storage_quota', to=settings.AUTH_USER_MODEL, verbose_name='Пользователь')),
            ],
            options={'verbose_name': 'Квота хранилища', 'verbose_name_plural': 'Квоты хранилищ'},
        ),
    ]
