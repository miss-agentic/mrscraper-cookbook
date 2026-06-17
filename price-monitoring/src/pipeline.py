"""
Price Monitor Pipeline — Main Orchestrator

This is the entry point that runs the full pipeline:
  1. Scrape prices from all configured retailers via MrScraper API
  2. Store results in the price history database
  3. Detect significant price changes
  4. Send alerts through configured channels

Designed to run as:
  - A GitHub Actions scheduled workflow (cron)
  - A standalone CLI script
  - Part of a larger data pipeline (importable)

Usage:
    python -m src.pipeline                     # Run full pipeline
    python -m src.pipeline --dry-run           # Scrape only, don't store/alert
    python -m src.pipeline --detect-only       # Skip scraping, just detect changes
    python -m src.pipeline --threshold 10      # Custom alert threshold (%)
"""

import argparse
import json
import logging
import sys
import time

from src.scraper import scrape_all_retailers, load_config
from src.database import store_prices, detect_price_changes, get_summary_stats
from src.alerts import send_alerts

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("pipeline")


def run_pipeline(
    dry_run: bool = False,
    detect_only: bool = False,
    threshold_pct: float = 5.0,
) -> dict:
    """
    Execute the full price monitoring pipeline.

    Args:
        dry_run: If True, scrape and print results but don't store or alert.
        detect_only: If True, skip scraping and just detect changes in existing data.
        threshold_pct: Minimum % change to trigger an alert.

    Returns:
        Pipeline execution summary dict.
    """
    start_time = time.time()
    summary = {
        "status": "success",
        "products_scraped": 0,
        "products_stored": 0,
        "alerts_detected": 0,
        "alerts_sent": {},
        "duration_seconds": 0,
    }

    try:
        # -----------------------------------------------------------
        # Step 0: Load and validate configuration
        # -----------------------------------------------------------
        config = load_config()
        retailers = config["retailers"]

        # -----------------------------------------------------------
        # Step 1: Scrape prices from retailers
        # -----------------------------------------------------------
        if not detect_only:
            logger.info("=" * 60)
            logger.info("STEP 1: Scraping prices from %d retailers...", len(retailers))
            logger.info("=" * 60)

            products = scrape_all_retailers(config)
            summary["products_scraped"] = len(products)

            if dry_run:
                logger.info("DRY RUN — printing results without storing:")
                print(json.dumps(products, indent=2, default=str))
                summary["duration_seconds"] = round(time.time() - start_time, 2)
                return summary

            # -----------------------------------------------------------
            # Step 2: Store in database
            # -----------------------------------------------------------
            logger.info("=" * 60)
            logger.info("STEP 2: Storing %d products in database...", len(products))
            logger.info("=" * 60)

            stored = store_prices(products)
            summary["products_stored"] = stored

        # -----------------------------------------------------------
        # Step 3: Detect price changes
        # -----------------------------------------------------------
        logger.info("=" * 60)
        logger.info("STEP 3: Detecting price changes (threshold=%.1f%%)...", threshold_pct)
        logger.info("=" * 60)

        alerts = detect_price_changes(threshold_pct=threshold_pct)
        summary["alerts_detected"] = len(alerts)

        # -----------------------------------------------------------
        # Step 4: Send alerts
        # -----------------------------------------------------------
        if alerts:
            logger.info("=" * 60)
            logger.info("STEP 4: Sending %d alerts...", len(alerts))
            logger.info("=" * 60)

            alert_summary = send_alerts(alerts)
            summary["alerts_sent"] = alert_summary
        else:
            logger.info("No significant price changes detected. No alerts to send.")

        # -----------------------------------------------------------
        # Summary
        # -----------------------------------------------------------
        stats = get_summary_stats()
        summary["database_stats"] = stats
        summary["duration_seconds"] = round(time.time() - start_time, 2)

        logger.info("=" * 60)
        logger.info("PIPELINE COMPLETE")
        logger.info("  Products scraped:  %d", summary["products_scraped"])
        logger.info("  Products stored:   %d", summary["products_stored"])
        logger.info("  Alerts detected:   %d", summary["alerts_detected"])
        logger.info("  Total DB records:  %d", stats.get("total_records", 0))
        logger.info("  Duration:          %.1fs", summary["duration_seconds"])
        logger.info("=" * 60)

    except Exception as e:
        summary["status"] = "error"
        summary["error"] = str(e)
        summary["duration_seconds"] = round(time.time() - start_time, 2)
        logger.exception("Pipeline failed: %s", e)
        raise

    return summary


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="MrScraper Enterprise Price Monitor Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m src.pipeline                   # Full pipeline run
  python -m src.pipeline --dry-run         # Test scraping without storing
  python -m src.pipeline --detect-only     # Only check for price changes
  python -m src.pipeline --threshold 10    # Alert on 10%+ changes only
        """,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Scrape and print results without storing or alerting.",
    )
    parser.add_argument(
        "--detect-only",
        action="store_true",
        help="Skip scraping, only detect changes in existing data.",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=5.0,
        help="Minimum price change percentage to trigger alerts (default: 5.0).",
    )

    args = parser.parse_args()

    summary = run_pipeline(
        dry_run=args.dry_run,
        detect_only=args.detect_only,
        threshold_pct=args.threshold,
    )

    # Exit with error code if pipeline failed
    if summary["status"] != "success":
        sys.exit(1)


if __name__ == "__main__":
    main()
