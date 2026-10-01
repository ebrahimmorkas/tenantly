#!/bin/sh
set -e

# Only the web container applies migrations; workers just wait for the app to be ready.
if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
    python manage.py migrate --noinput
fi

exec "$@"
