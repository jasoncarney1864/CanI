import os
import psycopg

dsn = os.environ['POSTGRES_DSN']
with psycopg.connect(dsn) as conn:
    with conn.cursor() as cur:
        cur.execute(\"\"\"ALTER TABLE users ADD COLUMN IF NOT EXISTS display_name TEXT\"\"\")
        conn.commit()
        print('Migration 0003 applied successfully')
