import os
import psycopg

conn = psycopg.connect(os.environ["POSTGRES_DSN"])
conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS display_name TEXT")
conn.commit()
print("Migration 0003 applied: display_name column added to users table")
