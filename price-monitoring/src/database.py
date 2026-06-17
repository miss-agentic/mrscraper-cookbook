"""
Price History Database Module

Stores scraped price data in SQLite for historical analysis.
SQLite is chosen deliberately for this demo because:
  - Zero setup (no database server needed)
  - File-based (easy to persist in GitHub Actions via artifacts)
  - Perfectly adequate for price monitoring at moderate scale
  - In production, swap to PostgreSQL/TimescaleDB with zero code changes
    (just replace the connection string)
"""

import os
import json
import sqlite3
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DB_DIR = Path(os.environ.get("DB_DIR", "data"))
DB_PATH = DB_DIR / "prices.db"


def get_connection() -> sqlite3.Connection:
    """Get a database connection, creating the DB and tables if needed."""
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row  # Return dicts instead of tuples
    conn.execute("PRAGMA journal_mode=WAL")  # Better concurrent read performance
    _create_tables(conn)
    return conn


def _create_tables(conn: sqlite3.Connection) -> None:
    """Create tables if they don't exist."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS price_history (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            product_name TEXT NOT NULL,
            retailer    TEXT NOT NULL,
            category    TEXT NOT NULL DEFAULT 'general',
            current_price REAL NOT NULL,
            original_price REAL,
            currency    TEXT NOT NULL DEFAULT 'USD',
            in_stock    BOOLEAN DEFAULT 1,
            product_url TEXT,
            seller      TEXT,
            source_url  TEXT,
            scraped_at  TEXT NOT NULL,
            created_at  TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_price_history_product
            ON price_history(product_name, retailer);

        CREATE INDEX IF NOT EXISTS idx_price_history_scraped
            ON price_history(scraped_at);

        CREATE INDEX IF NOT EXISTS idx_price_history_category
            ON price_history(category);

        CREATE TABLE IF NOT EXISTS price_alerts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            product_name TEXT NOT NULL,
            retailer    TEXT NOT NULL,
            alert_type  TEXT NOT NULL,  -- 'price_drop', 'price_increase', 'back_in_stock', 'out_of_stock'
            old_price   REAL,
            new_price   REAL,
            pct_change  REAL,
            message     TEXT,
            created_at  TEXT NOT NULL DEFAULT (datetime('now')),
            notified    BOOLEAN DEFAULT 0
        );
    """)
    conn.commit()


def store_prices(products: list[dict]) -> int:
    """
    Store a batch of scraped products into the price history table.

    Args:
        products: List of product dicts from the scraper module.

    Returns:
        Number of rows inserted.
    """
    if not products:
        logger.warning("No products to store.")
        return 0

    conn = get_connection()
    cursor = conn.cursor()

    inserted = 0
    for p in products:
        try:
            cursor.execute(
                """
                INSERT INTO price_history
                    (product_name, retailer, category, current_price, original_price,
                     currency, in_stock, product_url, seller, source_url, scraped_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    p.get("product_name", "Unknown"),
                    p.get("retailer", "Unknown"),
                    p.get("category", "general"),
                    p.get("current_price", 0),
                    p.get("original_price"),
                    p.get("currency", "USD"),
                    p.get("in_stock", True),
                    p.get("product_url"),
                    p.get("seller"),
                    p.get("source_url"),
                    p.get("scraped_at", datetime.now(timezone.utc).isoformat()),
                ),
            )
            inserted += 1
        except sqlite3.Error as e:
            logger.error("Failed to insert product '%s': %s", p.get("product_name"), e)

    conn.commit()
    conn.close()
    logger.info("Stored %d/%d products in database.", inserted, len(products))
    return inserted


def detect_price_changes(threshold_pct: float = 5.0) -> list[dict]:
    """
    Compare the latest scrape with the previous scrape to detect
    significant price changes.

    This is the core intelligence that enterprise pricing teams rely on.
    Detects: price drops, price increases, and stock status changes.

    Args:
        threshold_pct: Minimum percentage change to trigger an alert.

    Returns:
        List of alert dictionaries with change details.
    """
    conn = get_connection()
    cursor = conn.cursor()

    # Find products where the latest price differs from the previous price
    # by more than the threshold percentage
    alerts = []

    cursor.execute("""
        WITH ranked AS (
            SELECT
                product_name,
                retailer,
                current_price,
                original_price,
                in_stock,
                scraped_at,
                ROW_NUMBER() OVER (
                    PARTITION BY product_name, retailer
                    ORDER BY scraped_at DESC
                ) as rn
            FROM price_history
        )
        SELECT
            curr.product_name,
            curr.retailer,
            curr.current_price AS new_price,
            prev.current_price AS old_price,
            curr.in_stock AS new_stock,
            prev.in_stock AS old_stock,
            curr.scraped_at AS new_scrape,
            prev.scraped_at AS old_scrape,
            CASE
                WHEN prev.current_price > 0
                THEN ROUND(((curr.current_price - prev.current_price) / prev.current_price) * 100, 2)
                ELSE 0
            END AS pct_change
        FROM ranked curr
        JOIN ranked prev
            ON curr.product_name = prev.product_name
            AND curr.retailer = prev.retailer
            AND curr.rn = 1
            AND prev.rn = 2
        WHERE ABS(
            CASE
                WHEN prev.current_price > 0
                THEN ((curr.current_price - prev.current_price) / prev.current_price) * 100
                ELSE 0
            END
        ) > ?
           OR (curr.in_stock != prev.in_stock)
    """, (threshold_pct,))

    for row in cursor.fetchall():
        pct = row["pct_change"]

        # Determine alert type
        if row["new_stock"] != row["old_stock"]:
            alert_type = "back_in_stock" if row["new_stock"] else "out_of_stock"
        elif pct < 0:
            alert_type = "price_drop"
        else:
            alert_type = "price_increase"

        # Build human-readable message
        if alert_type in ("price_drop", "price_increase"):
            direction = "dropped" if pct < 0 else "increased"
            message = (
                f"🏷️ {row['product_name']} ({row['retailer']}): "
                f"Price {direction} {abs(pct):.1f}% — "
                f"${row['old_price']:.2f} → ${row['new_price']:.2f}"
            )
        else:
            status = "back in stock" if alert_type == "back_in_stock" else "out of stock"
            message = (
                f"📦 {row['product_name']} ({row['retailer']}): "
                f"Now {status}"
            )

        alert = {
            "product_name": row["product_name"],
            "retailer": row["retailer"],
            "alert_type": alert_type,
            "old_price": row["old_price"],
            "new_price": row["new_price"],
            "pct_change": pct,
            "message": message,
        }
        alerts.append(alert)

        # Persist alert
        cursor.execute(
            """
            INSERT INTO price_alerts
                (product_name, retailer, alert_type, old_price, new_price, pct_change, message)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                alert["product_name"],
                alert["retailer"],
                alert["alert_type"],
                alert["old_price"],
                alert["new_price"],
                alert["pct_change"],
                alert["message"],
            ),
        )

    conn.commit()
    conn.close()

    logger.info("Detected %d price change alerts.", len(alerts))
    return alerts


