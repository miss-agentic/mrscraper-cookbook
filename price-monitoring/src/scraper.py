"""
MrScraper Price Extraction Module  (cookbook recipe: price-monitoring)

Extracts structured price data from product pages using MrScraper's
create-and-run API — the same call the Playground "Run" button makes.
No dashboard scraper setup, no scraper IDs: you give it a URL and a
plain-English field list, and it returns clean JSON.

One product per URL (General Agent). Tracks the same product across
retailers (e.g. Amazon, Best Buy, Walmart) to detect price drops,
increases, and stock changes.

Migration note: earlier versions used the Scraper Rerun API
(/scrapers-ai-rerun) with a pre-configured scraper ID from the
dashboard. That path is deprecated. This module calls create-and-run
per URL instead, so there is nothing to set up in a dashboard.
"""

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from mrscraper import MrScraper
from mrscraper.exceptions import AuthenticationError, APIError, NetworkError

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MRSCRAPER_API_TOKEN = os.environ.get("MRSCRAPER_API_TOKEN", "")
CONFIG_PATH = Path(os.environ.get("CONFIG_PATH", "config.json"))

# Fallback field set if config.json omits "fields". The keys here are what
# the normalizer below understands; edit descriptions to tune extraction.
DEFAULT_FIELDS = {
    "product_name": "the product title",
    "current_price": "number, digits only — the current selling price after any discount",
    "original_price": "number, digits only — the list/strikethrough price before discount; null if none",
    "currency": "the currency code shown, e.g. USD; null if not shown",
    "in_stock": "true if the product can be purchased now, false if sold out or unavailable",
    "product_url": "the canonical URL of this product page",
    "seller": "the seller or retailer name if shown; null otherwise",
}


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------
def build_prompt(config: dict) -> str:
    """Build the strict-JSON extraction prompt from the config field list.

    The prompt replaces the dashboard scraper's saved prompt: it now lives
    in version control, so a change is a reviewable diff.
    """
    fields = config.get("fields") or DEFAULT_FIELDS
    keys = ",\n".join(f'  "{name}": "{desc}"' for name, desc in fields.items())
    return (
        "Extract this product. Return ONLY a JSON object with exactly these keys.\n"
        "Use null for anything not shown on the page — never guess or infer.\n\n"
        "{\n" + keys + "\n}\n\n"
        "Return JSON only. No commentary, no markdown fences."
    )


# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------
def load_config(config_path: Optional[Path] = None) -> dict:
    """Load retailer targets and parameters from config.json."""
    path = config_path or CONFIG_PATH

    if not path.exists():
        raise FileNotFoundError(
            f"Config file not found at {path}. "
            f"Copy config.json into the recipe folder and add your retailer URLs."
        )

    with open(path, "r", encoding="utf-8") as f:
        config = json.load(f)

    if "retailers" not in config or not isinstance(config["retailers"], list):
        raise ValueError("config.json must contain a 'retailers' array.")
    if not config["retailers"]:
        raise ValueError("config.json 'retailers' array is empty. Add at least one target.")

    logger.info("Loaded config: %d retailer target(s) from %s", len(config["retailers"]), path)
    return config


def _validate_token() -> None:
    if not MRSCRAPER_API_TOKEN:
        raise ValueError(
            "MRSCRAPER_API_TOKEN environment variable is required.\n"
            "Get your token at: https://app.mrscraper.com (free tier available).\n"
            "Then set it in .env  (MRSCRAPER_API_TOKEN=atk_...)\n"
            "or in GitHub Actions:  Settings → Secrets → MRSCRAPER_API_TOKEN"
        )


