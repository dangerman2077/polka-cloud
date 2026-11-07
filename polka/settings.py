import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get('POLKA_DATA', BASE_DIR / 'var')).resolve()
DATA.mkdir(exist_ok=True, parents=True)
DEBUG = os.environ.get('POLKA_DEV') == '1'
SECRET_KEY = os.environ.get('POLKA_SECRET') or ('local-test-only' if DEBUG else '')
if not SECRET_KEY:
    raise RuntimeError('Set POLKA_SECRET or enable local development with POLKA_DEV=1')
DOMAIN = os.environ.get('POLKA_DOMAIN', 'localhost')
ALLOWED_HOSTS = [DOMAIN] + (['127.0.0.1', 'testserver'] if DEBUG else [])
ROOT_URLCONF = 'polka.urls'
INSTALLED_APPS = ['django.contrib.admin', 'django.contrib.auth', 'django.contrib.contenttypes',
                  'django.contrib.sessions', 'django.contrib.messages', 'django.contrib.staticfiles', 'locker']
AUTH_USER_MODEL = 'locker.Student'
MIDDLEWARE = ['django.middleware.security.SecurityMiddleware', 'django.contrib.sessions.middleware.SessionMiddleware',
              'django.middleware.common.CommonMiddleware', 'django.middleware.csrf.CsrfViewMiddleware',
              'django.contrib.auth.middleware.AuthenticationMiddleware', 'django.contrib.messages.middleware.MessageMiddleware',
              'django.middleware.clickjacking.XFrameOptionsMiddleware']
TEMPLATES = [{'BACKEND': 'django.template.backends.django.DjangoTemplates', 'DIRS': [BASE_DIR/'templates'],
              'APP_DIRS': True, 'OPTIONS': {'context_processors': [
                  'django.template.context_processors.request','django.contrib.auth.context_processors.auth',
                  'django.contrib.messages.context_processors.messages']}}]
DATABASES = {'default': {'ENGINE':'django.db.backends.sqlite3','NAME': DATA/'accounts.sqlite3',
                          'OPTIONS': {'timeout': 20}}}
AUTH_PASSWORD_VALIDATORS = [{'NAME':'django.contrib.auth.password_validation.' + name} for name in
                           ('MinimumLengthValidator','CommonPasswordValidator','UserAttributeSimilarityValidator')]
LANGUAGE_CODE = 'ru'
TIME_ZONE = 'Europe/Moscow'
USE_TZ = True
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR/'public'
STATICFILES_DIRS = [BASE_DIR/'assets']
LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/login/'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = not DEBUG
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO','https')
