"""
DEFINITIVE SUPABASE PASSWORD RESET - FIXED
Run with: python /home/runner/workspace/fix_supabase_passwords.py
"""
import os, sys, secrets, hashlib, base64

SUPABASE_URL = "postgresql://postgres.fnpjxcbraxkltdtaoiqq:Minak6462Gpsl@aws-0-eu-west-1.pooler.supabase.com:5432/postgres"
NEW_PASSWORD = "Password@123"

try:
    import psycopg2
except ImportError:
    os.system("pip install psycopg2-binary --break-system-packages -q")
    import psycopg2

def make_password(password):
    iterations = 720000
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), iterations)
    hash_b64 = base64.b64encode(dk).decode()
    return f"pbkdf2_sha256${iterations}${salt}${hash_b64}"

conn = psycopg2.connect(SUPABASE_URL)
cur = conn.cursor()
print("Connected to Supabase!")

# Check actual columns
cur.execute("""
    SELECT column_name FROM information_schema.columns
    WHERE table_name = 'core_user' ORDER BY ordinal_position;
""")
columns = [row[0] for row in cur.fetchall()]
print(f"Columns: {columns}")

# Detect column names
username_col = next((c for c in columns if 'username' in c.lower()), None)
role_col     = next((c for c in columns if c == 'role'), None)
locked_col   = next((c for c in columns if 'locked' in c.lower()), None)
fails_col    = next((c for c in columns if 'failed' in c.lower()), None)
password_col = next((c for c in columns if 'password' in c.lower()), None)
id_col       = 'id' if 'id' in columns else columns[0]

print(f"username={username_col} password={password_col} locked={locked_col} fails={fails_col}")

if not username_col or not password_col:
    print("Cannot find required columns. All columns:", columns)
    conn.close()
    sys.exit(1)

# Get users
select_cols = f"{id_col}, {username_col}"
if role_col:
    select_cols += f", {role_col}"
cur.execute(f"SELECT {select_cols} FROM core_user ORDER BY {id_col};")
users = cur.fetchall()
print(f"\nUsers found: {len(users)}")
for u in users:
    print(f"  {u}")

if not users:
    print("No users - run migrations and seed first.")
    conn.close()
    sys.exit(1)

# Build update SQL
new_hash = make_password(NEW_PASSWORD)
update_parts = ["password = %s"]
update_vals  = [new_hash]
if fails_col:
    update_parts.append(f"{fails_col} = 0")
if locked_col:
    update_parts.append(f"{locked_col} = false")

sql = f"UPDATE core_user SET {', '.join(update_parts)} WHERE {id_col} = %s"

print(f"\nResetting all to: {NEW_PASSWORD}")
count = 0
for u in users:
    try:
        cur.execute(sql, update_vals + [u[0]])
        count += 1
        print(f"  Reset: {u[1]}")
    except Exception as e:
        print(f"  Failed {u[1]}: {e}")
        conn.rollback()

conn.commit()
print(f"\nDone! {count}/{len(users)} reset.")
print(f"\nAll users password: {NEW_PASSWORD}")
cur.close()
conn.close()