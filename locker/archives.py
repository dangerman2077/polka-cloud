import lzma
import stat
import tempfile
import zlib
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from django.conf import settings

from .dav import allow_web_change
from .disk import DiskError, Full, budget, filename


LEGACY_ENCODINGS = {'auto', 'cp866', 'cp1251', 'cp437'}


def archive_name(entry, encoding):
    original = entry.orig_filename
    if '\x00' in original:
        raise DiskError('В имени файла обнаружен нулевой байт.')
    # Python 3.12 applies a valid Info-ZIP Unicode Path field to filename.
    if entry.flag_bits & 0x800 or entry.filename != original:
        return entry.filename
    # Without a Unicode marker zipfile maps every original byte through CP437.
    raw = original.encode('cp437')
    if encoding != 'auto':
        return raw.decode(encoding)
    try:
        return raw.decode('utf-8')
    except UnicodeDecodeError:
        pass
    dos = raw.decode('cp866')
    try:
        windows = raw.decode('cp1251')
    except UnicodeDecodeError:
        return dos
    def russian_letters(name):
        return sum('А' <= ch <= 'я' or ch in 'Ёё' for ch in name)
    return max((dos, windows), key=russian_letters)


def extract_archive(user, archive, encoding='auto'):
    """Caller holds the account write lock. Publish only after every entry succeeds."""
    if encoding not in LEGACY_ENCODINGS:
        raise DiskError('Неизвестная кодировка имён файлов.')
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
                raw = archive_name(entry, encoding)
                if entry.is_dir():
                    raw = raw.removesuffix('/')
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
    except UnicodeError as exc:
        raise DiskError('Не удалось прочитать имя файла. Выберите другую кодировку имён ZIP.') from exc
    except (BadZipFile, NotImplementedError, EOFError, zlib.error, lzma.LZMAError) as exc:
        raise DiskError('ZIP повреждён или использует неподдерживаемое сжатие.') from exc
    return destination
