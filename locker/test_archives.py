from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile
from django.test import TestCase, override_settings
from .models import Student


class ArchiveTests(TestCase):
    def setUp(self):
        directory = self.enterContext(TemporaryDirectory())
        self.enterContext(override_settings(DATA=Path(directory)))
        user = Student.objects.create_user('reader', quota_mib=1)
        self.client.force_login(user)
        self.root = user.folder
        self.root.mkdir(parents=True, exist_ok=True)

    def extract(self, entries):
        with ZipFile(self.root/'Учёба.ZIP', 'w') as archive:
            for name, value in entries:
                archive.writestr(name, value)
        return self.client.post('/change/', {'action':'extract','name':'Учёба.ZIP'}, follow=True)

    def test_extract_and_collision(self):
        page = self.extract([('Сети/лекция.txt', b'abc'), ('empty/', b'')])
        self.assertEqual(page.context['path'], 'Учёба')
        self.assertEqual((self.root/'Учёба/Сети/лекция.txt').read_bytes(), b'abc')
        self.assertTrue((self.root/'Учёба/empty').is_dir())
        self.assertTrue((self.root/'Учёба.ZIP').exists())
        self.assertContains(self.extract([('new', b'')]), 'уже занято')
        self.assertFalse((self.root/'Учёба/new').exists())

    def test_bad_paths_and_quota_leave_no_partial_folder(self):
        for entries in [[('note',b'x'),('../bad', b'z')],[('big', b'0' * 1024**2)]]:
            self.extract(entries)
            self.assertFalse((self.root/'Учёба').exists())
            self.assertFalse((self.root/'bad').exists())
