"""
ROLLBACK CREATOR — run this BEFORE master_fix_all.py
=====================================================
Run: python /home/runner/workspace/create_rollback.py

This saves a snapshot of every file that master_fix_all.py will touch.
If anything breaks after the fix, run restore_rollback.py to go back.
"""
import os
import shutil
from datetime import datetime

WORKSPACE = '/home/runner/workspace'
TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
BACKUP_DIR = f'{WORKSPACE}/rollback_{TIMESTAMP}'

# Files that master_fix_all.py will modify
FILES_TO_BACKUP = [
    'core/views.py',
    'core/urls.py',
    'django_project/settings.py',
    'templates/partials/attendance_widget.html',
    'core/management/commands/stock_alert_email.py',
]

os.makedirs(BACKUP_DIR, exist_ok=True)

print(f"Creating rollback snapshot: {BACKUP_DIR}")
print("=" * 50)

backed_up = []
for rel_path in FILES_TO_BACKUP:
    src = f'{WORKSPACE}/{rel_path}'
    if os.path.exists(src):
        # Preserve folder structure inside backup dir
        dest_dir = os.path.join(BACKUP_DIR, os.path.dirname(rel_path))
        os.makedirs(dest_dir, exist_ok=True)
        dest = os.path.join(BACKUP_DIR, rel_path)
        shutil.copy2(src, dest)
        size = os.path.getsize(src) / 1024
        print(f"  Backed up: {rel_path} ({size:.1f} KB)")
        backed_up.append(rel_path)
    else:
        print(f"  SKIPPED (not found): {rel_path}")

# Write a restore script inside the backup folder
restore_script = f'''"""
RESTORE SCRIPT — restores files to the state before master_fix_all.py
======================================================================
Run: python /home/runner/workspace/rollback_{TIMESTAMP}/restore.py
"""
import os
import shutil

WORKSPACE = '/home/runner/workspace'
BACKUP_DIR = '/home/runner/workspace/rollback_{TIMESTAMP}'

FILES = {backed_up}

print("Restoring files to pre-fix state...")
for rel_path in FILES:
    src = os.path.join(BACKUP_DIR, rel_path)
    dest = os.path.join(WORKSPACE, rel_path)
    if os.path.exists(src):
        shutil.copy2(src, dest)
        print(f"  Restored: {{rel_path}}")
    else:
        print(f"  NOT FOUND in backup: {{rel_path}}")

print("\\nRollback complete. Restart your app:")
print("  python manage.py runserver 0.0.0.0:8000")
'''

restore_path = f'{BACKUP_DIR}/restore.py'
open(restore_path, 'w').write(restore_script)

print("=" * 50)
print(f"\nSnapshot saved to: rollback_{TIMESTAMP}/")
print(f"Files backed up: {len(backed_up)}/{len(FILES_TO_BACKUP)}")
print(f"\nIF ANYTHING BREAKS after the master fix, run:")
print(f"  python /home/runner/workspace/rollback_{TIMESTAMP}/restore.py")
print(f"\nThen restart:")
print(f"  python manage.py runserver 0.0.0.0:8000")
print(f"\nYou are now safe to run master_fix_all.py")
