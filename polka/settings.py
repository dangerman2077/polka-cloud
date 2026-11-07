"""Settings for the Polka web storage service."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

def env_flag(name, default='0'):
    return os.environ.get(name, default).strip().lower() in {'1', 'true', 'yes', 'on'}

DEBUG = env_flag('POLKA_DEBUG')
SECRET_KEY = os.environ.get('POLKA_SECRET_KEY', 'unsafe-development-key-not-for-production')
if not DEBUG and SECRET_KEY == 'unsafe-development-key-not-for-production':
    raise RuntimeError('Set POLKA_SECRET_KEY before starting Polka in production')
ALLOWED_HOSTS = [h.strip() for h in os.environ.get('POLKA_ALLOWED_HOSTS', '127.0.0.1,localhost').split(',') if h.strip()]
CSRF_TRUSTED_ORIGINS = [h.strip() for h in os.environ.get('POLKA_CSRF_ORIGINS', '').split(',') if h.strip()]
POLKA_DATA_ROOT = Path(os.environ.get('POLKA_DATA_ROOT', str(BASE_DIR / 'data'))).expanduser().resolve()
POLKA_USERS_ROOT = POLKA_DATA_ROOT / 'users'
POLKA_STAGING_ROOT = POLKA_DATA_ROOT / '.staging'
POLKA_LOCK_ROOT = POLKA_DATA_ROOT / '.locks'

INSTALLED_APPS = [
    'django.contrib.admin', 'django.contrib.auth', 'django.contrib.contenttypes',
    'django.contrib.sessions', 'django.contrib.messages', 'django.contrib.staticfiles',
    'drive.apps.DriveConfig',
]
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]
ROOT_URLCONF = 'polka.urls'
TEMPLATES = [{'BACKEND': 'django.template.backends.django.DjangoTemplates',
              'DIRS': [BASE_DIR / 'templates'], 'APP_DIRS': True,
              'OPTIONS': {'context_processors': [
                  'django.template.context_processors.debug',
                  'django.template.context_processors.request',
                  'django.contrib.auth.context_processors.auth',
                  'django.contrib.messages.context_processors.messages',
              ]}}]
WSGI_APPLICATION = 'polka.wsgi.application'
DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3',
                         'NAME': os.environ.get('POLKA_DB_PATH', str(POLKA_DATA_ROOT / 'db.sqlite3')),
                         'OPTIONS': {'timeout': 30}}}
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]
LANGUAGE_CODE = 'ru-ru'
TIME_ZONE = 'Europe/Moscow'
USE_I18N = True
USE_TZ = True
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'drive:index'
LOGOUT_REDIRECT_URL = 'login'
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
FORCE_SSL = env_flag('POLKA_FORCE_SSL', '1')
SESSION_COOKIE_SECURE = FORCE_SSL
CSRF_COOKIE_SECURE = FORCE_SSL
SECURE_SSL_REDIRECT = FORCE_SSL
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
X_FRAME_OPTIONS = 'DENY'
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'same-origin'
