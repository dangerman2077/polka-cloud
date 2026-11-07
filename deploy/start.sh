#!/bin/sh
set -eu
python manage.py migrate --noinput
python manage.py collectstatic --noinput
exec gunicorn polka.wsgi:application --no-control-socket --bind 0.0.0.0:8000 --workers 1 --threads 8 --timeout 300 --access-logfile -
