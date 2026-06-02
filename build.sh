#!/usr/bin/env bash
# Build script for Render (also used for local deployment)

set -e

echo "==> Installing dependencies..."
pip install -r requirements.txt

echo "==> Collecting static files..."
python manage.py collectstatic --noinput

echo "==> Running migrations..."
python manage.py migrate

echo "==> Loading initial data (if available)..."
if [ -f "core/fixtures/initial_data.json" ]; then
    python manage.py loaddata core/fixtures/initial_data.json
fi

echo "==> Build complete!"
