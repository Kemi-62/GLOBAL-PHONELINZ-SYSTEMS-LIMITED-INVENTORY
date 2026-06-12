#!/bin/bash

# Build script for deployment

# Install requirements
pip install -r requirements.txt

# Run migrations
python manage.py migrate

# Collect static files
python manage.py collectstatic --noinput
