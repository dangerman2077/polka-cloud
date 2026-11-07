import secrets
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from locker.models import Student


class Command(BaseCommand):
    help = 'Create the first admin for this installation.'

    @transaction.atomic
    def handle(self, **options):
        if Student.objects.filter(is_superuser=True, is_active=True).exists():
            self.stdout.write('Активный администратор уже существует.')
            return
        if Student.objects.filter(username='admin').exists():
            raise CommandError('Имя admin занято. Создайте администратора командой createsuperuser.')
        password = secrets.token_urlsafe(20)
        Student.objects.create_superuser('admin', password=password)
        self.stdout.write(f'Логин: admin\nПароль: {password}')
