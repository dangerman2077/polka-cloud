"""One authenticated DAV share per personal directory; no public filesystem provider."""
import base64
import binascii
import os
from contextlib import nullcontext
from threading import Lock
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

from django.conf import settings
from django.contrib.auth import authenticate
from django.core.handlers.wsgi import WSGIRequest
from django.core.exceptions import DisallowedHost
from django.db import close_old_connections
from wsgidav.dav_error import DAVError, get_http_status_string
from wsgidav.error_printer import ErrorPrinter
from wsgidav.fs_dav_provider import FilesystemProvider, FileResource, FolderResource
from wsgidav.request_resolver import RequestResolver
from wsgidav.wsgidav_app import WsgiDAVApp
from .disk import DiskError, Full, Pending, budget, exclusive, locate, volume

MUTATIONS = {'PUT', 'COPY', 'MOVE', 'DELETE', 'MKCOL', 'LOCK', 'UNLOCK', 'PROPPATCH'}


class UploadFile(FileResource):
    pending = None
    newly_created = False

    def begin_write(self, *, content_type=None):
        self.pending = Pending(self.environ['polka.student'], Path(self._file_path))
        return self

    def write(self, chunk):
        try:
            return self.pending.write(chunk)
        except Full as exc:
            raise DAVError(507, str(exc)) from exc

    def close(self):
        self.pending.close()

    def end_write(self, *, with_errors):
        length = self.environ.get('CONTENT_LENGTH')
        incomplete = (not with_errors and length and self.pending.temp.stat().st_size != int(length))
        try:
            if self.pending:
                self.pending.finish(not with_errors and not incomplete)
            if incomplete:
                raise DAVError(400, 'Неполная передача файла.')
            if not with_errors:
                self.file_stat = os.stat(self._file_path)
        except BaseException:
            with_errors = True
            raise
        finally:
            if with_errors and self.newly_created:
                Path(self._file_path).unlink(missing_ok=True)


class Folder(FolderResource):
    def create_empty_resource(self, name):
        resource = super().create_empty_resource(name)
        resource.newly_created = True
        return resource

    def get_used_bytes(self):
        return volume(self.environ['polka.student'].folder)

    def get_available_bytes(self):
        return max(0, budget(self.environ['polka.student']))


class PrivateTree(FilesystemProvider):
    def _loc_to_file_path(self, path, environ=None):
        try:
            return str(locate(environ['polka.student'], path.strip('/')))
        except DiskError as exc:
            raise DAVError(403, str(exc)) from exc

    def get_resource_inst(self, path, environ):
        physical = self._loc_to_file_path(path, environ)
        if os.path.isdir(physical):
            return Folder(path, environ, physical)
        if os.path.isfile(physical):
            return UploadFile(path, environ, physical)
        return None


# A single engine owns all WebDAV locks for each share within the worker.
_engines = {}
_engine_lock = Lock()


def engine(folder):
    with _engine_lock:
        if folder not in _engines:
            _engines[folder] = build_engine(folder)
        return _engines[folder]


def build_engine(folder):
    provider = PrivateTree(str(folder), fs_opts={'follow_symlinks': False})
    return WsgiDAVApp({'provider_mapping': {'/dav': provider}, 'lock_storage': True,
                       'middleware_stack': [ErrorPrinter, RequestResolver],
                       'property_manager': False, 'dir_browser': {'enable': False},
                       'verbose': 0, 'logging': {'enable': False}})


def allow_web_change(user, target, *, membership=False):
    """The browser owns no DAV lock tokens. Check source and collection membership."""
    manager = engine(user.folder).lock_manager
    paths = [target]
    if membership:
        paths.append(target.parent)
    for path in paths:
        rel = path.relative_to(user.folder).as_posix()
        url = '/dav/' + ('' if rel == '.' else quote(rel))
        if path.is_dir() and not url.endswith('/'):
            url += '/'
        try:
            manager.check_write_permission(url=url,
                depth='infinity' if path == target and path.is_dir() else '0',
                token_list=[], principal=user.username)
        except DAVError as exc:
            raise DiskError('Объект заблокирован клиентом WebDAV.') from exc


def identify(environ):
    kind, _, payload = environ.get('HTTP_AUTHORIZATION','').partition(' ')
    if kind.lower() != 'basic':
        return None
    try:
        credentials = base64.b64decode(payload, validate=True).decode('utf-8')
        name, password = credentials.split(':', 1)
    except (ValueError, binascii.Error, UnicodeError):
        return None
    return authenticate(username=name, password=password)


def verify_target(user, environ):
    method = environ['REQUEST_METHOD']
    # PEP 3333 transports raw UTF-8 path bytes in a Latin-1 string.
    path = environ['PATH_INFO'].encode('latin1').decode('utf8')
    source = locate(user, path[4:].strip('/'))
    if method in {'DELETE','MOVE','PUT'} and source == user.folder:
        raise DAVError(403)
    if method == 'PUT' and environ.get('CONTENT_LENGTH'):
        size = int(environ['CONTENT_LENGTH'])
        if size < 0:
            raise DAVError(400)
        if size > max(0, budget(user) + volume(source)):
            raise DAVError(507)
    if method in {'MOVE', 'COPY'}:
        dest = urlparse(unquote(environ.get('HTTP_DESTINATION','')), allow_fragments=False)
        if not dest.path.startswith('/dav/') or (dest.netloc and dest.netloc.lower() != environ['HTTP_HOST'].lower()):
            raise DAVError(403)
        target = locate(user, dest.path[5:].strip('/'))
        if target == user.folder or target in source.parents or source in target.parents:
            raise DAVError(403)
        if method == 'COPY':
            credit = volume(target) if target.is_file() else 0
            if volume(source) > budget(user) + credit:
                raise DAVError(507)


def reply(start, status, headers=()):
    start(status, list(headers) + [('Content-Length','0')])
    return [b'']


def serve(environ, start):
    close_old_connections()
    try:
        request = WSGIRequest(environ.copy())
        request.get_host()
        if not settings.DEBUG and not request.is_secure():
            yield from reply(start, '403 Forbidden')
            return
        if environ['REQUEST_METHOD'] == 'OPTIONS':
            yield from reply(start, '200 OK', [('DAV','1,2'), ('MS-Author-Via','DAV'),
                ('Allow','OPTIONS, HEAD, GET, PUT, DELETE, COPY, MOVE, PROPFIND, PROPPATCH, MKCOL, LOCK, UNLOCK')])
            return
        user = identify(environ)
        if user is None:
            yield from reply(start, '401 Unauthorized', [('WWW-Authenticate','Basic realm="Polka", charset="UTF-8"')])
            return
        environ['polka.student'] = user
        environ['wsgidav.auth.user_name'] = user.username
        mutating = environ['REQUEST_METHOD'] in MUTATIONS
        with exclusive(user) if mutating else nullcontext():
            if mutating:
                try:
                    verify_target(user, environ)
                except DAVError as exc:
                    yield from reply(start, get_http_status_string(exc.value))
                    return
                except (DiskError, ValueError):
                    yield from reply(start, '400 Bad Request')
                    return
            app = engine(locate(user, ''))
            yield from app(environ, start)
    except DisallowedHost:
        yield from reply(start, '400 Bad Request')
    finally:
        close_old_connections()
