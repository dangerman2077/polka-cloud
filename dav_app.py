"""Polka's standalone WsgiDAV WSGI application (gunicorn dav_app:application).

Nginx publishes /dav/; proxy_pass with a trailing slash strips this prefix.
The mount_path setting adds it back to generated WebDAV href values.
"""
import os
from pathlib import Path
import tempfile
from urllib.parse import unquote, urlparse

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'polka.settings')
import django
django.setup()

from django.contrib.auth import authenticate
from django.db import close_old_connections
from django.conf import settings
from wsgidav.mw.base_mw import BaseMiddleware
from wsgidav.error_printer import ErrorPrinter
from wsgidav.http_authenticator import HTTPAuthenticator
from wsgidav.request_resolver import RequestResolver
from wsgidav.wsgidav_app import WsgiDAVApp
from wsgidav.dc.base_dc import BaseDomainController
from wsgidav.fs_dav_provider import FilesystemProvider, FileResource, FolderResource
from wsgidav.dav_error import DAVError, HTTP_FORBIDDEN

from drive.storage import (QuotaExceeded, UnsafePath, mutation_lock, quota_bytes,
                           root_for_user_id, safe_user_path, sum_bytes)


class PolkaDomainController(BaseDomainController):
    """Use Django password hashes; never give clients anonymous storage."""
    def get_domain_realm(self, path_info, environ):
        return 'Polka'

    def require_authentication(self, realm, environ):
        return True

    def supports_http_digest_auth(self):
        return False

    def basic_auth_user(self, realm, user_name, password, environ):
        close_old_connections()
        try:
            user = authenticate(username=user_name, password=password)
            if user and user.is_active:
                environ['polka.uid'] = user.pk
                root_for_user_id(user.pk)
                return True
            return False
        finally:
            close_old_connections()


class IsolatedResourceMixin:
    """Lock and dead-property keys must not collide between two users."""
    def get_ref_url(self):
        return f'/users/{int(self.environ["polka.uid"])}' + super().get_ref_url()


class PolkaFile(IsolatedResourceMixin, FileResource):
    """Replace files atomically after a complete WebDAV PUT."""
    _staged_path = None

    def begin_write(self, *, content_type=None):
        if self.provider.readonly:
            raise DAVError(HTTP_FORBIDDEN)
        settings.POLKA_STAGING_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
        stream = tempfile.NamedTemporaryFile(mode='wb', prefix='dav-',
                                             dir=settings.POLKA_STAGING_ROOT, delete=False)
        self._staged_path = Path(stream.name)
        return stream

    def end_write(self, *, with_errors):
        if self._staged_path is None:
            return
        try:
            if with_errors and getattr(self, '_new_upload', False):
                Path(self._file_path).unlink(missing_ok=True)
            if not with_errors:
                if self._staged_path.stat().st_size != int(self.environ['CONTENT_LENGTH']):
                    if getattr(self, '_new_upload', False):
                        Path(self._file_path).unlink(missing_ok=True)
                    raise DAVError(400, 'Неполное тело запроса.')
                os.replace(self._staged_path, self._file_path)
                self.file_stat = os.stat(self._file_path)
        finally:
            self._staged_path.unlink(missing_ok=True)
            self._staged_path = None


class PolkaFolder(IsolatedResourceMixin, FolderResource):
    def create_empty_resource(self, name):
        resource = super().create_empty_resource(name)
        resource._new_upload = True
        return resource

    def get_used_bytes(self):
        return sum_bytes(root_for_user_id(self.environ['polka.uid']))

    def get_available_bytes(self):
        user_id = self.environ['polka.uid']
        return max(0, quota_bytes(user_id) - self.get_used_bytes())


class PolkaProvider(FilesystemProvider):
    """Per-user chroot: provider never changes global root_folder_path."""
    def ref_url_to_path(self, ref_url):
        # Reverse the account prefix added by IsolatedResourceMixin for lock discovery.
        return super().ref_url_to_path('/' + ref_url.split('/', 3)[3])

    def _loc_to_file_path(self, path, environ=None):
        if environ is None or 'polka.uid' not in environ:
            raise DAVError(HTTP_FORBIDDEN)
        try:
            # WsgiDAV supplies a resource-relative path, without the /dav prefix.
            return str(safe_user_path(environ['polka.uid'], path.lstrip('/')))
        except UnsafePath as exc:
            raise DAVError(HTTP_FORBIDDEN, str(exc)) from exc

    def get_resource_inst(self, path, environ):
        self._count_get_resource_inst += 1
        physical = self._loc_to_file_path(path, environ)
        if not os.path.exists(physical):
            return None
        if os.path.islink(physical):
            raise DAVError(HTTP_FORBIDDEN)
        if os.path.isdir(physical):
            return PolkaFolder(path, environ, physical)
        if os.path.isfile(physical):
            return PolkaFile(path, environ, physical)
        return None


