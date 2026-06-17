# Price Monitor — MrScraper cookbook

Automated price tracking: monitor the same product across retailers (Amazon, Best Buy, Walmart, …), detect price drops, increases, and stock changes, and route alerts to console, Slack/Discord, email, or the GitHub Actions summary. Runs on GitHub Actions with zero infrastructure.

This recipe lives in the cookbook at `mrscraper-cookbook/price-monitoring/`.

## How it works

1. **Scrape** — for each retailer URL, the pipeline calls MrScraper's create-and-run API (the same call the Playground "Run" button makes) with a plain-English field list. No dashboard setup, no scraper IDs.
2. **Store** — results land in SQLite with full, timestamped history.
3. **Detect** — a SQL diff compares the latest scrape with the previous one and flags changes above a configurable threshold.
4. **Alert** — changes route to console, GitHub Actions summary, Slack/Discord webhook, or email.

## Quick start

### Prerequisites
- Python 3.10+
- A [MrScraper account](https://app.mrscraper.com) (free tier available) and an API token
- A GitHub account (for scheduled runs)

### 1. Add your products

Edit `config.json` — list the product pages you want to track. No scraper IDs needed; the extraction prompt is built from the `fields` block right there in the config.

```json
{
  "retailers": [
    { "retailer": "Amazon", "url": "https://www.amazon.com/...", "category": "headphones" }
  ]
}
```

Use one product detail page per entry (the General Agent extracts one product per URL). To track the same product across stores, add one entry per retailer.

### 2. Install

```bash
cd price-monitoring
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # then edit .env and paste your real token
```

### 3. Run

```bash
python -m src.pipeline              # full pipeline
python -m src.pipeline --dry-run    # scrape + print, don't store
python -m src.pipeline --threshold 10   # alert only on 10%+ moves
```

The first run is your baseline (it stores prices, nothing to compare yet). The second run is the first real diff.

### 4. Schedule it (GitHub Actions)

The workflow runs every 6 hours and persists the price database between runs via the Actions cache. It lives at the **cookbook repo root** — `.github/workflows/price-monitor.yml` — because Actions only runs workflows from the repository root, not from a subfolder. It's already scoped into this recipe with `working-directory: price-monitoring`.

1. Push the cookbook repo to GitHub.
2. Settings → Secrets and variables → Actions → add `MRSCRAPER_API_TOKEN`.
3. (Optional) add `ALERT_WEBHOOK_URL` (and `ALERT_WEBHOOK_FORMAT=discord` for Discord).
4. Trigger manually from Actions → Price Monitor → Run workflow, or wait for the schedule.

## Demo

To show the alert system without waiting for a real price move, seed a change into your local database and re-run:

```bash
python -m src.pipeline                 # build a baseline first
python demo_seed_alert.py --retailer BestBuy --delta -50   # stage a $50 drop
python -m src.pipeline                 # the diff now fires a price-drop alert
python demo_seed_alert.py --reset      # undo
```

## Project structure

```
mrscraper-cookbook/
├── .github/workflows/price-monitor.yml   # scheduler (must be at repo root)
└── price-monitoring/
    ├── src/
    │   ├── scraper.py      # create-and-run integration + response normalization
    │   ├── database.py     # SQLite price history + SQL change detection
    │   ├── alerts.py       # console / GitHub / Slack / Discord / email
    │   └── pipeline.py     # orchestrator (CLI entry point)
    ├── config.json         # retailer targets + extraction fields
    ├── demo_seed_alert.py  # demo helper (not part of the pipeline)
    ├── data/               # SQLite db (auto-created, gitignored)
    ├── .env.example
    ├── requirements.txt
    └── README.md
```

## Configuration notes

- **`fields`** — the extraction schema in plain English. The keys map to what the normalizer understands (`product_name`, `current_price`, `original_price`, `currency`, `in_stock`, `product_url`, `seller`); edit the descriptions to tune extraction. The prompt is generated from this, so changes are reviewable in version control.
- **`agent`** — `general` for individual product pages (this recipe). Listing/search pages are a different recipe.
- **`proxy_country`** — geolocates the request; `US` for US storefronts.
- **`alerts.threshold_pct`** — informational; the live threshold is the `--threshold` flag / workflow input.

## Notification channels

| Channel        | Configuration                                                        |
| -------------- | -------------------------------------------------------------------- |
| Console        | always on (visible in CI logs)                                       |
| GitHub summary | automatic in Actions                                                 |
| Slack          | `ALERT_WEBHOOK_URL`                                                  |
| Discord        | `ALERT_WEBHOOK_URL` + `ALERT_WEBHOOK_FORMAT=discord`                 |
| Email          | `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `ALERT_EMAIL_TO` |

## Gotchas (worth knowing before you publish or demo)

- **Empty renders happen.** A site occasionally returns a blank/blocked page; that scrape yields no usable price and is skipped, not stored. It's site variance — a later run usually catches it. Confirm your target sites render reliably before relying on them.
- **Schema-echo guard.** On a blocked page a model can return the field *descriptions* as values (`current_price` = "number…"). Those parse to a non-positive price and are dropped, so they never pollute history.
- **Change detection keys on product name + retailer.** If a retailer's extracted product title drifts between runs, organic detection can miss or double-count. The demo path (`demo_seed_alert.py`) edits an existing row, so it's unaffected. For long-running production use, keying on a stable identifier (the product URL) is a worthwhile hardening.
- **When you demo:** only show clean, populated runs — never a token, a failed run, or empty output on screen.

## Extending

- Dashboard (Grafana) over the SQLite/Postgres history
- Feed alerts into a repricing engine
- MAP (minimum advertised price) violation monitoring across resellers
- Multi-region via proxy settings; swap SQLite for Postgres/TimescaleDB at scale

## License

MIT
