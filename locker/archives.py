import lzma
import stat
import tempfile
import zlib
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from django.conf import settings

from .dav import allow_web_change
from .disk import DiskError, Full, budget, filename


def extract_archive(user, archive):
    """Caller holds the account write lock. Publish only after every entry succeeds."""
    if not archive.is_file() or archive.suffix.casefold() != '.zip':
        raise DiskError('Выберите ZIP-архив.')
    destination = archive.with_name(filename(archive.stem))
    if destination.exists() or destination.is_symlink():
        raise DiskError('Имя папки уже занято. Переименуйте архив или существующую папку.')
    allow_web_change(user, destination, membership=True)
    remaining = max(0, budget(user))
    stage = settings.DATA / 'incoming'
    stage.mkdir(exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(dir=stage) as tmp, ZipFile(archive) as zipped:
            entries = zipped.infolist()
            if len(entries) > 10000:
                raise DiskError('В архиве больше 10 000 объектов.')
            if sum(entry.file_size for entry in entries) > remaining:
                raise Full('Для распаковки недостаточно места в личном хранилище.')
            root = Path(tmp) / 'result'
            root.mkdir()
            for entry in entries:
                if entry.flag_bits & 1:
                    raise DiskError('Архивы с паролем пока не поддерживаются.')
                kind = stat.S_IFMT(entry.external_attr >> 16)
                if kind not in (0, stat.S_IFREG, stat.S_IFDIR):
                    raise DiskError('Архив содержит ссылку или специальный файл.')
                raw = entry.orig_filename.removesuffix('/') if entry.is_dir() else entry.orig_filename
                parts = raw.split('/')
                if len(parts) > 64:
                    raise DiskError('Слишком много уровней вложенности.')
                target = root.joinpath(*(filename(part) for part in parts))
                if entry.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with zipped.open(entry) as source, target.open('xb') as output:
                    while chunk := source.read(256 * 1024):
                        remaining -= len(chunk)
                        if remaining < 0:
                            raise Full('Исчерпана квота хранилища.')
                        output.write(chunk)
            root.rename(destination)
    except (BadZipFile, NotImplementedError, EOFError, zlib.error, lzma.LZMAError) as exc:
        raise DiskError('ZIP повреждён или использует неподдерживаемое сжатие.') from exc
    return destination