def relative_dav_path(url_path):
    """Nginx already strips /dav/ from PATH_INFO, not from Destination."""
    return url_path.lstrip('/')


def destination_relative(environ):
    destination = environ.get('HTTP_DESTINATION')
    if not destination:
        raise UnsafePath('Destination header отсутствует.')
    parsed = urlparse(unquote(destination), allow_fragments=False)
    host = environ.get('HTTP_X_FORWARDED_HOST') or environ.get('HTTP_HOST', '')
    if parsed.netloc and parsed.netloc.lower() != host.lower():
        raise UnsafePath('Перемещение в другое хранилище запрещено.')
    path = parsed.path
    if not path.startswith('/dav/'):
        raise UnsafePath('Destination должен начинаться с /dav/.')
    return path[len('/dav/'):]


class QuotaGate(BaseMiddleware):
    """Lock concurrent web/DAV mutations and reject PUT/COPY above a user's quota.

    Always require a known Content-Length on PUT, so the predicted byte count
    is enforceable. 507 communicates insufficient storage to WebDAV clients.
    """
    METHODS = frozenset({'PUT', 'COPY', 'MOVE', 'MKCOL', 'DELETE'})

    def preflight(self, environ, user_id):
        method = environ['REQUEST_METHOD'].upper()
        source = safe_user_path(user_id, relative_dav_path(environ.get('PATH_INFO', '/')))
        if method in {'MOVE', 'DELETE'} and source == root_for_user_id(user_id):
            return '403 Forbidden', 'Корневую папку нельзя удалить или переместить.'
        if method == 'PUT':
            content_length = environ.get('CONTENT_LENGTH', '')
            if not content_length.isdigit():
                return '411 Length Required', 'Нужен заголовок Content-Length.'
            size = int(content_length)
            if size < 0:
                return '400 Bad Request', 'Некорректный Content-Length.'
            if source.is_dir():
                return None
            existing = source.stat().st_size if source.is_file() else 0
            if sum_bytes(root_for_user_id(user_id)) - existing + size > quota_bytes(user_id):
                raise QuotaExceeded('Квота Polka исчерпана.')
        elif method in {'MOVE', 'COPY'}:
            dest = safe_user_path(user_id, destination_relative(environ))
            if dest == root_for_user_id(user_id):
                return '403 Forbidden', 'Замена корневой папки запрещена.'
            if method == 'MOVE':
                return None
            src_size = sum_bytes(source)
            dst_size = sum_bytes(dest)
            if sum_bytes(root_for_user_id(user_id)) - dst_size + src_size > quota_bytes(user_id):
                raise QuotaExceeded('Недостаточно места для копирования.')
        return None

    def __call__(self, environ, start_response):
        method = environ.get('REQUEST_METHOD', '').upper()
        close_old_connections()
        try:
            if method not in self.METHODS:
                yield from self.next_app(environ, start_response)
                return
            user_id = environ['polka.uid']
            with mutation_lock(user_id):
                try:
                    failure = self.preflight(environ, user_id)
                except QuotaExceeded as exc:
                    failure = ('507 Insufficient Storage', str(exc))
                except UnsafePath as exc:
                    failure = ('403 Forbidden', str(exc))
                if failure:
                    status, body_text = failure
                    body = body_text.encode('utf-8')
                    start_response(status, [
                        ('Content-Type', 'text/plain; charset=utf-8'),
                        ('Content-Length', str(len(body))),
                        ('Cache-Control', 'no-store'),
                    ])
                    yield body
                    return
                app_iter = self.next_app(environ, start_response)
                try:
                    yield from app_iter
                finally:
                    if hasattr(app_iter, 'close'):
                        app_iter.close()
        finally:
            close_old_connections()


# This DAV service must run with exactly 1 Gunicorn worker; WsgiDAV's locks
# are in process memory. Threads within one worker share the lock manager.
settings.POLKA_USERS_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
provider = PolkaProvider(str(settings.POLKA_USERS_ROOT), fs_opts={'follow_symlinks': False})
application = WsgiDAVApp({
    'middleware_stack': [ErrorPrinter, HTTPAuthenticator, QuotaGate, RequestResolver],
    'mount_path': '/dav',
    'provider_mapping': {'/': provider},
    'dir_browser': {'enable': False},
    'http_authenticator': {
        'domain_controller': PolkaDomainController,
        'accept_basic': True,
        'accept_digest': False,
        'default_to_digest': False,
    },
    'lock_storage': True,
    'property_manager': False,
    'verbose': 2,
    'logging': {'enable': False},
    'fs_dav_provider': {'follow_symlinks': False},
})
