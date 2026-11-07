"""Shared local filesystem utilities for both the Django UI and WebDAV.

All user roots are named by immutable numeric primary keys, not by usernames.
WebDAV and the Django UI use the same flock file to serialize quota mutations.
"""
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import re

from django.conf import settings
from .models import StorageQuota

WINDOWS_RESERVED = re.compile(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)', re.IGNORECASE)

class UnsafePath(ValueError):
    pass

class QuotaExceeded(ValueError):
    pass


def root_for_user_id(user_id):
    root = settings.POLKA_USERS_ROOT / str(int(user_id))
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    return root.resolve()


def validate_name(name):
    if not isinstance(name, str) or not name or name in {'.', '..'}:
        raise UnsafePath('Некорректное имя файла или папки.')
    if len(name) > 240 or name.endswith((' ', '.')) or WINDOWS_RESERVED.match(name):
        raise UnsafePath('Недопустимое имя для Windows.')
    if any(c in name for c in '/\\:*?"<>|') or any(ord(c) < 32 for c in name):
        raise UnsafePath('Имя содержит запрещённые символы.')
    return name


def safe_user_path(user_id, relative):
    root = root_for_user_id(user_id)
    relative = str(relative or '')
    if relative.startswith('/') or '\x00' in relative:
        raise UnsafePath('Недопустимый путь.')
    parts = [p for p in relative.split('/') if p]
    for p in parts:
        validate_name(p)
    target = root.joinpath(*parts)
    # Resolve symlinks and reject all links, including ones still inside the root.
    cursor = root
    for part in parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise UnsafePath('Символические ссылки не поддерживаются.')
    resolved = target.resolve(strict=False)
    if resolved != root and root not in resolved.parents:
        raise UnsafePath('Путь вне личного хранилища.')
    return target


def sum_bytes(path):
    path = Path(path)
    if path.is_symlink() or not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    total = 0
    for base, dirs, files in os.walk(path, followlinks=False):
        dirs[:] = [d for d in dirs if not (Path(base) / d).is_symlink()]
        for name in files:
            fp = Path(base) / name
            if not fp.is_symlink():
                try:
                    total += fp.stat().st_size
                except FileNotFoundError:
                    pass
    return total


def quota_bytes(user_id):
    quota, _ = StorageQuota.objects.get_or_create(user_id=user_id)
    return quota.quota_bytes


def quota_check(user_id, added_bytes):
    if sum_bytes(root_for_user_id(user_id)) + max(0, added_bytes) > quota_bytes(user_id):
        raise QuotaExceeded('Недостаточно места в личном хранилище.')


@contextmanager
def mutation_lock(user_id):
    settings.POLKA_LOCK_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_path = settings.POLKA_LOCK_ROOT / f'{int(user_id)}.lock'
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def file_statistics(root):
    """Summarize regular files across the account, including nested folders."""
    groups = {}
    for base, _, names in os.walk(root, followlinks=False):
        for name in names:
            path = Path(base) / name
            if path.is_symlink():
                continue
            try:
                size = path.stat().st_size
            except FileNotFoundError:
                continue
            extension = path.suffix.casefold() or 'Без расширения'
            group = groups.setdefault(extension, {'extension': extension, 'count': 0, 'size': 0})
            group['count'] += 1
            group['size'] += size
    return sorted(groups.values(), key=lambda g: (-g['size'], g['extension']))
