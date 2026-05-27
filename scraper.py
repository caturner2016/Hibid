"""
HiBid auction evaluator — scrapes a catalog and compares lots against eBay solds.

Usage:
    python scraper.py <hibid-catalog-url> [options]

Examples:
    python scraper.py "https://hibid.com/catalog/741805/..."
    python scraper.py "https://hibid.com/catalog/741805/..." --no-ebay
    python scraper.py "https://hibid.com/catalog/741805/..." --headless false
    python scraper.py "https://hibid.com/catalog/741805/..." --ebay-delay 2
"""

import argparse
import csv
import json
import sys
import webbrowser
from pathlib import Path

from hibid import scrape_catalog, extract_catalog_id, normalize_url
import ebay
import report


def write_json(lots, path):
    clean = [{k: v for k, v in lot.items() if k != "_ebay"} | {"ebay": lot.get("_ebay")}
             for lot in lots]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(clean, f, indent=2, default=str)
    print(f"JSON  → {path}")


def write_csv(lots, path):
    if not lots:
        return
    flat = []
    for lot in lots:
        row = {k: v for k, v in lot.items() if k != "_ebay"}
        eb  = lot.get("_ebay") or {}
        row["ebay_avg"]    = eb.get("avg_price")
        row["ebay_min"]    = eb.get("min_price")
        row["ebay_max"]    = eb.get("max_price")
        row["ebay_query"]  = eb.get("query")
        row["ebay_search"] = eb.get("search_url")
        flat.append(row)
    fieldnames = list(dict.fromkeys(k for r in flat for k in r))
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(flat)
    print(f"CSV   → {path}")


def main():
    parser = argparse.ArgumentParser(
        description="Scrape any HiBid auction and compare lots to eBay sold prices.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("url", help="Full HiBid catalog URL")
    parser.add_argument("--output", "-o", default=None,
                        help="Base output filename (no extension). Default: hibid_<id>")
    parser.add_argument("--no-ebay", action="store_true",
                        help="Skip eBay lookup (faster, HTML report still generated)")
    parser.add_argument("--ebay-delay", type=float, default=1.5, metavar="SECS",
                        help="Seconds to wait between eBay requests (default: 1.5)")
    parser.add_argument("--ebay-results", type=int, default=6, metavar="N",
                        help="Max eBay sold results per lot (default: 6)")
    parser.add_argument("--headless", default="true", choices=["true", "false"],
                        help="Run Chromium headlessly (default: true)")
    parser.add_argument("--timeout", type=int, default=30,
                        help="Page load timeout in seconds (default: 30)")
    parser.add_argument("--no-open", action="store_true",
                        help="Don't auto-open the HTML report in your browser")
    parser.add_argument("--csv", action="store_true", help="Also save a CSV file")
    parser.add_argument("--json", action="store_true", help="Also save a JSON file")
    args = parser.parse_args()

    headless    = args.headless.lower() == "true"
    catalog_id  = extract_catalog_id(normalize_url(args.url))
    base        = args.output or f"hibid_{catalog_id}"
    base        = str(Path(base).with_suffix(""))

    # 1. Scrape HiBid
    lots = scrape_catalog(args.url, headless=headless, timeout_ms=args.timeout * 1000)
    if not lots:
        sys.exit("No lots found. Try --headless false to debug visually.")

    # 2. eBay comparison
    if not args.no_ebay:
        print(f"\nFetching eBay sold comps for {len(lots)} lots "
              f"(~{args.ebay_delay}s delay each)...")
        for i, lot in enumerate(lots, 1):
            title = lot.get("title") or ""
            print(f"  [{i}/{len(lots)}] {title[:60]}")
            lot["_ebay"] = ebay.search_sold(
                title,
                max_results=args.ebay_results,
                delay=args.ebay_delay,
            )
    else:
        for lot in lots:
            lot["_ebay"] = None

    # 3. HTML report (always)
    html_path = base + ".html"
    report.generate(lots, catalog_id, html_path)

    # 4. Optional CSV / JSON
    if args.csv:
        write_csv(lots, base + ".csv")
    if args.json:
        write_json(lots, base + ".json")

    # 5. Preview
    print(f"\nPreview — top 5 deals (by eBay value):")
    scored = []
    for lot in lots:
        eb  = lot.get("_ebay") or {}
        avg = eb.get("avg_price")
        bid = lot.get("current_bid")
        if avg and bid:
            try:
                scored.append((float(bid) / float(avg), lot))
            except (TypeError, ValueError):
                pass
    scored.sort(key=lambda x: x[0])
    shown = scored[:5] if scored else [(None, l) for l in lots[:5]]
    for ratio, lot in shown:
        eb    = lot.get("_ebay") or {}
        title = (lot.get("title") or "")[:55]
        bid   = lot.get("current_bid") or "—"
        avg   = eb.get("avg_price") or "—"
        pct   = f"{ratio*100:.0f}% of eBay avg" if ratio else ""
        print(f"  Lot {str(lot.get('lot_number') or '?'):>4}  bid ${bid:<8} eBay avg ${avg:<8}  {pct}  {title}")

    # 6. Open in browser
    if not args.no_open:
        webbrowser.open(f"file://{Path(html_path).resolve()}")


if __name__ == "__main__":
    main()
