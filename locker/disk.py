"""Filesystem rules shared by the HTTP and DAV entry points (Linux)."""
import fcntl
import os
import re
import shutil
import tempfile
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path
from django.conf import settings
from .models import Student


class DiskError(ValueError):
    pass


class Full(DiskError):
    pass


def filename(value):
    invalid = '<>:"/\\|?*'
    if (not value or value in ('.', '..') or value.endswith((' ', '.'))
        or len(value.encode()) > 240 or any(c in invalid or ord(c) < 32 for c in value)
        or re.match(r'^(con|aux|prn|nul|com[1-9]|lpt[1-9])(\.|$)', value, re.I)):
        raise DiskError('Недопустимое имя файла или папки.')
    return value


def locate(user, relative):
    folder = user.folder
    folder.mkdir(mode=0o700, exist_ok=True, parents=True)
    for part in relative.split('/') if relative else ():
        folder = folder / filename(part)
        if folder.is_symlink():
            raise DiskError('Символические ссылки запрещены.')
    return folder


@contextmanager
def exclusive(user):
    locks = settings.DATA/'locks'
    locks.mkdir(exist_ok=True)
    with (locks/user.vault.hex).open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def tally(folder):
    groups = defaultdict(lambda: [0, 0])
    for base, _, names in os.walk(folder):
        for name in names:
            path = Path(base)/name
            if path.is_symlink():
                continue
            try:
                size = path.stat().st_size
            except FileNotFoundError:
                continue
            row = groups[path.suffix.casefold() or 'Без расширения']
            row[0] += 1
            row[1] += size
    return groups


def volume(path):
    if path.is_file():
        return path.stat().st_size
    return sum(size for count, size in tally(path).values())


def budget(user):
    mib = Student.objects.values_list('quota_mib', flat=True).get(pk=user.pk)
    return mib * 1024**2 - volume(user.folder)


class Pending:
    """Write outside the visible tree and publish a complete file with rename."""
    def __init__(self, user, target, *, remaining=None):
        if not target.parent.is_dir() or target.is_dir():
            raise DiskError('Проверьте имя и папку назначения.')
        self.target = target
        self.remaining = max(0, budget(user) + volume(target)) if remaining is None else remaining
        stage = settings.DATA/'incoming'
        stage.mkdir(exist_ok=True)
        self.stream = tempfile.NamedTemporaryFile(dir=stage, delete=False)
        self.temp = Path(self.stream.name)

    def write(self, chunk):
        if len(chunk) > self.remaining:
            raise Full('Превышена личная квота.')
        self.remaining -= len(chunk)
        return self.stream.write(chunk)

    def close(self):
        self.stream.close()

    def finish(self, success):
        try:
            self.close()
            if success:
                os.replace(self.temp, self.target)
        finally:
            self.temp.unlink(missing_ok=True)


def remove(path):
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()