def get_price_history(
    product_name: Optional[str] = None,
    retailer: Optional[str] = None,
    category: Optional[str] = None,
    days: int = 30,
) -> list[dict]:
    """
    Query historical price data with optional filters.

    Args:
        product_name: Filter by product name (partial match).
        retailer: Filter by retailer name.
        category: Filter by product category.
        days: Number of days of history to return.

    Returns:
        List of price history records.
    """
    conn = get_connection()
    cursor = conn.cursor()

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    query = "SELECT * FROM price_history WHERE scraped_at >= ?"
    params: list = [cutoff]

    if product_name:
        query += " AND product_name LIKE ?"
        params.append(f"%{product_name}%")
    if retailer:
        query += " AND retailer = ?"
        params.append(retailer)
    if category:
        query += " AND category = ?"
        params.append(category)

    query += " ORDER BY scraped_at DESC"

    cursor.execute(query, params)
    results = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return results


def get_latest_prices_by_retailer(category: Optional[str] = None) -> list[dict]:
    """
    Get the most recent price for each product at each retailer.
    Used for the comparison dashboard view.
    """
    conn = get_connection()
    cursor = conn.cursor()

    query = """
        SELECT
            ph.product_name,
            ph.retailer,
            ph.category,
            ph.current_price,
            ph.original_price,
            ph.currency,
            ph.in_stock,
            ph.scraped_at
        FROM price_history ph
        INNER JOIN (
            SELECT product_name, retailer, MAX(scraped_at) as max_scrape
            FROM price_history
            GROUP BY product_name, retailer
        ) latest
            ON ph.product_name = latest.product_name
            AND ph.retailer = latest.retailer
            AND ph.scraped_at = latest.max_scrape
    """

    params = []
    if category:
        query += " WHERE ph.category = ?"
        params.append(category)

    query += " ORDER BY ph.product_name, ph.retailer"

    cursor.execute(query, params)
    results = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return results


def get_summary_stats() -> dict:
    """Return high-level stats about the price database."""
    conn = get_connection()
    cursor = conn.cursor()

    stats = {}

    cursor.execute("SELECT COUNT(*) as cnt FROM price_history")
    stats["total_records"] = cursor.fetchone()["cnt"]

    cursor.execute("SELECT COUNT(DISTINCT product_name) as cnt FROM price_history")
    stats["unique_products"] = cursor.fetchone()["cnt"]

    cursor.execute("SELECT COUNT(DISTINCT retailer) as cnt FROM price_history")
    stats["retailers_tracked"] = cursor.fetchone()["cnt"]

    cursor.execute("SELECT MIN(scraped_at) as earliest, MAX(scraped_at) as latest FROM price_history")
    row = cursor.fetchone()
    stats["earliest_scrape"] = row["earliest"]
    stats["latest_scrape"] = row["latest"]

    cursor.execute("SELECT COUNT(*) as cnt FROM price_alerts WHERE created_at >= datetime('now', '-24 hours')")
    stats["alerts_24h"] = cursor.fetchone()["cnt"]

    conn.close()
    return stats