# ---------------------------------------------------------------------------
# Transport: create-and-run, one product page per URL
# ---------------------------------------------------------------------------
async def _scrape_all_async(
    targets: list[dict], prompt: str, agent: str, proxy_country: str
) -> list[tuple]:
    """Run create-and-run for every target URL. Returns (target, products, error)."""
    client = MrScraper(token=MRSCRAPER_API_TOKEN)
    out: list[tuple] = []
    for i, target in enumerate(targets, 1):
        url = target["url"]
        logger.info("[%d/%d] %s → %s", i, len(targets), target.get("retailer", "?"), url[:80])
        try:
            r = await client.create_scraper(
                url=url, message=prompt, agent=agent, proxy_country=proxy_country
            )
            products = _normalize_response(r.get("data"))
            out.append((target, products, None))
        except (AuthenticationError, APIError, NetworkError) as e:
            out.append((target, [], e))
    return out


def _normalize_response(body) -> list[dict]:
    """Normalize the create-and-run response body into a flat list of products.

    Confirmed shape (the product is nested three levels deep):
        {
          "message": "Successful operation!",
          "data": {                       <- run record (status, error, ...)
            "status": "Finished",
            "data": { "product_name": ..., "current_price": ... }   <- product
          }
        }
    The inner data may be a dict (single product), a list, a wrapper like
    {"products": [...]}, or a JSON string. _unwrap_product_data handles all.
    """
    if not isinstance(body, dict):
        return []

    record = body.get("data")
    if isinstance(record, dict):
        inner = record.get("data")
        if inner is not None:
            return _unwrap_product_data(inner)
        results = record.get("results", [])
        if results:
            return _extract_products_from_results(results)

    if "result" in body and isinstance(body["result"], list):
        return body["result"]
    if isinstance(body, list):
        return body
    return []


def _unwrap_product_data(inner_data) -> list[dict]:
    """Unwrap the inner 'data' field into a list of product dicts."""
    if isinstance(inner_data, str):
        try:
            inner_data = json.loads(inner_data)
        except json.JSONDecodeError:
            logger.warning("Could not parse inner data as JSON: %s...", inner_data[:100])
            return []

    if isinstance(inner_data, list):
        return inner_data

    if isinstance(inner_data, dict):
        for key in ("products", "items", "data", "listings", "results"):
            if key in inner_data and isinstance(inner_data[key], list):
                return inner_data[key]

        product_indicators = ("product_name", "name", "title", "current_price", "price")
        if any(k in inner_data for k in product_indicators):
            return [inner_data]

    logger.warning("Could not extract products from inner data of type %s", type(inner_data).__name__)
    return []


def _extract_products_from_results(results: list[dict]) -> list[dict]:
    """Extract product data from a results[] array (older shape; kept for safety)."""
    all_products = []
    for result in results:
        status = result.get("status", "unknown")
        if status not in ("succeeded", "success", "unknown"):
            continue
        content = result.get("content", result)
        if isinstance(content, str):
            try:
                content = json.loads(content)
            except json.JSONDecodeError:
                continue
        if isinstance(content, list):
            all_products.extend(content)
        elif isinstance(content, dict):
            for key in ("products", "items", "data", "listings"):
                if key in content and isinstance(content[key], list):
                    all_products.extend(content[key])
                    break
            else:
                if "product_name" in content or "name" in content or "title" in content:
                    all_products.append(content)
    return all_products


# ---------------------------------------------------------------------------
# Product normalizer  (unchanged — retailer-agnostic field/value mapping)
# ---------------------------------------------------------------------------
def _normalize_product(raw: dict, source_url: str = "") -> dict:
    return {
        "product_name": (
            raw.get("product_name") or raw.get("name") or raw.get("title") or "Unknown"
        ),
        "current_price": _parse_price(
            raw.get("current_price") or raw.get("price") or raw.get("product_price") or 0
        ),
        "original_price": _parse_price(
            raw.get("original_price") or raw.get("list_price") or raw.get("was_price")
        ),
        "currency": _normalize_currency(
            raw.get("currency") or raw.get("product_currency") or "USD"
        ),
        "in_stock": _parse_availability(raw),
        "product_url": _resolve_url(
            raw.get("product_url") or raw.get("url") or raw.get("link"), source_url
        ),
        "seller": raw.get("seller"),
    }


