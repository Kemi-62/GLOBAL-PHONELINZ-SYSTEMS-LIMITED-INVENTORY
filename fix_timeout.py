"""
Fix cron-job.org timeout by making endpoints respond immediately
and run the actual work in a background thread.

Run: python /home/runner/workspace/fix_timeout.py
"""
VIEWS = '/home/runner/workspace/core/views.py'
code = open(VIEWS).read()

# Fix 1: daily_summary_trigger
old_trigger = '''def daily_summary_trigger(request):
    """Triggered by cron-job.org daily at 8pm to email director summary."""
    from django.http import JsonResponse as _JR
    from decouple import config as _cfg
    secret = request.GET.get("key", "")
    expected = _cfg("BACKUP_SECRET_KEY", default="")
    if expected and secret != expected:
        return _JR({"error": "unauthorized"}, status=403)
    try:
        result = send_daily_summary_email()
        return _JR(result)
    except Exception as e:
        return _JR({"status": "error", "detail": str(e)})'''

new_trigger = '''def daily_summary_trigger(request):
    """Triggered by cron-job.org daily at 8pm to email director summary.
    Responds immediately to avoid cron-job.org 30s timeout.
    Actual email runs in background thread.
    """
    from django.http import JsonResponse as _JR
    from decouple import config as _cfg
    import threading as _threading
    secret = request.GET.get("key", "")
    expected = _cfg("BACKUP_SECRET_KEY", default="")
    if expected and secret != expected:
        return _JR({"error": "unauthorized"}, status=403)
    def _run():
        try:
            send_daily_summary_email()
        except Exception:
            pass
    _threading.Thread(target=_run, daemon=True).start()
    return _JR({"status": "started", "message": "Daily digest running in background"})'''

if old_trigger in code:
    code = code.replace(old_trigger, new_trigger)
    print("Fixed: daily_summary_trigger")
elif 'def daily_summary_trigger' in code:
    # Try to patch whatever version exists
    import re
    code = re.sub(
        r'def daily_summary_trigger\(request\):.*?return _JR\(\{[^}]+\}\)',
        new_trigger,
        code,
        count=1,
        flags=re.DOTALL
    )
    print("Fixed: daily_summary_trigger (regex method)")
else:
    print("WARNING: daily_summary_trigger not found - add manually")

# Fix 2: any backup trigger view
old_backup = '''def trigger_backup(request):
    from django.http import JsonResponse
    from decouple import config as _config
    secret = request.GET.get('key', '')
    expected = _config('BACKUP_SECRET_KEY', default='')
    if expected and secret != expected:
        return JsonResponse({'error': 'unauthorized'}, status=403)
    try:
        import subprocess
        result = subprocess.Popen(
            ['python', '/opt/render/project/src/cron.py', 'backup'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        return JsonResponse({'status': 'backup started', 'pid': result.pid})
    except Exception as e:
        return JsonResponse({'status': 'error', 'detail': str(e)})'''

new_backup = '''def trigger_backup(request):
    """Responds immediately, runs backup in background to avoid timeout."""
    from django.http import JsonResponse
    from decouple import config as _config
    import threading as _threading
    import subprocess as _subprocess
    secret = request.GET.get('key', '')
    expected = _config('BACKUP_SECRET_KEY', default='')
    if expected and secret != expected:
        return JsonResponse({'error': 'unauthorized'}, status=403)
    def _run():
        try:
            _subprocess.run(
                ['python', '/opt/render/project/src/cron.py', 'backup'],
                timeout=300
            )
        except Exception:
            pass
    _threading.Thread(target=_run, daemon=True).start()
    return JsonResponse({'status': 'started', 'message': 'Backup running in background'})'''

if old_backup in code:
    code = code.replace(old_backup, new_backup)
    print("Fixed: trigger_backup")
elif 'def trigger_backup' in code:
    import re
    code = re.sub(
        r'def trigger_backup\(request\):.*?return JsonResponse\(\{[^}]+\}\)',
        new_backup,
        code,
        count=1,
        flags=re.DOTALL
    )
    print("Fixed: trigger_backup (regex method)")
else:
    print("trigger_backup not found - may not exist yet, skipping")

open(VIEWS, 'w').write(code)
print("\nDone. Now run:")
print("  python manage.py check")
print("  git add core/views.py && git commit -m 'Fix cron timeout - respond immediately' && git push")
