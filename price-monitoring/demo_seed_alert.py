"""
Demo Helper — Seed Price Change for Alert Demonstration

This script modifies one historical price record in the local database
so that the next pipeline run detects a "price change" and fires alerts.

USE CASE: Video demo / presentation where you need to show the alert
system working without waiting for a real-world price change.

Usage:
    py demo_seed_alert.py                    # Seed a $50 price drop on BestBuy
    py demo_seed_alert.py --retailer Walmart --delta -30
    py demo_seed_alert.py --reset            # Undo: delete seeded records

This script is NOT part of the production pipeline. It exists solely
for demonstration purposes.
"""

import argparse
import sqlite3
import sys
from pathlib import Path

DB_PATH = Path("data/prices.db")


def seed_price_change(retailer: str = "BestBuy", delta: float = -50.0):
    """
    Modify the most recent price record for a retailer to simulate
    a price change that the next pipeline run will detect.
    """
    if not DB_PATH.exists():
        print("❌ Database not found. Run the pipeline first: py -m src.pipeline")
        sys.exit(1)

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    # Find the most recent record for this retailer
    row = conn.execute(
        "SELECT id, product_name, current_price, retailer "
        "FROM price_history WHERE retailer = ? "
        "ORDER BY scraped_at DESC LIMIT 1",
        (retailer,),
    ).fetchone()

    if not row:
        print(f"❌ No records found for retailer '{retailer}'.")
        print("   Available retailers:")
        for r in conn.execute("SELECT DISTINCT retailer FROM price_history").fetchall():
            print(f"     - {r[0]}")
        conn.close()
        sys.exit(1)

    old_price = row["current_price"]
    new_price = old_price + delta

    # Update the price
    conn.execute(
        "UPDATE price_history SET current_price = ? WHERE id = ?",
        (new_price, row["id"]),
    )
    conn.commit()
    conn.close()

    direction = "drop" if delta < 0 else "increase"
    pct = abs(delta / old_price) * 100

    print(f"✅ Seeded price {direction} for demo:")
    print(f"   Product:  {row['product_name']}")
    print(f"   Retailer: {retailer}")
    print(f"   Price:    ${old_price:.2f} → ${new_price:.2f} ({pct:.1f}% {direction})")
    print()
    print(f"   Now run the pipeline to trigger the alert:")
    print(f"   py -m src.pipeline")


def reset_database():
    """Delete all records and start fresh."""
    if not DB_PATH.exists():
        print("No database to reset.")
        return

    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("DELETE FROM price_history")
    conn.execute("DELETE FROM price_alerts")
    conn.commit()
    conn.close()
    print("✅ Database reset. Run the pipeline twice to rebuild data.")


def show_status():
    """Show current database state."""
    if not DB_PATH.exists():
        print("No database found.")
        return

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    count = conn.execute("SELECT COUNT(*) as cnt FROM price_history").fetchone()["cnt"]
    alerts = conn.execute("SELECT COUNT(*) as cnt FROM price_alerts").fetchone()["cnt"]

    print(f"📊 Database Status:")
    print(f"   Total records: {count}")
    print(f"   Total alerts:  {alerts}")
    print()

    if count > 0:
        print("   Latest prices by retailer:")
        rows = conn.execute(
            "SELECT product_name, retailer, current_price, in_stock, scraped_at "
            "FROM price_history "
            "ORDER BY scraped_at DESC"
        ).fetchall()

        seen = set()
        for row in rows:
            key = (row["product_name"], row["retailer"])
            if key not in seen:
                seen.add(key)
                stock = "✅" if row["in_stock"] else "❌"
                print(f"   {stock} ${row['current_price']:>7.2f} | {row['retailer']:10s} | {row['product_name'][:50]}")

    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Demo helper for price alert demonstration")
    parser.add_argument("--retailer", default="BestBuy", help="Retailer to modify (default: BestBuy)")
    parser.add_argument("--delta", type=float, default=-50.0, help="Price change amount (negative=drop, default: -50)")
    parser.add_argument("--reset", action="store_true", help="Delete all data and start fresh")
    parser.add_argument("--status", action="store_true", help="Show current database state")

    args = parser.parse_args()

    if args.status:
        show_status()
    elif args.reset:
        reset_database()
    else:
        seed_price_change(retailer=args.retailer, delta=args.delta)