"""
database.py
-----------
All SQLite operations live here.
The existing table 'machine_readings' keeps the same columns,
so previously saved records are preserved.
"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

import pandas as pd

# Always the same file next to this script, whatever folder you run from
DB_NAME = str(Path(__file__).resolve().parent / "production.db")

COLUMN_MAP = {
    "Machine": "machine",
    "Timestamp": "timestamp",
    "Temperature": "temperature",
    "Vibration": "vibration",
    "Pressure": "pressure",
    "Units Produced": "units_produced",
    "Status": "status",
}
DB_COLUMNS = list(COLUMN_MAP.values())


@contextmanager
def get_connection():
    """Open a connection, commit on success, always close."""
    conn = sqlite3.connect(DB_NAME)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def create_table():
    """Create the table and indexes if they do not exist (keeps old data)."""
    try:
        with get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS machine_readings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    machine TEXT,
                    timestamp TEXT,
                    temperature REAL,
                    vibration REAL,
                    pressure REAL,
                    units_produced INTEGER,
                    status TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_readings_machine_time
                ON machine_readings (machine, timestamp)
            """)
        # Separate step: stops the same machine+timestamp being saved twice
        try:
            with get_connection() as conn:
                conn.execute("""
                    CREATE UNIQUE INDEX IF NOT EXISTS ux_readings_machine_time
                    ON machine_readings (machine, timestamp)
                """)
        except sqlite3.IntegrityError:
            print("Note: old duplicate rows exist, unique index not created.")
        return True
    except sqlite3.Error as error:
        print(f"Database error in create_table: {error}")
        return False


def save_readings(df):
    """Save a DataFrame of readings. Returns the number of NEW rows saved."""
    if df is None or df.empty:
        return 0

    try:
        data = df.rename(columns=COLUMN_MAP).copy()

        missing = [c for c in DB_COLUMNS if c not in data.columns]
        if missing:
            print(f"save_readings: missing columns {missing}")
            return 0

        data = data[DB_COLUMNS]
        data["timestamp"] = pd.to_datetime(data["timestamp"], errors="coerce")
        for col in ["temperature", "vibration", "pressure", "units_produced"]:
            data[col] = pd.to_numeric(data[col], errors="coerce")

        # Drop rows with invalid essential values
        data = data.dropna(subset=["machine", "timestamp", "temperature",
                                   "vibration", "pressure", "units_produced"])
        if data.empty:
            return 0

        data["timestamp"] = data["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S")
        data["units_produced"] = data["units_produced"].astype(int)
        rows = list(data.itertuples(index=False, name=None))

        with get_connection() as conn:
            before = conn.total_changes
            conn.executemany(
                """
                INSERT OR IGNORE INTO machine_readings
                (machine, timestamp, temperature, vibration,
                 pressure, units_produced, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            return conn.total_changes - before
    except sqlite3.Error as error:
        print(f"Database error in save_readings: {error}")
        return 0


def get_readings(machine=None, start=None, end=None, limit=None):
    """
    Get saved readings, newest first.
    machine: e.g. "M001" (None = all)
    start / end: "YYYY-MM-DD" or "YYYY-MM-DD HH:MM:SS"
    limit: maximum number of rows
    """
    query = "SELECT * FROM machine_readings WHERE 1=1"
    params = []

    if machine:
        query += " AND machine = ?"
        params.append(machine)
    if start:
        query += " AND timestamp >= ?"
        params.append(str(start))
    if end:
        end = str(end)
        if len(end) == 10:          # date only -> include the whole day
            end += " 23:59:59"
        query += " AND timestamp <= ?"
        params.append(end)

    query += " ORDER BY timestamp DESC, id DESC"
    if limit:
        query += " LIMIT ?"
        params.append(int(limit))

    try:
        with get_connection() as conn:
            return pd.read_sql_query(query, conn, params=params)
    except (sqlite3.Error, pd.errors.DatabaseError) as error:
        print(f"Database error in get_readings: {error}")
        return pd.DataFrame()


def get_latest_readings():
    """Latest saved reading for every machine."""
    query = """
        SELECT r.*
        FROM machine_readings r
        JOIN (SELECT machine, MAX(id) AS max_id
              FROM machine_readings GROUP BY machine) m
          ON r.id = m.max_id
        ORDER BY r.machine
    """
    try:
        with get_connection() as conn:
            return pd.read_sql_query(query, conn)
    except (sqlite3.Error, pd.errors.DatabaseError) as error:
        print(f"Database error in get_latest_readings: {error}")
        return pd.DataFrame()


def get_reading_count():
    """Total number of saved readings."""
    try:
        with get_connection() as conn:
            return conn.execute("SELECT COUNT(*) FROM machine_readings").fetchone()[0]
    except sqlite3.Error as error:
        print(f"Database error in get_reading_count: {error}")
        return 0