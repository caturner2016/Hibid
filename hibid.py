"""HiBid catalog scraper — loads page in Chromium and intercepts API responses."""

import asyncio
import re
import sys
from urllib.parse import urlparse

try:
    from playwright.async_api import async_playwright, TimeoutError as PWTimeout
except ImportError:
    sys.exit("Run: pip install playwright && python -m playwright install chromium")


def extract_catalog_id(url: str) -> str:
    m = re.search(r"/catalog/(\d+)", url)
    if not m:
        sys.exit(f"No catalog ID found in: {url}")
    return m.group(1)


def normalize_url(url: str) -> str:
    if not url.startswith("http"):
        url = "https://" + url
    return url


# ── API interception ──────────────────────────────────────────────────────────

_LOT_PATH_RE = re.compile(r"/lot[s]?|catalog|auction|item[s]?", re.I)

def _looks_like_lot_api(url: str) -> bool:
    return bool(_LOT_PATH_RE.search(urlparse(url).path))


def _find_lots_in_json(data) -> list[dict] | None:
    """Recursively hunt for a list of lot-like objects in arbitrary JSON."""
    if isinstance(data, list) and data and isinstance(data[0], dict):
        if any(k in data[0] for k in ("lotNumber", "lot_number", "lotId", "title", "name", "currentBid")):
            return data
    if isinstance(data, dict):
        for key in ("lots", "items", "results", "data", "records", "auctionItems"):
            if key in data:
                sub = data[key]
                if isinstance(sub, list) and sub and isinstance(sub[0], dict):
                    return sub
        for val in data.values():
            found = _find_lots_in_json(val)
            if found:
                return found
    return None


# ── Field normalisation ───────────────────────────────────────────────────────

_ALIASES = {
    "lot_number":  ["lotNumber", "lot_number", "lotNum", "number"],
    "title":       ["title", "name", "description", "lotTitle", "itemTitle"],
    "current_bid": ["currentBid", "current_bid", "highBid", "high_bid", "bidAmount"],
    "start_price": ["startingBid", "startBid", "startPrice", "openingBid", "minimumBid"],
    "estimate":    ["estimate", "lowEstimate", "highEstimate"],
    "bid_count":   ["bidCount", "numberOfBids", "numBids", "totalBids"],
    "end_time":    ["endTime", "closeTime", "closingTime", "auctionEnd", "endDate"],
    "lot_id":      ["lotId", "id", "itemId", "auctionItemId"],
    "image_url":   ["imageUrl", "image", "primaryImage", "thumbnailUrl", "imageURL",
                    "primaryImageUrl", "images"],
    "status":      ["status", "lotStatus", "auctionStatus"],
}

def _normalise(raw: dict, catalog_id: str) -> dict:
    out = {"catalog_id": catalog_id}
    for field, aliases in _ALIASES.items():
        for alias in aliases:
            if alias in raw:
                val = raw[alias]
                if field == "image_url" and isinstance(val, list):
                    val = val[0] if val else None
                    if isinstance(val, dict):
                        val = val.get("url") or val.get("src") or val.get("href")
                out[field] = val
                break
        else:
            out[field] = None

    if not out.get("url"):
        lid = out.get("lot_id") or out.get("lot_number")
        if lid:
            out["url"] = f"https://hibid.com/lot/{lid}"

    return out


# ── DOM fallback ──────────────────────────────────────────────────────────────

async def _dom_fallback(page, catalog_id: str) -> list[dict]:
    print("  [fallback] Scraping DOM...")
    cards = []
    for sel in (".lot-card", "[class*='lot-card']", "[class*='LotCard']", ".item-card"):
        cards = await page.query_selector_all(sel)
        if cards:
            break

    lots = []
    for card in cards:
        text = (await card.inner_text()).strip()
        href = None
        link = await card.query_selector("a[href*='/lot/']")
        if link:
            href = await link.get_attribute("href")
            if href and not href.startswith("http"):
                href = "https://hibid.com" + href

        img_el = await card.query_selector("img")
        img_url = await img_el.get_attribute("src") if img_el else None

        lot_id = None
        if href:
            m = re.search(r"/lot/(\d+)", href)
            if m:
                lot_id = m.group(1)

        lots.append({
            "catalog_id": catalog_id,
            "lot_id":     lot_id,
            "lot_number": lot_id,
            "title":      text.split("\n")[0] if text else None,
            "current_bid": None,
            "image_url":  img_url,
            "url":        href,
        })
    return lots


# ── Async core ────────────────────────────────────────────────────────────────

async def _scrape_async(url: str, headless: bool, timeout_ms: int) -> list[dict]:
    catalog_id = extract_catalog_id(url)
    api_hits: list[list] = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=headless)
        ctx = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1440, "height": 900},
        )
        page = await ctx.new_page()

        async def on_response(resp):
            try:
                if resp.status != 200:
                    return
                if "json" not in resp.headers.get("content-type", ""):
                    return
                if not _looks_like_lot_api(resp.url):
                    return
                data = await resp.json()
                lots = _find_lots_in_json(data)
                if lots:
                    print(f"  [api] {len(lots)} lots ← {resp.url}")
                    api_hits.append(lots)
            except Exception:
                pass

        page.on("response", on_response)

        print("  Loading page...")
        try:
            await page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
        except PWTimeout:
            print("  Load timed out, continuing...")

        await page.wait_for_timeout(3000)

        print("  Scrolling for lazy-loaded lots...")
        prev_h = 0
        for _ in range(25):
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(1200)
            h = await page.evaluate("document.body.scrollHeight")
            if h == prev_h:
                break
            prev_h = h

        await page.wait_for_timeout(2000)

        if api_hits:
            seen = set()
            lots = []
            for raw_list in api_hits:
                for raw in raw_list:
                    lot = _normalise(raw, catalog_id)
                    uid = lot.get("lot_id") or lot.get("lot_number") or id(raw)
                    if uid not in seen:
                        seen.add(uid)
                        lots.append(lot)
        else:
            lots = await _dom_fallback(page, catalog_id)

        await browser.close()

    return lots


# ── Public entry point ────────────────────────────────────────────────────────

def scrape_catalog(url: str, headless: bool = True, timeout_ms: int = 30_000) -> list[dict]:
    url = normalize_url(url)
    catalog_id = extract_catalog_id(url)
    print(f"Scraping HiBid catalog {catalog_id}")
    lots = asyncio.run(_scrape_async(url, headless, timeout_ms))
    print(f"  {len(lots)} lots collected")
    return lots
