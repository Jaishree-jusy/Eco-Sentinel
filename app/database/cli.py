"""
CLI for syncing the SQLite database from pipeline outputs.

Usage (from the eco-sentinel/ project root):

    python -m app.database.cli sync
"""

from app.database.sync import sync_database


def main():
    print("Syncing SQLite database from Module 6/7/8/9 outputs...")
    stats = sync_database()
    print("\nDatabase Sync SUCCESS")
    print(f"  alerts synced:   {stats['alerts_synced']}")
    print(f"  evidence synced: {stats['evidence_synced']}")
    print(f"  blocks synced:   {stats['blocks_synced']}")
    print("  database: db/eco_sentinel.db\n")


if __name__ == "__main__":
    main()
