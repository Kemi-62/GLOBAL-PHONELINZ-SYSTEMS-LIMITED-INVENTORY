#!/usr/bin/env python3
"""
apply_cron_key_secret.py  --  SECURITY: stop putting the cron key in GitHub files.

Run from the project root (the folder with manage.py):   python apply_cron_key_secret.py

What it does (safe to run twice):
 1. Rewrites the 5 older workflows so they read the key from the GitHub secret
    CRON_KEY and send it in a header (not in the web address, so it also stays
    out of server logs):  daily_digest, stock_alert, whatsapp_report,
    monthly_archive, weekly_backup.
 2. weekly_backup.yml now also uploads each backup to Supabase Storage (needs the
    SUPABASE_URL / SUPABASE_KEY / SUPABASE_BUCKET settings on Render).
    It was calling /system/backup/, which does not exist in this
    app (the real route is /cron/backup/), so no backup was ever running. Fixed.
 3. Deletes fix_batch.py and fix_email.py (one-off helper scripts that print the
    old key) and removes the key from the email-test comment in core/views.py.
 4. Repairs .gitignore (the earlier line got glued onto '/result' so it did not
    work) so *.pre_*.bak files, backups/ (real database copies) and the
    data.json dumps stop being committed.
 5. Removes the root-level duplicate weekly_backup.yml / daily_digest.yml
    (copies that are not used by GitHub and reference old secret names).
"""
import os, re, sys

OLD = "gpsl2026backup"
MARK = "CRON_KEY_SECRET_V1"
WF = ".github/workflows"

if not os.path.exists("manage.py"):
    sys.exit("Run this from the project root (the folder that contains manage.py).")

def read(p):
    with open(p, encoding="utf-8") as f:
        return f.read()

def write(p, s):
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(s)

def step_block(name, url, maxtime, extra_before="", extra_after=""):
    return (
        "      - name: %s\n"
        "        env:\n"
        "          CRON_KEY: ${{ secrets.CRON_KEY }}\n"
        "        run: |\n"
        "          if [ -z \"$CRON_KEY\" ]; then\n"
        "            echo \"CRON_KEY secret is not set (GitHub repo > Settings > Secrets and variables > Actions)\"\n"
        "            exit 1\n"
        "          fi\n"
        "%s"
        "          curl -fsS --retry 2 --retry-delay 20 --retry-all-errors --max-time %d \\\n"
        "            -H \"X-Cron-Secret: $CRON_KEY\" \\\n"
        "            \"%s\"\n"
        "%s"
    ) % (name, extra_before, maxtime, url, extra_after)

HEAD = ("%s\nname: %s\n\non:\n  schedule:\n    - cron: '%s'\n  workflow_dispatch:\n\n"
        "jobs:\n  %s:\n    runs-on: ubuntu-latest\n    steps:\n"
        "      - name: Wake Render app\n        run: |\n"
        "          curl -s --max-time 60 \"https://app.globalphonelinz.com/system/keepalive/\" || true\n"
        "          sleep 15\n")

B = "https://app.globalphonelinz.com"
DIGEST_MAIL = "kemimonday00@gmail.com"

def build(marker, name, cron, job, steps):
    return HEAD % ("# " + marker, name, cron, job) + "".join(steps)

WORKFLOWS = {
    "daily_digest.yml": build(MARK, "GPSL Daily Digest", "0 18 * * 1-6", "daily-digest", [
        step_block("Send daily digest", B + "/cron/daily-digest/?email=" + DIGEST_MAIL, 120)]),
    "stock_alert.yml": build(MARK, "GPSL Stock Alert", "30 18 * * 1-6", "stock-alert", [
        step_block("Send stock and subscription alerts", B + "/cron/stock-alert/?email=" + DIGEST_MAIL, 120)]),
    "whatsapp_report.yml": build(MARK, "GPSL WhatsApp Report", "15 18 * * 1-6", "whatsapp-report", [
        step_block("Send WhatsApp report", B + "/cron/whatsapp-report/", 120)]),
    "monthly_archive.yml": build(MARK, "GPSL Monthly Performance Archive", "10 0 1 * *", "archive-monthly", [
        step_block("Archive previous month", B + "/cron/archive-monthly-performance/", 120),
        step_block("Archive + email staff performance", B + "/cron/archive-staff-monthly-performance/", 120)]),
    "weekly_backup.yml": build(MARK, "GPSL Weekly Backup", "30 17 * * 6", "weekly-backup", [
        step_block("Run weekly backup", B + "/cron/backup/?upload=true", 240)]),
}

# ---- 1/2. workflows
for fn, text in WORKFLOWS.items():
    p = os.path.join(WF, fn)
    if not os.path.exists(p):
        print("MISSING  %s (skipped)" % p); continue
    cur = read(p)
    if MARK in cur:
        print("SKIP     %s already applied" % p); continue
    bak = p + ".pre_cronkey.bak"
    if not os.path.exists(bak):
        write(bak, cur)
    write(p, text)
    print("APPLIED  %s" % p)

# ---- 3. one-off scripts + comment in views.py
for fn in ("fix_batch.py", "fix_email.py"):
    if os.path.exists(fn):
        os.remove(fn); print("APPLIED  deleted %s" % fn)
    else:
        print("SKIP     %s already gone" % fn)

v = "core/views.py"
if os.path.exists(v):
    s = read(v)
    if OLD in s:
        write(v + ".pre_cronkey.bak", s)
        s = s.replace("?key=" + OLD, "?key=YOUR_CRON_SECRET")
        write(v, s); print("APPLIED  removed old key from comment in %s" % v)
    else:
        print("SKIP     %s already clean" % v)

# ---- 4. .gitignore
g = ".gitignore"
gi = read(g) if os.path.exists(g) else ""
gi = gi.replace("/result-**.pre_*.bak", "/result-*")   # undo the glued line
need = ["*.pre_*.bak", "logs/", "*.sqlite3", ".env", "backups/", "data.json", "data.raw.json"]
lines = gi.splitlines()
added = []
for n in need:
    if n not in lines:
        lines.append(n); added.append(n)
new = "\n".join(lines).rstrip("\n") + "\n"
if new != gi:
    write(g, new); print("APPLIED  .gitignore fixed (added: %s)" % ", ".join(added) if added else "APPLIED  .gitignore repaired")
else:
    print("SKIP     .gitignore already fine")

# ---- 5. stray root copies
for fn in ("weekly_backup.yml", "daily_digest.yml"):
    if os.path.exists(fn):
        os.remove(fn); print("APPLIED  deleted stray copy ./%s" % fn)
    else:
        print("SKIP     ./%s already gone" % fn)

print("\nDone. Next, in the Shell:")
print("  git rm -r --cached --ignore-unmatch '*.pre_*.bak' backups data.json data.raw.json")
print("  git add -A && git commit -m 'Move cron key to GitHub secret; fix weekly backup route'")
print("  (then push with your token, as before)")