def _parse_price(value) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.strip()
        for char in ("$", "€", "£", "¥", "US", "USD", "EUR", "GBP", ","):
            cleaned = cleaned.replace(char, "")
        cleaned = cleaned.strip()
        try:
            return float(cleaned)
        except ValueError:
            logger.warning("Could not parse price from string: '%s'", value)
            return 0.0
    return 0.0


def _normalize_currency(value: str) -> str:
    symbol_map = {"$": "USD", "€": "EUR", "£": "GBP", "¥": "JPY", "us$": "USD"}
    lowered = value.strip().lower()
    return symbol_map.get(lowered, value.upper().strip())


def _resolve_url(url: Optional[str], source_url: str = "") -> Optional[str]:
    if url is None:
        return None
    if url.startswith("http://") or url.startswith("https://"):
        return url
    if source_url and url.startswith("/"):
        try:
            from urllib.parse import urlparse
            parsed = urlparse(source_url)
            return f"{parsed.scheme}://{parsed.netloc}" + url
        except Exception:
            pass
    return url


def _parse_availability(raw: dict) -> bool:
    value = None
    for field in ("in_stock", "availability_status", "availability"):
        if field in raw:
            value = raw[field]
            break
    if value is None:
        return True
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.lower().strip()
        if any(k in lowered for k in ("out of stock", "unavailable", "sold out", "not available")):
            return False
        if any(k in lowered for k in ("in stock", "available", "add to cart", "buy now")):
            return True
        if any(k in lowered for k in ("people's carts", "bought since", "bought in")):
            return True
        return True
    if isinstance(value, dict):
        for channel, status in value.items():
            if isinstance(status, str):
                lowered = status.lower().strip()
                if any(kw in lowered for kw in ("unavailable", "out of stock", "sold out", "not available")):
                    continue
                if any(kw in lowered for kw in ("available", "in stock", "ready")):
                    return True
            elif isinstance(status, bool) and status:
                return True
        return False
    return True


# ---------------------------------------------------------------------------
# Orchestrator: scrape all retailers
# ---------------------------------------------------------------------------
def scrape_all_retailers(config: Optional[dict] = None) -> list[dict]:
    """Scrape every configured retailer via create-and-run, normalize, enrich.

    Returns a list of product dicts ready for the database layer. Products
    with no usable price are skipped — that filters out both empty renders
    and schema echoes (where a blocked page returns the field descriptions
    as values, e.g. current_price = "number...", which parses to 0).
    """
    if config is None:
        config = load_config()

    _validate_token()

    retailers = config["retailers"]
    agent = config.get("agent", "general")
    proxy_country = config.get("proxy_country", "US")
    prompt = build_prompt(config)
    scrape_time = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    raw_results = asyncio.run(_scrape_all_async(retailers, prompt, agent, proxy_country))

    all_products: list[dict] = []
    for target, raw_products, error in raw_results:
        retailer = target["retailer"]
        url = target["url"]
        category = target.get("category", "general")

        if error is not None:
            logger.error("x %s: %s", retailer, error)
            continue

        kept = 0
        for raw in raw_products:
            product = _normalize_product(raw, source_url=url)
            if product["current_price"] <= 0:
                logger.warning(
                    "  %s: dropped a record with no usable price "
                    "(empty render or schema echo).", retailer
                )
                continue
            product["retailer"] = retailer
            product["category"] = category
            product["scraped_at"] = scrape_time
            product["source_url"] = url
            all_products.append(product)
            kept += 1

        if kept:
            logger.info("+ %s: %d product(s)", retailer, kept)
        else:
            logger.warning("- %s: nothing usable this pass (retry later)", retailer)

    logger.info(
        "Scraping complete: %d product(s) from %d retailer(s)",
        len(all_products), len(retailers),
    )
    return all_products


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
    print(json.dumps(scrape_all_retailers(), indent=2, default=str))
