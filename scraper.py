"""
HiBid auction scraper.

Uses Playwright to load any HiBid catalog URL and intercepts the internal API
calls the page makes, giving clean JSON data for every lot. Falls back to DOM
scraping if the API calls don't match expected patterns.

Usage:
    python scraper.py <hibid-catalog-url> [options]

Examples:
    python scraper.py "https://hibid.com/catalog/741805/..."
    python scraper.py "https://hibid.com/catalog/741805/..." --output results.csv
    python scraper.py "https://hibid.com/catalog/741805/..." --format json
    python scraper.py "https://hibid.com/catalog/741805/..." --headless false
"""

import argparse
import csv
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
except ImportError:
    sys.exit("Playwright not installed. Run: pip install playwright && python -m playwright install chromium")


# ── URL helpers ──────────────────────────────────────────────────────────────

def extract_catalog_id(url: str) -> str:
    """Pull the numeric catalog ID out of any HiBid catalog URL."""
    m = re.search(r"/catalog/(\d+)", url)
    if not m:
        sys.exit(f"Could not find a catalog ID in URL: {url}")
    return m.group(1)


def normalize_url(url: str) -> str:
    """Ensure the URL has a scheme."""
    if not url.startswith("http"):
        url = "https://" + url
    return url


# ── Network interception ─────────────────────────────────────────────────────

# Patterns that look like HiBid's lot-listing API responses
LOT_API_PATTERNS = [
    re.compile(r"/lot[s]?\b", re.I),
    re.compile(r"catalog", re.I),
    re.compile(r"auction", re.I),
    re.compile(r"item[s]?\b", re.I),
]

def looks_like_lot_api(url: str) -> bool:
    path = urlparse(url).path
    return any(p.search(path) for p in LOT_API_PATTERNS)


def try_extract_lots_from_json(data) -> list[dict] | None:
    """
    Try to find a list of lot-like objects anywhere in an arbitrary JSON blob.
    Returns None if nothing promising is found.
    """
    if isinstance(data, list) and data and isinstance(data[0], dict):
        if any(k in data[0] for k in ("lotNumber", "lot_number", "lotId", "title", "name", "currentBid")):
            return data

    if isinstance(data, dict):
        for key in ("lots", "items", "results", "data", "records", "auctionItems"):
            if key in data:
                sub = data[key]
                if isinstance(sub, list) and sub and isinstance(sub[0], dict):
                    return sub
        # recurse one level deeper
        for val in data.values():
            result = try_extract_lots_from_json(val)
            if result:
                return result

    return None


# ── Lot normalisation ─────────────────────────────────────────────────────────

FIELD_ALIASES = {
    "lot_number":  ["lotNumber", "lot_number", "lotNum", "number"],
    "title":       ["title", "name", "description", "lotTitle", "itemTitle"],
    "current_bid": ["currentBid", "current_bid", "highBid", "high_bid", "bidAmount", "amount"],
    "start_price": ["startingBid", "startBid", "startPrice", "openingBid", "minimumBid"],
    "estimate":    ["estimate", "lowEstimate", "highEstimate", "estimateRange"],
    "bid_count":   ["bidCount", "numberOfBids", "numBids", "totalBids"],
    "end_time":    ["endTime", "closeTime", "closingTime", "auctionEnd", "endDate"],
    "lot_id":      ["lotId", "id", "itemId", "auctionItemId"],
    "url":         ["url", "lotUrl", "itemUrl", "link"],
    "image_url":   ["imageUrl", "image", "primaryImage", "thumbnailUrl"],
    "status":      ["status", "lotStatus", "auctionStatus"],
}

def normalise_lot(raw: dict, catalog_id: str) -> dict:
    out = {"catalog_id": catalog_id}
    for field, aliases in FIELD_ALIASES.items():
        for alias in aliases:
            if alias in raw:
                out[field] = raw[alias]
                break
        else:
            out[field] = None

    # Build a direct lot URL if we have a lot_id but no url
    if not out.get("url") and out.get("lot_id"):
        out["url"] = f"https://hibid.com/lot/{out['lot_id']}"

    return out


# ── DOM fallback ──────────────────────────────────────────────────────────────

def scrape_lots_from_dom(page, catalog_id: str) -> list[dict]:
    """
    Last-resort DOM scraper. Looks for common HiBid lot card selectors.
    Returns whatever it can find.
    """
    print("  [fallback] Attempting DOM scrape...")

    # Common selectors seen on HiBid — adjust if their markup changes
    card_selectors = [
        ".lot-card",
        "[class*='lot-card']",
        "[class*='LotCard']",
        "[data-testid*='lot']",
        ".item-card",
        "[class*='item-card']",
    ]

    cards = []
    for sel in card_selectors:
        cards = page.query_selector_all(sel)
        if cards:
            print(f"  [fallback] Found {len(cards)} cards with selector: {sel}")
            break

    if not cards:
        print("  [fallback] No lot cards found. The page structure may have changed.")
        return []

    lots = []
    for card in cards:
        text = card.inner_text().strip()
        href = None
        link = card.query_selector("a[href*='/lot/']")
        if link:
            href = link.get_attribute("href")
            if href and not href.startswith("http"):
                href = "https://hibid.com" + href

        # Extract lot number from URL or text
        lot_num = None
        if href:
            m = re.search(r"/lot/(\d+)", href)
            if m:
                lot_num = m.group(1)

        lots.append({
            "catalog_id": catalog_id,
            "lot_id":     lot_num,
            "lot_number": lot_num,
            "title":      text.split("\n")[0] if text else None,
            "current_bid": None,
            "raw_text":   text,
            "url":        href,
        })

    return lots


