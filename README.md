# MrScraper Cookbook

Copy-paste recipes for getting real work done with [MrScraper](https://app.mrscraper.com). Each recipe is a small, self-contained project you can clone and run in minutes.

## Recipes

| Recipe | What it does |
| ------ | ------------ |
| [`price-monitoring/`](price-monitoring/) | Track products across retailers. Alerts on price drops, price increases, and stock changes. Runs every 6 hours on GitHub Actions. |

More recipes are on the way.

## How recipes are organized

- Each recipe is its own folder with everything it needs: code, config, README, and tests.
- Scheduled workflows live at the repo root in `.github/workflows/`, because GitHub Actions only runs workflows from there. Each workflow scopes itself into its recipe folder with `working-directory`.
- Secrets like `MRSCRAPER_API_TOKEN` go in a gitignored `.env` for local runs, and in repo Settings → Secrets and variables → Actions for scheduled runs.

## Quickstart

```bash
cd price-monitoring
pip install -r requirements.txt
pytest -q                 # 52 tests, no token needed
cp .env.example .env      # paste your MrScraper token
python monitor.py
```

## License

MIT
