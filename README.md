# MrScraper Cookbook

Copy-paste recipes for getting real work done with [MrScraper](https://app.mrscraper.com) — each one a small, self-contained project you can run in minutes.

## Recipes

| Recipe                                   | What it does                                                                                             | Archetype                     |
| ---------------------------------------- | -------------------------------------------------------------------------------------------------------- | ----------------------------- |
| [`price-monitoring/`](price-monitoring/) | Track products across retailers; alert on price drops, increases, and stock changes. Runs on a schedule. | Monitoring — change over time |

More recipes are on the way.

## Getting started

Open a recipe folder and follow its README. Each recipe includes its own setup, config, demo path, and expected output.

Most recipes use:

* Python 3.10+
* A MrScraper account
* A `MRSCRAPER_API_TOKEN` stored in `.env` locally or as a GitHub Actions secret

## Conventions

* **Each recipe is its own folder.** Everything a recipe needs — code, config, README — lives inside it, so you can run one without touching the others.
* **Scheduled workflows live at the repo root.** GitHub Actions only runs workflows from `<repo-root>/.github/workflows/`, never from a subfolder. So a recipe's workflow file sits at the cookbook root and scopes itself into the recipe folder with `working-directory:`. See `.github/workflows/price-monitor.yml`.
* **Playground first.** Every recipe is built on the same core move you can try before writing code: paste a URL, describe the fields in plain English, get clean JSON. The scripted recipes turn that into repeatable automations.

