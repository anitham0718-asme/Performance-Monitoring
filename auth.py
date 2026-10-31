"""
auth.py
-------
Simple login system for the demo application.
- Users are stored in the 'users' table of production.db
- Passwords are stored as salted PBKDF2 hashes (never as plain text)
"""

import hashlib
import hmac
import os
import re
import sqlite3
from datetime import datetime

import pandas as pd

from database import get_connection

ITERATIONS = 200_000
ROLES = ["Admin", "Supervisor"]


def _hash_password(password, salt):
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, ITERATIONS
    ).hex()


def create_users_table():
    """Create the users table and add two demo users on first run."""
    try:
        with get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    salt TEXT NOT NULL,
                    role TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]

        if count == 0:
            add_user("admin", "Admin@123", "Admin")
            add_user("supervisor", "Super@123", "Supervisor")
    except sqlite3.Error as error:
        print(f"Database error in create_users_table: {error}")


def add_user(username, password, role):
    """Add a user. Returns (success, message)."""
    username = (username or "").strip().lower()

    if not re.fullmatch(r"[a-z0-9_]{3,30}", username):
        return False, "Username must be 3 to 30 characters: letters, numbers, underscore."
    if len(password or "") < 8:
        return False, "Password must be at least 8 characters."
    if role not in ROLES:
        return False, "Invalid role."

    salt = os.urandom(16)
    password_hash = _hash_password(password, salt)

    try:
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO users (username, password_hash, salt, role, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (username, password_hash, salt.hex(), role,
                 datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            )
        return True, f"User '{username}' created."
    except sqlite3.IntegrityError:
        return False, "That username already exists."
    except sqlite3.Error as error:
        return False, f"Database error: {error}"


def verify_user(username, password):
    """Return the user's role if the login is correct, otherwise None."""
    username = (username or "").strip().lower()
    if not username or not password:
        return None

    try:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT password_hash, salt, role FROM users WHERE username = ?",
                (username,),
            ).fetchone()
    except sqlite3.Error as error:
        print(f"Database error in verify_user: {error}")
        return None

    if row is None:
        # Do the same work anyway so response time doesn't reveal valid usernames
        _hash_password(password, b"0" * 16)
        return None

    stored_hash, salt_hex, role = row
    test_hash = _hash_password(password, bytes.fromhex(salt_hex))
    return role if hmac.compare_digest(test_hash, stored_hash) else None


def list_users():
    """All users (without password data) as a DataFrame."""
    try:
        with get_connection() as conn:
            return pd.read_sql_query(
                "SELECT username, role, created_at FROM users ORDER BY id", conn
            )
    except (sqlite3.Error, pd.errors.DatabaseError) as error:
        print(f"Database error in list_users: {error}")
        return pd.DataFrame()