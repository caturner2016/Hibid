"""Generate a self-contained HTML report comparing HiBid lots with eBay solds."""

from datetime import datetime


_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
       background: #f4f5f7; color: #1a1a2e; }
header { background: #1a1a2e; color: #fff; padding: 18px 28px; }
header h1 { font-size: 1.3rem; font-weight: 600; }
header p  { font-size: 0.85rem; opacity: 0.7; margin-top: 4px; }
.grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
    gap: 18px;
    padding: 22px 28px;
}
.card {
    background: #fff;
    border-radius: 10px;
    box-shadow: 0 1px 4px rgba(0,0,0,.10);
    overflow: hidden;
    display: flex;
    flex-direction: column;
}
.card-img {
    width: 100%;
    height: 220px;
    object-fit: cover;
    background: #e8e8e8;
    display: block;
}
.card-img-placeholder {
    width: 100%;
    height: 220px;
    background: #e8e8e8;
    display: flex;
    align-items: center;
    justify-content: center;
    color: #aaa;
    font-size: 0.85rem;
}
.card-body { padding: 14px 16px; flex: 1; display: flex; flex-direction: column; gap: 10px; }
.lot-header { display: flex; justify-content: space-between; align-items: flex-start; gap: 8px; }
.lot-number { font-size: 0.72rem; font-weight: 700; color: #888;
              text-transform: uppercase; letter-spacing: .05em; white-space: nowrap; }
