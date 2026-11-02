<!-- mcp-name: io.github.sepehr071/hamrah-mechanic-mcp -->

# hamrah-mechanic-mcp: Hamrah Mechanic (همراه مکانیک) car prices and used cars MCP server for AI agents

**hamrah-mechanic-mcp is an unofficial, read-only MCP server that gives AI agents the public data of Hamrah Mechanic (hamrah-mechanic.com), an Iranian car services company.**<br>
Its 12 tools read the daily car market price list by brand, model, trim and year, give a trim's price range and monthly history,<br>
search used and zero-km cars for sale with filters, read one ad in full, list inspection fees, find showrooms, and read<br>
expert reviews and the Persian magazine.<br>
No API key or account is needed. It works in Claude, Cursor, Copilot and any other MCP client.

[![PyPI](https://img.shields.io/pypi/v/hamrah-mechanic-mcp?color=2563eb)](https://pypi.org/project/hamrah-mechanic-mcp/)
[![License: MIT](https://img.shields.io/badge/license-MIT-16a34a)](https://github.com/sepehr071/hamrah-mechanic-mcp/blob/main/LICENSE)

## For AI agents

- **What:** unofficial MCP server for hamrah-mechanic.com: daily car price list (قیمت روز خودرو), used car search, ad details, inspection prices, showroom list.
- **Install:** `uvx hamrah-mechanic-mcp` or `claude mcp add hamrah-mechanic -- uvx hamrah-mechanic-mcp`. Transport: stdio. Needs [uv](https://docs.astral.sh/uv/getting-started/installation/) (Python 3.10+).
- **Auth:** none. Optional `HAMRAH_MECHANIC_MCP_PROXY` (HTTP proxy URL, or a comma-separated list); system proxy settings are ignored.
- **Access:** read-only. It cannot log in, book, buy or sell, and never returns seller phone numbers, so no confirmation is needed before calling any tool.
- **Tools:** 12, all prefixed `hm_`. Typical sequences: `hm_brands` -> `hm_models` -> `hm_prices` -> `hm_price_history`; `hm_search_cars` -> `hm_car` -> `hm_price_estimate`; `hm_car` -> `hm_inspection_prices`; `hm_price_list` (budget) -> `hm_reviews`; `hm_articles` (specs, comparisons).
- **Use when:** the user asks what a car model costs today in Iran (market price by trim and model year), what used cars of a kind are on sale and for how much, whether an ad is priced fairly, what a car inspection costs, or where the showrooms are.
- **Do not use when:** the user wants other sellers' marketplaces, factory prices, parts, repair or insurance prices (the site has none), or anything that needs an account.
- **Output:** compact JSON, prices in Toman, Persian names. Years are Solar Hijri for Iranian cars and Gregorian for imports.

## Quick start

```bash
claude mcp add hamrah-mechanic -- uvx hamrah-mechanic-mcp
```

Other clients: command `uvx`, args `["hamrah-mechanic-mcp"]`.

## Tools

| Tool | What it does |
|---|---|
| `hm_brands` | Brand slugs, optionally filtered by name. |
| `hm_models` | Models of a brand with slugs. |
| `hm_prices` | Daily market prices: a brand's models, a model's trims by year, or one year. |
| `hm_price_estimate` | Price range and monthly trend of one trim in one year (trend is null when the site has no data). |
| `hm_price_history` | About six monthly market prices of one trim and year, plus its other years and cars for sale. |
| `hm_price_list` | Every priced domestic or imported car, filtered by budget or brand. |
| `hm_reviews` | Expert review (pros, cons, engine, safety), owner ratings and comments of a model, or a brand profile. |
| `hm_articles` | Search and read the Persian magazine (specs, comparisons, buying and care advice, news). |
| `hm_search_cars` | Cars for sale: brand, model, price, year, km, gearbox, fuel, body, origin, color, city, installments, showroom stock, sort. A brand also matches its Iranian-assembled models; those cards show the requested brand plus `maker`. |
| `hm_car` | One ad: price, specs, condition, highlights, photos. |
| `hm_inspection_prices` | Fee for the full, VIP and economy inspection of a car, by time slot. |
| `hm_branches` | Showrooms and inspection centers of a province. |

## FAQ

**Is it official?** No. It reads the same public pages and API that hamrah-mechanic.com shows any visitor, with a small cache and request limit.
**Does it work outside Iran?** Yes, directly or through `HAMRAH_MECHANIC_MCP_PROXY`.

## فارسی

سرور MCP غیررسمی و فقط‌خواندنی برای همراه مکانیک: قیمت روز خودرو بر اساس برند، مدل، تیپ و سال، برآورد قیمت، جست‌وجوی خودروهای آگهی‌شده با فیلتر، جزئیات آگهی، هزینهٔ کارشناسی و شعب حضوری. نصب: `uvx hamrah-mechanic-mcp`.

Author: Sepehr Radmard (سپهر رادمرد) · [github.com/sepehr071](https://github.com/sepehr071) · [linkedin.com/in/sepehr-radmard](https://linkedin.com/in/sepehr-radmard)
