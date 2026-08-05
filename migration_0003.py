import os
import psycopg

c = psycopg.connect(os.environ["POSTGRES_DSN"])
c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS display_name TEXT")
c.commit()
print("Migration 0003 applied: display_name column added")
