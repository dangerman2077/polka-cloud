import base64
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import quote
from wsgiref.util import setup_testing_defaults
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from .models import Student
from .disk import locate


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'], DEBUG=True)
class DriveTests(TestCase):
    def setUp(self):
        self.dir = self.enterContext(TemporaryDirectory())
        self.enterContext(override_settings(DATA=Path(self.dir)))
        self.user = Student.objects.create_user('alice', password='demo', quota_mib=1)
        Student.objects.create_user('bob', password='demo')
        self.client.force_login(self.user)

    def request(self, method, path='/dav', body=b'', who='alice', **headers):
        from polka.wsgi import application
        environ = {}
        setup_testing_defaults(environ)
        environ.update(PATH_INFO=path.encode().decode('latin1'), HTTP_HOST='testserver',
                       REQUEST_METHOD=method, CONTENT_LENGTH=str(len(body)))
        environ['wsgi.input'] = BytesIO(body)
        if who:
            environ['HTTP_AUTHORIZATION'] = 'Basic ' + base64.b64encode((who+':demo').encode()).decode()
        environ.update(headers)
        response = {}
        def start(status, fields, exc_info=None):
            response.update(status=int(status[:3]), fields=dict(fields))
        data = b''.join(application(environ, start))
        return response['status'], data, response['fields']

    def test_discovery(self):
        self.assertEqual(self.request('OPTIONS','/',who=None)[2]['DAV'], '1,2')
        self.assertEqual(self.request('PROPFIND',who=None)[0], 401)
        self.assertEqual(self.request('PROPFIND',HTTP_DEPTH='0')[0], 207)

    def test_roundtrip(self):
        self.assertEqual(self.request('MKCOL','/dav/Курс')[0],201)
        self.assertEqual(self.request('PUT','/dav/Курс/лекция.PDF',b'test')[0],201)
        self.assertContains(self.client.get('/',{'p':'Курс'}), 'лекция.PDF')
        self.assertEqual(self.client.get('/stats/').context['rows'],[('.pdf',1,4,100)])
        self.assertEqual(self.request('GET','/dav/Курс/лекция.PDF',who='bob')[0],404)
        self.client.post('/change/',{'action':'upload','file':SimpleUploadedFile('a.txt',b'hi')})
        self.assertEqual(self.request('GET','/dav/a.txt')[:2], (200,b'hi'))
        self.assertIn(b'/dav/a.txt',self.request('PROPFIND','/dav/',HTTP_DEPTH='1')[1])

    def test_copy_move_delete(self):
        self.request('PUT','/dav/один.txt',b'abc')
        for verb, old, new in [('COPY','один.txt','два.txt'),('MOVE','два.txt','три.txt')]:
            code = self.request(verb,'/dav/'+old,HTTP_DESTINATION='http://testserver/dav/'+quote(new))[0]
            self.assertEqual(code,201)
        self.assertEqual(self.request('GET','/dav/три.txt')[1],b'abc')
        self.assertEqual(self.request('DELETE','/dav/три.txt')[0],204)
        self.assertEqual(self.request('DELETE','/dav/')[0],403)

    def test_failed_writes_preserve_original(self):
        data = b'x' * (1024**2)
        self.assertEqual(self.request('PUT','/dav/full',data)[0],201)
        self.assertEqual(self.request('PUT','/dav/full',data+b'y')[0],507)
        self.assertEqual(self.request('COPY','/dav/full',HTTP_DESTINATION='http://testserver/dav/other')[0],507)
        self.client.post('/change/',{'action':'upload','file':SimpleUploadedFile('full',data+b'y')})
        self.assertEqual(self.request('GET','/dav/full')[1],data)
        self.assertEqual(self.request('PUT','/dav/full',b'a',CONTENT_LENGTH='3')[0],400)
        self.assertEqual(self.request('GET','/dav/full')[1],data)

    def test_names_and_accounts(self):
        self.assertEqual(self.request('PUT','/dav/CON',b'bad')[0],400)
        self.assertEqual(self.request('PUT','/dav/../other',b'bad')[0],400)
        locate(self.user,'link').symlink_to(Path(self.dir))
        self.assertEqual(self.request('GET','/dav/link/secret')[0],403)
        self.user.is_active=False
        self.user.save()
        self.assertEqual(self.request('PROPFIND')[0],401)

    def test_web_forms(self):
        self.client.post('/change/',{'action':'mkdir','name':'Семестр'})
        self.client.post('/change/',{'action':'rename','name':'Семестр','to':'Архив'})
        self.assertContains(self.client.get('/'), 'Архив')
        self.client.post('/change/',{'action':'delete','name':'Архив'})
        self.assertNotContains(self.client.get('/'), 'Архив')
        self.client.logout()
        self.assertEqual(self.client.get('/stats/').status_code,302)

    def test_dav_locks_are_personal(self):
        xml = b'<D:lockinfo xmlns:D="DAV:"><D:lockscope><D:exclusive/></D:lockscope><D:locktype><D:write/></D:locktype><D:owner>student</D:owner></D:lockinfo>'
        self.request('PUT','/dav/notes', b'first')
        code, _, headers = self.request('LOCK','/dav/notes',xml,CONTENT_TYPE='application/xml',
                                          HTTP_DEPTH='0',HTTP_TIMEOUT='Second-120')
        self.assertEqual(code,200)
        self.assertEqual(self.request('PUT','/dav/notes',b'second')[0],423)
        self.assertEqual(self.request('PUT','/dav/notes',b'private',who='bob')[0],201)
        self.client.post('/change/',{'action':'delete','name':'notes'})
        self.assertEqual(self.request('GET','/dav/notes')[1],b'first')
        token = next(v for k,v in headers.items() if k.lower()=='lock-token')
        self.assertEqual(self.request('UNLOCK','/dav/notes',HTTP_LOCK_TOKEN=token)[0],204)
        self.assertEqual(self.request('PUT','/dav/notes',b'second')[0],204)

    def test_admin_quota_and_directory(self):
        with self.captureOnCommitCallbacks(execute=True):
            member = Student.objects.create_user('new', password='demo')
        self.assertTrue(member.folder.is_dir())
        self.client.force_login(Student.objects.create_superuser('manager', password='demo'))
        page = self.client.get(f'/admin/locker/student/{member.pk}/change/')
        self.assertContains(page, 'name="quota_mib"')
        self.client.post(f'/admin/locker/student/{member.pk}/change/', {
            'username':'new', 'quota_mib':'0', 'is_active':'on',
            'date_joined_0':'2026-11-01','date_joined_1':'10:00:00','_save':'Save'})
        member.refresh_from_db()
        self.assertEqual(member.quota_mib,0)
        self.assertEqual(self.request('PUT','/dav/empty.txt',b'1',who='new')[0],507)

    def test_preview_and_download(self):
        import base64
        data = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=')
        self.request('PUT', '/dav/рисунок.PNG', data)
        for url, disposition in [('/view/', 'inline'), ('/download/', 'attachment')]:
            reply = self.client.get(url, {'p': 'рисунок.PNG'})
            self.assertEqual(reply.status_code, 200)
            self.assertEqual(reply['Content-Type'], 'image/png')
            self.assertTrue(reply['Content-Disposition'].startswith(disposition + ';'))
            self.assertEqual(b''.join(reply.streaming_content), data)
        self.request('PUT', '/dav/page.html', b'<script>alert(1)</script>')
        self.assertContains(self.client.get('/view/', {'p':'page.html'}), 'просмотр в браузере недоступен')
        self.client.force_login(Student.objects.get(username='bob'))
        self.assertEqual(self.client.get('/view/', {'p':'рисунок.PNG'}).status_code, 404)
