"""Search eBay completed/sold listings for a given title."""

import re
import time
import urllib.parse

import requests
from bs4 import BeautifulSoup


_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Words/patterns to strip before searching eBay
_STRIP_RE = re.compile(
    r"^lot\s*\d+\s*[:\-]\s*"          # "Lot 42: " prefix
    r"|^lot\s+of\s+\d+\s+"            # "Lot of 3 "
    r"|\bset\s+of\s+\d+\b"            # "set of 4"
    r"|\bpair\s+of\b"                  # "pair of"
    r"|\b(signed|autographed)\b"       # auction buzzwords that confuse eBay
    r"|\bcoa\b|\bw/coa\b",
    re.I,
)

_PRICE_RE = re.compile(r"[\d,]+\.?\d*")


def clean_title(title: str) -> str:
    """Strip auction-house boilerplate and trim to a focused eBay search query."""
    if not title:
        return ""
    q = _STRIP_RE.sub(" ", title).strip()
    # Collapse whitespace
    q = re.sub(r"\s{2,}", " ", q)
    # Trim to ~60 chars at a word boundary
    if len(q) > 60:
        q = q[:60].rsplit(" ", 1)[0]
    return q.strip()


def _parse_price(text: str) -> float | None:
    m = _PRICE_RE.search(text.replace(",", ""))
    if m:
        try:
            return float(m.group())
        except ValueError:
            pass
    return None


def search_sold(title: str, max_results: int = 6, delay: float = 1.5) -> dict:
    """
    Return a dict with:
        query     – the cleaned search string sent to eBay
        search_url – full eBay search URL
        results   – list of {title, price, url, date}
        avg_price – float or None
        min_price – float or None
        max_price – float or None
    """
    query = clean_title(title)
    result = {
        "query": query,
        "search_url": "",
        "results": [],
        "avg_price": None,
        "min_price": None,
        "max_price": None,
    }

    if not query:
        return result

    params = {
        "_nkw": query,
        "LH_Sold": "1",
        "LH_Complete": "1",
        "_sacat": "0",
        "_sop": "13",   # sort newest first
    }
    search_url = "https://www.ebay.com/sch/i.html?" + urllib.parse.urlencode(params)
    result["search_url"] = search_url

    time.sleep(delay)

    try:
        resp = requests.get(search_url, headers=_HEADERS, timeout=15)
    except requests.RequestException as e:
        print(f"  [ebay] Request failed for '{query}': {e}")
        return result

    if resp.status_code != 200:
        print(f"  [ebay] HTTP {resp.status_code} for '{query}'")
        return result

    soup = BeautifulSoup(resp.text, "html.parser")
    items = soup.select("li.s-item")

    solds = []
    for item in items:
        title_el  = item.select_one(".s-item__title")
        price_el  = item.select_one(".s-item__price")
        link_el   = item.select_one("a.s-item__link")
        date_el   = item.select_one(".s-item__title--tag .POSITIVE, "
                                    ".s-item__caption--signal, "
                                    ".s-item__title-tag")

        if not (title_el and price_el and link_el):
            continue

        item_title = title_el.get_text(strip=True)
        if item_title.lower().startswith("shop on ebay"):
            continue

        price = _parse_price(price_el.get_text())
        if price is None:
            continue

        date_text = date_el.get_text(strip=True) if date_el else ""

        solds.append({
            "title": item_title,
            "price": price,
            "url":   link_el["href"].split("?")[0],
            "date":  date_text,
        })

        if len(solds) >= max_results:
            break

    if solds:
        prices = [s["price"] for s in solds]
        result["results"]   = solds
        result["avg_price"] = round(sum(prices) / len(prices), 2)
        result["min_price"] = min(prices)
        result["max_price"] = max(prices)

    return result
