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

    def unpack_legacy(self, name, codec, choice='auto', extra=b''):
        from zipfile import ZipInfo
        raw = name.encode(codec)
        marker = 'X' * len(raw)
        path = self.root/'Учёба.ZIP'
        with ZipFile(path, 'w') as archive:
            member = ZipInfo(marker)
            member.extra = extra
            archive.writestr(member, b'content')
        data = path.read_bytes()
        self.assertEqual(data.count(marker.encode()), 2)
        path.write_bytes(data.replace(marker.encode(), raw))
        return self.client.post('/change/', {'action':'extract', 'name':path.name,
                                             'encoding':choice}, follow=True)

    def test_dos_names(self):
        name = 'Учёба/Лекции/Отчёт.txt'
        self.unpack_legacy(name, 'cp866')
        self.assertEqual((self.root/'Учёба'/name).read_bytes(), b'content')

    def test_windows_names(self):
        name = 'Лекции/Отчёт.txt'
        self.unpack_legacy(name, 'cp1251')
        self.assertTrue((self.root/'Учёба'/name).is_file())

    def test_ambiguous_name_with_manual_encoding(self):
        name = 'мама.txt'
        self.unpack_legacy(name, 'cp1251', 'cp1251')
        self.assertTrue((self.root/'Учёба'/name).is_file())

    def test_unflagged_utf8(self):
        name = 'Текст/файл.txt'
        self.unpack_legacy(name, 'utf-8')
        self.assertTrue((self.root/'Учёба'/name).is_file())

    def test_unicode_extra_field(self):
        import struct
        import zlib
        alias = 'TEXT.TXT'
        name = 'Учебник.txt'
        payload = struct.pack('<BI', 1, zlib.crc32(alias.encode())) + name.encode()
        extra = struct.pack('<HH', 0x7075, len(payload)) + payload
        self.unpack_legacy(alias, 'ascii', extra=extra)
        self.assertTrue((self.root/'Учёба'/name).is_file())
