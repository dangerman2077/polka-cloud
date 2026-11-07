import os
from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'polka.settings')
site = get_wsgi_application()
from locker.dav import serve


def application(environ, start_response):
    path = environ.get('PATH_INFO', '')
    if path == '/dav' or path.startswith('/dav/') or (path == '/' and environ['REQUEST_METHOD'] == 'OPTIONS'):
        return serve(environ, start_response)
    return site(environ, start_response)
