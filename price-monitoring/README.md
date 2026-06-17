# Price Monitor

Track a set of products across retailers. Each run scrapes every product, compares it to the last run, and prints a short summary of what changed: price drops, price increases, and stock going in or out. Runs on a 6-hour schedule with GitHub Actions and no server.

> Status: validated against MrScraper's known SDK patterns and covered by an offline `selftest.py`. The live scrape call is pending a run against your account.

## What you'll build

A single script, `monitor.py`, that you point at a list of product URLs. It returns a screenshot-ready summary like this:

```
Run Summary

🔔 PRICE DROP
Powerbeats Pro 2 (BestBuy)
USD 249.99 → USD 199.99  (-20.0%)

🔔 OUT OF STOCK
Samsung SSD 990 Pro 2TB (Amazon)

No changes detected on 4 other product(s).
```

State lives in one JSON file. No database, no SQL, nothing to host.

## Quickstart

```bash
cd price-monitoring
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python selftest.py            # proves the change-detection logic, no token needed
cp .env.example .env          # paste your MrScraper token
python monitor.py             # first run = baseline; run again later for the first diff
```

To force a full alert summary for a screenshot or video: `python seed_demo.py && python monitor.py`.

## Who it's for

Ecommerce operators watching competitor or own-catalog prices, founders tracking a few SKUs, and developers who want a price/stock feed for a dashboard, alert, or LLM workflow. You do not need to write code to run it. You do need to paste URLs into a config file.

## When to use it

When you care about *change over time* on pages you don't control: a competitor drops a price, a popular item goes out of stock, a deal ends. One-off extraction is the Playground. This recipe is the scheduled version of that same move.

## What you need

- Python 3.10+
- A MrScraper token (free tier at https://app.mrscraper.com)
- A GitHub account, if you want the schedule. Local runs need neither.

## MrScraper setup

There is no dashboard setup. The recipe calls create-and-run per URL, which is the same call the Playground "Run" button makes: you give it a URL and a plain-English field list, it returns clean JSON. The extraction prompt lives in `monitor.py`, so any change to what you extract is a reviewable diff.

`agent="general"` because each URL is one product page. `proxy_country="US"` so US storefronts return US pricing. Omitting the country silently returns wrong-locale prices, which is the single most common way these runs go wrong.

## Example fields to extract

```json
{
  "name": "the product title",
  "price": "current selling price as a number, after any discount; null if not shown",
  "currency": "currency code shown, e.g. USD; null if not shown",
  "in_stock": "true if it can be bought now, false if sold out"
}
```

Four fields. Add more if you want (rating, seller, SKU), but these four are all the diff needs.

## API/SDK workflow

1. Read `config.json` for the product list, proxy country, and threshold.
2. Scrape every URL, one at a time, with `create_scraper(url=..., message=PROMPT, agent="general", proxy_country=...)`.
3. Load the previous run from `data/snapshot.json`.
4. Diff current against previous, keyed by URL. Emit events for stock transitions and for price moves at or above the threshold.
5. Print the summary, write it to the GitHub Actions run page if in CI, and save the new snapshot.

## Clean code sample

The whole monitor is `monitor.py`. The two parts that matter:

The live call, with the verified response path:

```python
result = await client.create_scraper(
    url=url, message=PROMPT, agent="general", proxy_country=proxy_country
)
# record at result["data"]["data"]; General Agent fields at record["data"]
record = result["data"]["data"]
fields = record["data"]            # the product dict (may be a JSON string; coerce)
```

The diff, keyed by URL so a drifting product title never breaks tracking:

```python
for url, curr in current.items():
    prev = previous.get(url)
    if prev is None:
        continue  # first sighting, nothing to compare
    if prev["in_stock"] and not curr["in_stock"]:
        emit("out_of_stock", ...)
    elif not prev["in_stock"] and curr["in_stock"]:
        emit("back_in_stock", ...)
    elif prev["price"] and curr["price"]:
        pct = (curr["price"] - prev["price"]) / prev["price"] * 100
        if abs(pct) >= threshold:
            emit("price_drop" if pct < 0 else "price_increase", ...)
```

Run it:

```bash
cd price-monitoring
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # paste your token
python monitor.py             # first run is the baseline
python monitor.py             # second run is the first real diff
```

## Expected output

First run prints `No changes detected on 0 product(s).` and writes the baseline. Every run after that compares to the one before it and prints the summary shown at the top.

To show a full summary on demand for a video or screenshot, stage changes into the snapshot:

```bash
python monitor.py            # build a baseline
python seed_demo.py          # stage a price move and a stock change
python monitor.py            # the run shows the staged alerts
python seed_demo.py --reset  # start clean
```

The change-detection logic is proven offline:

```bash
python selftest.py           # quick synthetic before/after, no API, no token
pip install pytest && pytest -q   # full suite: 52 tests, every offline path
```

## Common pitfalls

- **Wrong-locale prices.** Without `proxy_country`, a US product can come back in TWD or EUR. Set it.
- **Out-of-stock pages hide the price.** When that happens, `price` is null. This recipe still records the product and still reports the stock transition. (The earlier database version dropped any record with no price, so out-of-stock events with hidden prices were silently missed. Fixed here by keying on URL and treating stock and price independently.)
- **Blocked or blank renders.** A site occasionally returns nothing usable. That product is skipped for the run and keeps its last-known snapshot value, so one bad render doesn't fake a change next time. Confirm your targets render reliably before you rely on them.
- **First run never alerts.** It is the baseline. You need two runs to get a diff. On a 6-hour schedule that means alerts can't appear until the second scheduled run (about 6 hours in). If you want a populated summary on the first morning, commit a seeded `snapshot.json` or run `monitor.py` once locally before the schedule starts.
- **The schedule only runs on the default branch.** `cron` triggers fire from `main`, not from a feature branch. Merge before you expect overnight runs.
- **When you demo, only show clean runs.** Never a token, a failed scrape, or empty output on screen.

## Production notes

- Latency is roughly 30 to 75 seconds per page, and the recipe scrapes one product at a time on purpose (stays inside free-tier limits, fails one product at a time, reads cleanly in logs). Budget a few minutes for 5 to 10 products. The CI timeout is set to 30 minutes to leave headroom.
- Pick volatile products to make the schedule earn its keep: open-box and clearance listings, daily-deal items, fast-moving electronics. Stable catalog pages rarely move on a 6-hour cron.
- The JSON snapshot is fine to about 50 products. Past that, or if you want history rather than just last-vs-current, move to SQLite or Postgres. The diff logic does not change.
- Scale the product list to 5 to 10 by adding entries to `config.json` in the same shape. More products, more chances to catch a real move.

## Optional extensions

- Post the summary to Slack or Discord by sending the same text to a webhook URL.
- Keep full history in SQLite and chart it in Grafana.
- Feed the events into a repricing rule or an LLM that drafts the response.
- Monitor minimum advertised price across resellers and flag violations.

## Content/LinkedIn angle

"I track 8 products across Amazon, Best Buy, and Walmart for price drops and stock changes. The whole thing is one Python file and a GitHub Action that runs every 6 hours. No server, no database. Here's the file." Then show the summary screenshot and the 40-line diff function. The hook is that the hard part (reliable extraction from sites that fight scrapers) is one API call, and everything else is a diff you can read in a minute.

## License

MIT
