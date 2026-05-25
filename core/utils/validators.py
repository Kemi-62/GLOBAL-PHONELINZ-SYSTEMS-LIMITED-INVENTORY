"""
File upload validators for security.
"""

import os
from django.core.exceptions import ValidationError
from django.conf import settings


# Allowed file extensions for uploads
ALLOWED_IMAGE_TYPES = {'jpg', 'jpeg', 'png'}
MAX_SELFIE_SIZE_MB = 5


def validate_selfie_file(file):
    """
    Validate selfie uploads:
    - Only images (jpg, jpeg, png)
    - Max 5MB
    - Filename sanitization
    """
    if not file:
        return

    # Check file size
    if file.size > MAX_SELFIE_SIZE_MB * 1024 * 1024:
        raise ValidationError(f"Selfie file too large. Maximum size is {MAX_SELFIE_SIZE_MB}MB.")

    # Check extension
    ext = os.path.splitext(file.name)[1].lower().lstrip('.')
    if ext not in ALLOWED_IMAGE_TYPES:
        raise ValidationError(
            f"Invalid file type '{ext}'. Only {', '.join(ALLOWED_IMAGE_TYPES)} are allowed."
        )

    # Sanitize filename (prevent path traversal)
    filename = os.path.basename(file.name)
    if '..' in filename or filename.startswith('/'):
        raise ValidationError("Invalid filename.")


def validate_csv_file(file):
    """
    Validate CSV uploads for bulk imports.
    - Only .csv extension
    - Max 2MB
    """
    if not file:
        return

    if file.size > 2 * 1024 * 1024:
        raise ValidationError("CSV file too large. Maximum size is 2MB.")

    ext = os.path.splitext(file.name)[1].lower()
    if ext != '.csv':
        raise ValidationError("Only .csv files are allowed.")

    filename = os.path.basename(file.name)
    if '..' in filename or filename.startswith('/'):
        raise ValidationError("Invalid filename.")
