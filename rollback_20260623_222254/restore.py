"""
RESTORE SCRIPT — restores files to the state before master_fix_all.py
======================================================================
Run: python /home/runner/workspace/rollback_20260623_222254/restore.py
"""
import os
import shutil

WORKSPACE = '/home/runner/workspace'
BACKUP_DIR = '/home/runner/workspace/rollback_20260623_222254'

FILES = ['core/views.py', 'core/urls.py', 'django_project/settings.py', 'templates/partials/attendance_widget.html', 'core/management/commands/stock_alert_email.py']

print("Restoring files to pre-fix state...")
for rel_path in FILES:
    src = os.path.join(BACKUP_DIR, rel_path)
    dest = os.path.join(WORKSPACE, rel_path)
    if os.path.exists(src):
        shutil.copy2(src, dest)
        print(f"  Restored: {rel_path}")
    else:
        print(f"  NOT FOUND in backup: {rel_path}")

print("\nRollback complete. Restart your app:")
print("  python manage.py runserver 0.0.0.0:8000")
