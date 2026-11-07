"""Manage Polka accounts without an interactive createsuperuser prompt."""
import re
import secrets
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from drive.models import StorageQuota


class Command(BaseCommand):
    help = 'Create accounts, reset passwords, and set per-user storage quotas.'

    def add_arguments(self, parser):
        actions = parser.add_subparsers(dest='action', required=True)

        create = actions.add_parser('create', help='Create a user and print a random password')
        create.add_argument('username')
        create.add_argument('--admin', action='store_true', help='Make a Django superuser')
        create.add_argument('--quota-mb', type=int, default=1024)

        password = actions.add_parser('password', help='Reset account password')
        password.add_argument('username')

        quota = actions.add_parser('quota', help='Set the storage quota in MiB')
        quota.add_argument('username')
        quota.add_argument('quota_mb', type=int)

    def handle(self, *args, **options):
        User = get_user_model()
        action = options['action']
        name = options['username']

        if action == 'create':
            if not re.fullmatch(r'[A-Za-z0-9_.@+-]{1,150}', name):
                raise CommandError('Имя: 1–150 символов, латиница, цифры, _ . @ + -')
            if options['quota_mb'] < 0:
                raise CommandError('Квота не может быть отрицательной')
            if User.objects.filter(username=name).exists():
                raise CommandError(f'Пользователь {name} уже существует')
            password = secrets.token_urlsafe(24)
            user = User.objects.create_user(username=name, password=password,
                                            is_staff=options['admin'],
                                            is_superuser=options['admin'])
            quota, _ = StorageQuota.objects.get_or_create(user=user)
            quota.quota_mb = options['quota_mb']
            quota.save(update_fields=['quota_mb'])
            self.stdout.write(f'Логин: {name}\nПароль: {password}\nКвота: {quota.quota_mb} МиБ')
            return

        try:
            user = User.objects.get(username=name)
        except User.DoesNotExist as exc:
            raise CommandError(f'Пользователь {name} не найден') from exc

        if action == 'password':
            password = secrets.token_urlsafe(24)
            user.set_password(password)
            user.save(update_fields=['password'])
            self.stdout.write(f'Логин: {name}\nНовый пароль: {password}')
        elif action == 'quota':
            if options['quota_mb'] < 0:
                raise CommandError('Квота не может быть отрицательной')
            quota, _ = StorageQuota.objects.get_or_create(user=user)
            quota.quota_mb = options['quota_mb']
            quota.save(update_fields=['quota_mb'])
            self.stdout.write(f'{name}: квота {quota.quota_mb} МиБ')