# ── Core scraper ──────────────────────────────────────────────────────────────

def scrape_catalog(url: str, headless: bool = True, timeout: int = 30_000) -> list[dict]:
    url = normalize_url(url)
    catalog_id = extract_catalog_id(url)
    print(f"Scraping catalog {catalog_id}: {url}")

    captured: list[dict] = []  # lots captured via API interception
    api_responses: list[dict] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1440, "height": 900},
        )
        page = context.new_page()

        # ── Intercept API responses ──────────────────────────────────────────
        def handle_response(response):
            try:
                if response.status != 200:
                    return
                ct = response.headers.get("content-type", "")
                if "json" not in ct:
                    return
                if not looks_like_lot_api(response.url):
                    return
                data = response.json()
                lots = try_extract_lots_from_json(data)
                if lots:
                    print(f"  [api] {len(lots)} lots from {response.url}")
                    api_responses.append({"url": response.url, "lots": lots})
            except Exception:
                pass

        page.on("response", handle_response)

        # ── Navigate ─────────────────────────────────────────────────────────
        print("  Loading page...")
        try:
            page.goto(url, timeout=timeout, wait_until="domcontentloaded")
        except PWTimeout:
            print("  Timed out waiting for page load, continuing anyway...")

        # Give the SPA time to fire its API calls
        page.wait_for_timeout(3000)

        # Scroll to trigger lazy-loaded content / pagination
        print("  Scrolling to load all lots...")
        prev_height = 0
        for _ in range(20):
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(1200)
            new_height = page.evaluate("document.body.scrollHeight")
            if new_height == prev_height:
                break
            prev_height = new_height

        # Extra wait for any final API calls
        page.wait_for_timeout(2000)

        # ── Decide whether we got useful API data ────────────────────────────
        if api_responses:
            # Merge results from all matching API calls (de-dupe by lot_id)
            seen_ids = set()
            for resp in api_responses:
                for raw in resp["lots"]:
                    lot = normalise_lot(raw, catalog_id)
                    uid = lot.get("lot_id") or lot.get("lot_number") or len(captured)
                    if uid not in seen_ids:
                        seen_ids.add(uid)
                        captured.append(lot)
        else:
            print("  No matching API responses captured, falling back to DOM...")
            captured = scrape_lots_from_dom(page, catalog_id)

        browser.close()

    print(f"Total lots collected: {len(captured)}")
    return captured


# ── Output writers ────────────────────────────────────────────────────────────

def write_json(lots: list[dict], path: str):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(lots, f, indent=2, default=str)
    print(f"Saved JSON → {path}")


def write_csv(lots: list[dict], path: str):
    if not lots:
        print("No lots to write.")
        return
    # Collect all keys across all lots
    fieldnames = list(dict.fromkeys(k for lot in lots for k in lot))
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(lots)
    print(f"Saved CSV  → {path}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Scrape any HiBid auction catalog into JSON or CSV.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("url", help="Full HiBid catalog URL")
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="Output file path. Defaults to hibid_<catalog_id>.<format>",
    )
    parser.add_argument(
        "--format", "-f",
        choices=["json", "csv", "both"],
        default="csv",
        help="Output format (default: csv)",
    )
    parser.add_argument(
        "--headless",
        default="true",
        choices=["true", "false"],
        help="Run browser headlessly (default: true)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="Page load timeout in seconds (default: 30)",
    )
    args = parser.parse_args()

    headless = args.headless.lower() == "true"
    catalog_id = extract_catalog_id(normalize_url(args.url))

    lots = scrape_catalog(args.url, headless=headless, timeout=args.timeout * 1000)

    if not lots:
        print("No lots found. Try --headless false to debug visually.")
        sys.exit(1)

    base = args.output or f"hibid_{catalog_id}"
    base = str(Path(base).with_suffix(""))  # strip extension if provided

    if args.format in ("json", "both"):
        write_json(lots, base + ".json")
    if args.format in ("csv", "both"):
        write_csv(lots, base + ".csv")

    # Always print a quick preview to stdout
    print(f"\nPreview (first 5 of {len(lots)} lots):")
    for lot in lots[:5]:
        title = lot.get("title") or lot.get("raw_text", "")[:60]
        bid   = lot.get("current_bid") or "—"
        num   = lot.get("lot_number") or lot.get("lot_id") or "?"
        print(f"  Lot {num:>5}  ${bid:<10}  {title}")


if __name__ == "__main__":
    main()
