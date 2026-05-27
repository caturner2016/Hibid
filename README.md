# HiBid Auction Evaluator

Scrapes any HiBid catalog, pulls the lot image and title, then compares each lot against recent eBay sold prices — all in a single HTML report you open in your browser.

![Report shows lot image, current bid, and eBay sold comps side by side]

## Setup

```bash
pip install playwright requests beautifulsoup4
python -m playwright install chromium
```

## Usage

```bash
# Full run — scrapes HiBid, fetches eBay comps, opens report in browser
python scraper.py "https://hibid.com/catalog/741805/..."

# Skip eBay lookup (faster, still generates HTML with images)
python scraper.py "https://hibid.com/catalog/741805/..." --no-ebay

# Visible browser window for debugging
python scraper.py "https://hibid.com/catalog/741805/..." --headless false

# Also save CSV and JSON alongside the HTML
python scraper.py "https://hibid.com/catalog/741805/..." --csv --json

# Slow down eBay requests if you're hitting rate limits
python scraper.py "https://hibid.com/catalog/741805/..." --ebay-delay 3
```

## What the report shows

Each lot card displays:
- **Main image** from HiBid
- **Lot number and title**
- **Current bid** on HiBid
- **eBay sold comps** — last 6 matching sales with prices and links
- **Value verdict** — colour-coded badge:
  - 🟢 **Great deal** — bid is under 50% of eBay average
  - 🟡 **Good deal** — bid is 50–80% of eBay average
  - 🔴 **Fair / Overbid** — bid is at or above eBay average
  - ⬜ **No eBay data** — nothing found to compare

## Notes

- Must run on your **local machine** — HiBid blocks cloud/datacenter IPs
- eBay lookup takes ~1.5 seconds per lot; a 100-lot auction takes ~2.5 minutes
- If eBay comps look wrong, the title may be too specific or too generic — check the "View all on eBay" link in the card
