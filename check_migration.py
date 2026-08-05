import os
import psycopg

conn = psycopg.connect(os.environ["POSTGRES_DSN"])
result = conn.execute(
    "SELECT column_name FROM information_schema.columns "
    "WHERE table_name='users' AND column_name='display_name'"
).fetchone()

if result:
    print("SUCCESS: display_name column exists")
else:
    print("ERROR: display_name column not found")