.lot-title  { font-size: 0.95rem; font-weight: 600; line-height: 1.35; }
.bid-row    { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
.bid-label  { font-size: 0.75rem; color: #888; }
.bid-value  { font-size: 1.05rem; font-weight: 700; }
.verdict {
    display: inline-block;
    padding: 3px 10px;
    border-radius: 20px;
    font-size: 0.75rem;
    font-weight: 700;
    letter-spacing: .03em;
}
.verdict-great  { background: #d4f7dc; color: #1a7a3a; }
.verdict-good   { background: #fff3cd; color: #7a5a00; }
.verdict-caution{ background: #fde8e8; color: #a02020; }
.verdict-nodata { background: #eee;    color: #888; }
.ebay-section { border-top: 1px solid #f0f0f0; padding-top: 10px; }
.ebay-header  { font-size: 0.75rem; font-weight: 700; color: #888;
                text-transform: uppercase; letter-spacing: .05em; margin-bottom: 6px; }
.ebay-stats   { font-size: 0.85rem; color: #555; margin-bottom: 6px; }
.ebay-stats strong { color: #1a1a2e; }
.ebay-list    { list-style: none; display: flex; flex-direction: column; gap: 3px; }
.ebay-list li { font-size: 0.80rem; color: #444; }
.ebay-list li a { color: #0064d2; text-decoration: none; }
.ebay-list li a:hover { text-decoration: underline; }
.ebay-list li .price { font-weight: 600; color: #1a7a3a; margin-right: 4px; }
.ebay-search-link { font-size: 0.75rem; color: #0064d2; text-decoration: none; margin-top: 4px; display: inline-block; }
.card-footer { padding: 10px 16px; border-top: 1px solid #f0f0f0; }
.lot-link { font-size: 0.78rem; color: #0064d2; text-decoration: none; }
.lot-link:hover { text-decoration: underline; }
.summary-bar {
    background: #fff; border-bottom: 1px solid #e0e0e0;
    padding: 10px 28px; display: flex; gap: 28px; font-size: 0.85rem; color: #555;
}
.summary-bar strong { color: #1a1a2e; }
"""

_VERDICT_TABLE = [
    (0.50, "great",   "Great deal"),
    (0.80, "good",    "Good deal"),
    (1.00, "caution", "Fair / Overbid"),
]


def _verdict(current_bid, avg_ebay):
    if current_bid is None or avg_ebay is None or avg_ebay == 0:
        return "nodata", "No eBay data"
    ratio = float(current_bid) / float(avg_ebay)
    for threshold, key, label in _VERDICT_TABLE:
        if ratio <= threshold:
            return key, label
    return "caution", "At/Above market"


def _fmt_price(val):
    if val is None:
        return "—"
    try:
        return f"${float(val):,.2f}"
    except (ValueError, TypeError):
        return str(val)


def _card_html(lot: dict) -> str:
    ebay  = lot.get("_ebay") or {}
    title = lot.get("title") or "Untitled"
    num   = lot.get("lot_number") or lot.get("lot_id") or "?"
    bid   = lot.get("current_bid")
    img   = lot.get("image_url")
    url   = lot.get("url") or "#"
    avg   = ebay.get("avg_price")
    vkey, vlabel = _verdict(bid, avg)

    # Image
    if img:
        img_html = f'<img class="card-img" src="{img}" alt="{title}" loading="lazy" onerror="this.style.display=\'none\';this.nextSibling.style.display=\'flex\'">\n<div class="card-img-placeholder" style="display:none">No image</div>'
    else:
        img_html = '<div class="card-img-placeholder">No image</div>'

    # Current bid
    bid_html = f'<span class="bid-value">{_fmt_price(bid)}</span>' if bid else '<span class="bid-value" style="color:#aaa">No bid yet</span>'

    # eBay section
    results = ebay.get("results") or []
    search_url = ebay.get("search_url") or ""

    if results:
        stats = (
            f'<div class="ebay-stats">'
            f'Avg <strong>{_fmt_price(avg)}</strong> &nbsp;·&nbsp; '
            f'Range {_fmt_price(ebay.get("min_price"))}–{_fmt_price(ebay.get("max_price"))}'
            f'</div>'
        )
        items_html = "\n".join(
            f'<li>'
            f'<span class="price">{_fmt_price(s["price"])}</span>'
            f'<a href="{s["url"]}" target="_blank" rel="noopener">{s["title"][:55]}</a>'
            f'{(" — " + s["date"]) if s.get("date") else ""}'
            f'</li>'
            for s in results
        )
        ebay_html = (
            f'<div class="ebay-section">'
            f'<div class="ebay-header">eBay Solds</div>'
            f'{stats}'
            f'<ul class="ebay-list">{items_html}</ul>'
            f'{"<a class=ebay-search-link href=" + repr(search_url) + " target=_blank>View all on eBay →</a>" if search_url else ""}'
            f'</div>'
        )
    elif search_url:
        ebay_html = (
            f'<div class="ebay-section">'
            f'<div class="ebay-header">eBay Solds</div>'
            f'<div class="ebay-stats" style="color:#aaa">No recent solds found</div>'
            f'<a class="ebay-search-link" href="{search_url}" target="_blank" rel="noopener">Search eBay →</a>'
            f'</div>'
        )
    else:
        ebay_html = ""

    return f"""
<div class="card">
  {img_html}
  <div class="card-body">
    <div class="lot-header">
      <div>
        <div class="lot-number">Lot {num}</div>
        <div class="lot-title">{title}</div>
      </div>
      <span class="verdict verdict-{vkey}">{vlabel}</span>
    </div>
    <div class="bid-row">
      <span class="bid-label">Current bid</span>
      {bid_html}
      {(f'<span class="bid-label">/ eBay avg {_fmt_price(avg)}</span>') if avg else ''}
    </div>
    {ebay_html}
  </div>
  <div class="card-footer">
    <a class="lot-link" href="{url}" target="_blank" rel="noopener">View lot on HiBid →</a>
  </div>
</div>
"""


def generate(lots: list[dict], catalog_id: str, output_path: str):
    total = len(lots)
    with_ebay   = sum(1 for l in lots if l.get("_ebay", {}).get("results"))
    with_bids   = sum(1 for l in lots if l.get("current_bid"))
    scraped_at  = datetime.now().strftime("%Y-%m-%d %H:%M")

    cards = "\n".join(_card_html(lot) for lot in lots)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>HiBid {catalog_id} — eBay Comparison</title>
<style>{_CSS}</style>
</head>
<body>
<header>
  <h1>HiBid Catalog {catalog_id}</h1>
  <p>Scraped {scraped_at}</p>
</header>
<div class="summary-bar">
  <span><strong>{total}</strong> lots</span>
  <span><strong>{with_bids}</strong> with bids</span>
  <span><strong>{with_ebay}</strong> with eBay comps</span>
</div>
<div class="grid">
{cards}
</div>
</body>
</html>"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Report saved → {output_path}")
