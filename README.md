# HiBid Scraper

Scrapes any HiBid auction catalog into CSV or JSON.

## How it works

Playwright loads the catalog page in a real (headless) Chromium browser and intercepts the internal API calls HiBid's frontend makes to fetch lot data. This gives clean structured JSON rather than fragile HTML parsing. If no API calls match, it falls back to DOM scraping.

## Setup

```bash
pip install playwright
python -m playwright install chromium
```

## Usage

```bash
# Basic — saves hibid_741805.csv
python scraper.py "https://hibid.com/catalog/741805/5-27-portugal-leaf-pottery--guitars--outdoor-theatre--comics"

# Save as JSON
python scraper.py "<url>" --format json

# Save both CSV and JSON
python scraper.py "<url>" --format both

# Custom output file
python scraper.py "<url>" --output my_auction.csv

# Debug with visible browser window
python scraper.py "<url>" --headless false
```

## Output fields

| Field | Description |
|---|---|
| `catalog_id` | HiBid catalog ID from the URL |
| `lot_id` | Internal lot identifier |
| `lot_number` | Display lot number |
| `title` | Lot title / item name |
| `current_bid` | Current high bid |
| `start_price` | Opening / starting bid |
| `estimate` | Auction house estimate |
| `bid_count` | Number of bids placed |
| `end_time` | Lot closing time |
| `url` | Direct link to the lot |
| `image_url` | Primary image URL |
| `status` | Lot status (open, closed, etc.) |

## Notes

- Run on your **local machine** — HiBid blocks requests from cloud/datacenter IPs
- If you get no results, try `--headless false` to watch the browser and diagnose what's happening
- HiBid occasionally changes their internal API structure; the field aliases in `scraper.py` cover common variations
