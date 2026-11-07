from base64 import b64encode
from unittest.mock import patch

from django.test import TestCase
from . import dav
from .models import Student


class AuthReuseTests(TestCase):
    def test_cache_reuses_success_and_revokes_on_reset_or_disable(self):
        user = Student.objects.create_user('speedcheck', password='before')
        def login(password):
            header = b64encode(('speedcheck:' + password).encode()).decode()
            return dav.identify({'HTTP_AUTHORIZATION': 'Basic ' + header})
        with patch.object(dav, 'authenticate', wraps=dav.authenticate) as verify:
            self.assertEqual(login('before'), user)
            self.assertEqual(login('before'), user)
            self.assertEqual(verify.call_count, 1)
            user.set_password('after')
            user.save()
            self.assertIsNone(login('before'))
            self.assertEqual(login('after'), user)
            user.is_active = False
            user.save()
            self.assertIsNone(login('after'))
