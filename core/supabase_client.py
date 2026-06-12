"""Supabase client for GPSL ERP.

This module is ONLY used when deployed to Render (production).
Replit stays with SQLite and does NOT use this.

Required env vars:
  SUPABASE_URL=https://your-project.supabase.co
  SUPABASE_KEY=your-service-role-key
  SUPABASE_BUCKET=your-bucket-name

Usage:
  from core.supabase_client import upload_file, download_file
  upload_file('/path/to/backup.db', folder='backups')
"""
import os
from django.conf import settings

# Lazy import — supabase-py is optional (only installed for Render)
try:
    from supabase import create_client
    _supabase = None
    _bucket = None

    def _get_client():
        global _supabase, _bucket
        if _supabase is None:
            url = os.environ.get("SUPABASE_URL") or getattr(settings, "SUPABASE_URL", "")
            key = os.environ.get("SUPABASE_KEY") or getattr(settings, "SUPABASE_KEY", "")
            if not url or not key:
                return None
            _supabase = create_client(url, key)
            _bucket = os.environ.get("SUPABASE_BUCKET") or getattr(settings, "SUPABASE_BUCKET", "gpsl-backups")
        return _supabase

    def upload_file(file_path, folder=""):
        """Upload a file to Supabase Storage. Returns {"ok": True, "path": ...} or {"ok": False, "error": ...}."""
        client = _get_client()
        if not client:
            return {"ok": False, "error": "Supabase not configured"}
        try:
            bucket_name = _bucket or "gpsl-backups"
            dest_path = f"{folder}/{os.path.basename(file_path)}" if folder else os.path.basename(file_path)
            with open(file_path, "rb") as f:
                client.storage.from_(bucket_name).upload(dest_path, f, file_options={"content-type": "application/octet-stream", "upsert": "true"})
            return {"ok": True, "path": dest_path}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def download_file(remote_path, local_path):
        """Download a file from Supabase Storage."""
        client = _get_client()
        if not client:
            return {"ok": False, "error": "Supabase not configured"}
        try:
            bucket_name = _bucket or "gpsl-backups"
            data = client.storage.from_(bucket_name).download(remote_path)
            with open(local_path, "wb") as f:
                f.write(data)
            return {"ok": True, "local_path": local_path}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def list_files(folder=""):
        """List files in a Supabase Storage folder."""
        client = _get_client()
        if not client:
            return {"ok": False, "error": "Supabase not configured"}
        try:
            bucket_name = _bucket or "gpsl-backups"
            result = client.storage.from_(bucket_name).list(folder)
            return {"ok": True, "files": result}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def is_configured():
        return _get_client() is not None

except ImportError:
    # supabase-py not installed — provide stubs
    def upload_file(file_path, folder=""):
        return {"ok": False, "error": "supabase-py not installed"}
    def download_file(remote_path, local_path):
        return {"ok": False, "error": "supabase-py not installed"}
    def list_files(folder=""):
        return {"ok": False, "error": "supabase-py not installed"}
    def is_configured():
        return False
