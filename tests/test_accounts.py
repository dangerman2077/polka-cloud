from io import StringIO
from django.contrib.auth import authenticate, get_user_model
from django.core.management import call_command
from django.test import TestCase
from drive.models import StorageQuota


class AccountManagementTests(TestCase):
    def test_create_and_change_quota(self):
        stdout = StringIO()
        call_command('account', 'create', 'test_user', '--quota-mb', '2048', stdout=stdout)
        user = get_user_model().objects.get(username='test_user')
        self.assertFalse(user.is_superuser)
        self.assertEqual(StorageQuota.objects.get(user=user).quota_mb, 2048)
        password = stdout.getvalue().split('Пароль: ')[1].splitlines()[0]
        self.assertIsNotNone(authenticate(username='test_user', password=password))

        call_command('account', 'quota', 'test_user', '5120', stdout=StringIO())
        self.assertEqual(StorageQuota.objects.get(user=user).quota_mb, 5120)

    def test_admin_and_reset_password(self):
        stdout = StringIO()
        call_command('account', 'create', 'admin_test', '--admin', stdout=stdout)
        user = get_user_model().objects.get(username='admin_test')
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)

        new_output = StringIO()
        call_command('account', 'password', 'admin_test', stdout=new_output)
        new_password = new_output.getvalue().split('Новый пароль: ')[1].splitlines()[0]
        self.assertIsNotNone(authenticate(username='admin_test', password=new_password))
