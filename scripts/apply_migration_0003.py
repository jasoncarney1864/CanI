#!/usr/bin/env python3
"""Apply migration 0003 - add display_name column to users table."""

import os
import psycopg

def main():
    dsn = os.environ.get("POSTGRES_DSN")
    if not dsn:
        print("ERROR: POSTGRES_DSN not set")
        return 1
    
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                ALTER TABLE users 
                ADD COLUMN IF NOT EXISTS display_name TEXT
            """)
            conn.commit()
            print("✓ Migration 0003 applied: display_name column added to users table")
    
    return 0

if __name__ == "__main__":
    exit(main())
