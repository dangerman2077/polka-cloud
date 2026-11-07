from base64 import b64encode
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from wsgiref.util import setup_testing_defaults

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from drive.storage import root_for_user_id


@override_settings(POLKA_FORCE_SSL=False, SECURE_SSL_REDIRECT=False,
                   PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class IntegratedDriveTests(TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.enterContext(override_settings(POLKA_USERS_ROOT=root/'users',
                                            POLKA_STAGING_ROOT=root/'stage',
                                            POLKA_LOCK_ROOT=root/'locks'))
        self.user = get_user_model().objects.create_user('student', password='example')
        self.other = get_user_model().objects.create_user('second', password='example')
        self.client.force_login(self.user)
        from dav_app import application
        self.app = application

    def dav(self, method, path, body=b'', username='student', **headers):
        environ = {}
        setup_testing_defaults(environ)
        environ.update(REQUEST_METHOD=method, PATH_INFO=path.encode().decode('latin1'),
                       CONTENT_LENGTH=str(len(body)), HTTP_HOST='localhost', **headers)
        environ['wsgi.input'] = BytesIO(body)
        if username:
            token = b64encode(f'{username}:example'.encode()).decode()
            environ['HTTP_AUTHORIZATION'] = 'Basic ' + token
        status = []
        result = self.app(environ, lambda code, fields, exc_info=None: status.append(code))
        try:
            data = b''.join(result)
        finally:
            if hasattr(result, 'close'):
                result.close()
        return int(status[0][:3]), data

    def test_shared_files_statistics_and_isolation(self):
        self.assertEqual(self.dav('PROPFIND', '/', username=None)[0], 401)
        self.assertEqual(self.dav('MKCOL', '/лекции')[0], 201)
        self.assertEqual(self.dav('PUT', '/лекции/конспект.PDF', b'123')[0], 201)
        self.assertEqual(self.dav('GET', '/лекции/конспект.PDF', username='second')[0], 404)
        page = self.client.get('/statistics/')
        self.assertEqual(page.context['groups'], [
            {'extension': '.pdf', 'size': 3, 'count': 1, 'percent': 100}])
        download = self.client.get('/download/', {'path': 'лекции/конспект.PDF'})
        self.assertEqual(b''.join(download.streaming_content), b'123')
        self.client.post('/upload/', {'files': SimpleUploadedFile('hello.txt', b'abc')})
        self.assertEqual(self.dav('GET', '/hello.txt'), (200, b'abc'))
        code, xml = self.dav('PROPFIND', '/', HTTP_DEPTH='1')
        self.assertEqual(code, 207)
        self.assertIn(b'/dav/hello.txt', xml)
        for method, source, dest in [('COPY', '/hello.txt', 'copy.txt'), ('MOVE', '/copy.txt', 'new.txt')]:
            self.assertEqual(self.dav(method, source, HTTP_DESTINATION='http://localhost/dav/'+dest)[0], 201)
        self.assertEqual(self.dav('DELETE', '/new.txt')[0], 204)

    def test_shared_quota_keeps_original(self):
        quota = self.user.storage_quota
        quota.quota_mb = 1
        quota.save()
        payload = b'x' * (1024 * 1024)
        self.assertEqual(self.dav('PUT', '/тест.txt', payload)[0], 201)
        self.assertEqual(self.dav('PUT', '/тест.txt', b'y'+payload)[0], 507)
        self.assertEqual(self.dav('COPY', '/тест.txt', HTTP_DESTINATION='http://localhost/dav/copy')[0], 507)
        self.client.post('/upload/', {'files': SimpleUploadedFile('extra', b'z')})
        self.assertFalse((root_for_user_id(self.user.pk)/'extra').exists())
        self.assertEqual(self.dav('GET', '/тест.txt'), (200, payload))

    def test_browser_session_and_folder_actions(self):
        self.client.logout()
        self.assertEqual(self.client.get('/statistics/').status_code, 302)
        self.client.post('/accounts/login/', {'username': 'student', 'password': 'example'})
        self.client.post('/folder/', {'name': 'Семестр'})
        self.client.post('/upload/', {'path': 'Семестр', 'files': SimpleUploadedFile('one.pdf', b'pdf')})
        self.assertContains(self.client.get('/', {'path': 'Семестр'}), 'one.pdf')
        self.client.post('/rename/', {'current': 'Семестр/one.pdf', 'new_name': 'two.pdf'})
        self.assertEqual(self.dav('GET', '/Семестр/two.pdf'), (200, b'pdf'))
        self.client.post('/delete/', {'current': 'Семестр'})
        self.assertEqual(self.client.get('/statistics/').context['count'], 0)
