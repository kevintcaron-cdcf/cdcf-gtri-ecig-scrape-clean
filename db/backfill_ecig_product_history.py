"""Seed baseline product-history snapshots for products scraped before history existed.

The script is resumable: it inserts only products with no history row, and
commits each batch separately. Re-run it after a network or database timeout.

Run from the repository root:
    python db/backfill_ecig_product_history.py

Use a smaller batch if Azure SQL is under load:
    python db/backfill_ecig_product_history.py --batch-size 50
"""

import argparse
import os
import sys
import time

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from db.db_azure import connect  # noqa: E402


HISTORY_FIELDS = (
    "product_name",
    "description",
    "site_category",
    "package_contents",
    "ingredients",
    "eliquid_contents",
    "puffs",
    "coil",
    "battery_text",
    "power_level",
    "nicotine_level_text",
    "stock_status",
    "features",
)


def ensure_history_index(cursor):
    """Make the missing-history lookup fast on the existing production table."""
    cursor.execute(
        """
        IF NOT EXISTS (
            SELECT 1
            FROM sys.indexes
            WHERE name = 'IX_ecig_product_history_product_date'
              AND object_id = OBJECT_ID(N'dbo.ecig_product_history')
        )
        CREATE INDEX IX_ecig_product_history_product_date
            ON dbo.ecig_product_history (product_id, date_inserted DESC);
        """
    )


def fetch_batch(cursor, batch_size):
    fields = ", ".join(f"ep.{field}" for field in HISTORY_FIELDS)
    cursor.execute(
        f"""
        SELECT TOP (?) ep.id, {fields}
        FROM dbo.ecig_product AS ep
        WHERE NOT EXISTS (
            SELECT 1
            FROM dbo.ecig_product_history AS h
            WHERE h.product_id = ep.id
        )
        ORDER BY ep.id;
        """,
        (batch_size,),
    )
    return cursor.fetchall()


def insert_batch(cursor, rows):
    fields = ", ".join(HISTORY_FIELDS)
    placeholders = ", ".join("?" for _ in HISTORY_FIELDS)
    cursor.fast_executemany = True
    cursor.executemany(
        f"""
        INSERT INTO dbo.ecig_product_history
            (product_id, changed_fields, {fields})
        VALUES (?, N'baseline', {placeholders});
        """,
        [tuple(row) for row in rows],
    )


def remaining_count(cursor):
    cursor.execute(
        """
        SELECT COUNT(*)
        FROM dbo.ecig_product AS ep
        WHERE NOT EXISTS (
            SELECT 1
            FROM dbo.ecig_product_history AS h
            WHERE h.product_id = ep.id
        );
        """
    )
    return cursor.fetchone()[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-size", type=int, default=100, help="Rows per committed batch (default: 100)")
    parser.add_argument("--pause", type=float, default=0.0, help="Seconds to wait between batches (default: 0)")
    args = parser.parse_args()
    if args.batch_size < 1:
        parser.error("--batch-size must be at least 1")

    connection = connect()
    cursor = connection.cursor()
    inserted = 0
    try:
        ensure_history_index(cursor)
        connection.commit()
        print("History lookup index is ready.")

        while True:
            rows = fetch_batch(cursor, args.batch_size)
            if not rows:
                break
            insert_batch(cursor, rows)
            connection.commit()
            inserted += len(rows)
            print(f"Inserted {inserted:,} baseline snapshots; {remaining_count(cursor):,} remain.")
            if args.pause:
                time.sleep(args.pause)
    except KeyboardInterrupt:
        connection.rollback()
        print(f"Stopped safely after {inserted:,} inserted snapshots. Re-run to resume.")
        return 130
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        connection.close()

    print(f"Complete. Inserted {inserted:,} baseline snapshots in this run.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
