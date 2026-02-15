#!/usr/bin/env python3
"""Nuke all users and tables. DESTRUCTIVE — use with caution.

Run: python scripts/nuke_db.py

Uses DATABASE_URL from .env. Truncates:
- All app tables (users + child tables via CASCADE)
- LangGraph checkpointer tables
"""
import asyncio
import sys

sys.path.insert(0, ".")

from sqlalchemy import text

from db.session import async_session


async def main():
    print("⚠️  Nuking all users and tables...")

    async with async_session() as session:
        # 1. Truncate users + all tables with FK to users (CASCADE)
        try:
            await session.execute(text('TRUNCATE TABLE users CASCADE'))
            print("   ✓ users (and all child tables: oauth_tokens, tasks, journal_entries, etc.)")
        except Exception as e:
            print(f"   ✗ users: {e}")

        # 2. Truncate LangGraph checkpointer tables
        lg_tables = ["checkpoint_writes", "checkpoint_blobs", "checkpoints", "checkpoint_migrations"]
        for table in lg_tables:
            try:
                await session.execute(text(f'TRUNCATE TABLE "{table}" CASCADE'))
                print(f"   ✓ {table}")
            except Exception as e:
                # Table might not exist if checkpointer never ran
                print(f"   - {table}: {e}")

        await session.commit()

    print("\nDone. All tables truncated.")


if __name__ == "__main__":
    asyncio.run(main())
