"""Password hashing and SQLite-backed user auth helpers.

Extracted verbatim from dashboard_server.py. verify_user_credentials and
register_user depend on WORKSPACE_DIR and on the live ADMIN_PASSWORD /
USER_PASSWORD module-level values in dashboard_server.py (tests monkeypatch
those after import, e.g. dashboard_server.ADMIN_PASSWORD = "testadmin"), so
dashboard_server is imported lazily inside each function -- never at module
load time -- to read the current values rather than a stale copy.
"""
import hashlib
import secrets
from datetime import datetime


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    pw_hash = hashlib.sha256((salt + password).encode('utf-8')).hexdigest()
    return f"{salt}:{pw_hash}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        salt, pw_hash = stored_hash.split(":", 1)
        calc_hash = hashlib.sha256((salt + password).encode('utf-8')).hexdigest()
        return secrets.compare_digest(calc_hash, pw_hash)
    except Exception:
        return False


def verify_user_credentials(email, password):
    import dashboard_server as ds
    from user_auth_db import db_path, ensure_users_schema
    import sqlite3

    ensure_users_schema(ds.WORKSPACE_DIR)
    db_file = db_path(ds.WORKSPACE_DIR)

    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    created_at = datetime.utcnow().isoformat()

    # Verify/Seed admin@hailmary.ai
    cursor.execute("SELECT password_hash FROM users WHERE email = ?", ("admin@hailmary.ai",))
    admin_row = cursor.fetchone()
    if not admin_row:
        admin_hash = hash_password(ds.ADMIN_PASSWORD)
        conn.execute("INSERT INTO users (email, password_hash, role, created_at) VALUES (?, ?, ?, ?)",
                     ("admin@hailmary.ai", admin_hash, "admin", created_at))
        conn.commit()
    elif not verify_password(ds.ADMIN_PASSWORD, admin_row["password_hash"]):
        admin_hash = hash_password(ds.ADMIN_PASSWORD)
        conn.execute("UPDATE users SET password_hash = ? WHERE email = ?", (admin_hash, "admin@hailmary.ai"))
        conn.commit()

    # Verify/Seed user@hailmary.ai
    cursor.execute("SELECT password_hash FROM users WHERE email = ?", ("user@hailmary.ai",))
    user_row = cursor.fetchone()
    if not user_row:
        user_hash = hash_password(ds.USER_PASSWORD)
        conn.execute("INSERT INTO users (email, password_hash, role, created_at) VALUES (?, ?, ?, ?)",
                     ("user@hailmary.ai", user_hash, "user", created_at))
        conn.commit()
    elif not verify_password(ds.USER_PASSWORD, user_row["password_hash"]):
        user_hash = hash_password(ds.USER_PASSWORD)
        conn.execute("UPDATE users SET password_hash = ? WHERE email = ?", (user_hash, "user@hailmary.ai"))
        conn.commit()

    cursor.execute("SELECT * FROM users WHERE email = ?", (email,))
    user = cursor.fetchone()
    conn.close()

    if user and verify_password(password, user["password_hash"]):
        return {"email": user["email"], "role": user["role"]}
    return None


def register_user(email, password, role="user"):
    import dashboard_server as ds
    from user_auth_db import db_path, ensure_users_schema
    import sqlite3

    ensure_users_schema(ds.WORKSPACE_DIR)
    db_file = db_path(ds.WORKSPACE_DIR)

    conn = sqlite3.connect(str(db_file))
    cursor = conn.cursor()

    cursor.execute("SELECT 1 FROM users WHERE email = ?", (email,))
    if cursor.fetchone():
        conn.close()
        return False, "Email already registered"

    pw_hash = hash_password(password)
    created_at = datetime.utcnow().isoformat()
    try:
        conn.execute("INSERT INTO users (email, password_hash, role, created_at) VALUES (?, ?, ?, ?)",
                     (email, pw_hash, role, created_at))
        conn.commit()
        conn.close()
        return True, "User registered successfully"
    except Exception as e:
        conn.close()
        return False, str(e)
