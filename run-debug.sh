#!/bin/bash
echo "=> Waiting for DB to be online"
uv run python manage.py wait_for_database -s 2

echo "=> Performing database migrations..."
uv run python manage.py migrate

echo "=> Ensuring Superusers..."
uv run python manage.py ensureadmin

echo "=> Collecting Static.."
uv run python manage.py collectstatic --noinput

# Start the first process
echo "=> Starting Server"
uv run python manage.py runserver 0.0.0.0:80