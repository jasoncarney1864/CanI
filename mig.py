import os
import psycopg

try:
    conn = psycopg.connect(os.environ["POSTGRES_DSN"])
    conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS display_name TEXT")
    conn.commit()
    print("SUCCESS: display_name column added")
except Exception as e:
    print(f"ERROR: {e}")
