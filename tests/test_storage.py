from tempfile import TemporaryDirectory
from pathlib import Path

from django.test import SimpleTestCase, override_settings
from drive.storage import UnsafePath, safe_user_path, sum_bytes, validate_name


class StorageBoundaryTests(SimpleTestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.override = override_settings(POLKA_USERS_ROOT=Path(self.tmp.name) / 'users')
        self.override.enable()
        self.addCleanup(self.override.disable)

    def test_accounts_have_separate_roots(self):
        one = safe_user_path(1, 'reports/note.txt')
        two = safe_user_path(2, 'reports/note.txt')
        self.assertNotEqual(one, two)
        self.assertEqual(one.parent.parent.name, '1')

    def test_dotdot_is_rejected(self):
        with self.assertRaises(UnsafePath):
            safe_user_path(1, '../2/secret.txt')

    def test_symlinks_are_rejected(self):
        root = safe_user_path(1, '')
        (root / 'link').symlink_to(Path(self.tmp.name))
        with self.assertRaises(UnsafePath):
            safe_user_path(1, 'link/secret.txt')

    def test_rejects_windows_reserved_filenames(self):
        for filename in ['CON.txt', 'file:abc', '../tmp', 'foo.', 'abc\\def']:
            with self.subTest(filename=filename):
                with self.assertRaises(UnsafePath):
                    validate_name(filename)

    def test_recursive_file_sizes(self):
        root = safe_user_path(1, '')
        folder = root / 'reports'
        folder.mkdir()
        (root / 'hello.txt').write_bytes(b'1234')
        (folder / 'other.txt').write_bytes(b'abc')
        self.assertEqual(sum_bytes(root), 7)
