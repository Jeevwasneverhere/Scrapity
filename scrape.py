#!/usr/bin/env python3
"""price_pulse_v2.py - multi-marketplace price scraper with optional Gemini filter.

pip install curl_cffi beautifulsoup4 google-genai
Usage: python price_pulse_v2.py "wireless mouse" [--debug] [--no-ai] [--usd-inr 88]
"""
import argparse
import csv
import json
import os
import re
import sys
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

import bs4

try:
  from curl_cffi import requests as http  # Chrome TLS fingerprint

  IMPERSONATE = {"impersonate": "chrome"}
except ImportError:
  import requests as http

  IMPERSONATE = {}
  print("[warn] curl_cffi missing: Amazon/Flipkart will likely block. pip install curl_cffi")

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
BLOCK_MARKERS = (
    "Type the characters you see in this image",
    "Enter the characters you see below",
    "Pardon Our Interruption",
    "Pardon our interruption",
)
MAX_PER_SITE = 12
ACCESSORY_WORDS = {
    "case", "cover", "skin", "sticker", "keycap", "keycaps", "cable", "charger",
    "protector", "pouch", "bag", "stand", "pad", "dongle", "receiver", "battery",
    "replacement", "spare", "cleaner", "adapter", "holder", "mount",
}


def log(src, msg):
  print(f"[{src}] {msg}")


def parse_price(s: str) -> float:
  """First number in the string (handles '₹1,299.00', 'Rs. 999', '$10 to $20')."""
  m = re.search(r"\d[\d,]*\.?\d*", s or "")
  if not m:
    return float("inf")
  try:
    return float(m.group(0).replace(",", ""))
  except ValueError:
    return float("inf")


def fetch(name, url, debug=False, referer=None):
  headers = {"Accept-Language": "en-IN,en;q=0.9"}
  if referer:
    headers["Referer"] = referer
  if not IMPERSONATE:
    headers["User-Agent"] = UA
  for attempt in range(3):
    try:
      r = http.get(url, headers=headers, timeout=20, **IMPERSONATE)
    except Exception as e:
      log(name, f"request error: {e}")
      time.sleep(1.5 * (attempt + 1))
      continue
    text = r.text
    blocked = r.status_code != 200 or any(m in text for m in BLOCK_MARKERS)
    if debug:
      with open(f"debug_{name}.html", "w", encoding="utf-8") as f:
        f.write(text)
    if not blocked:
      return text
    log(name, f"blocked/status {r.status_code} (attempt {attempt + 1}/3)")
    time.sleep(2 * (attempt + 1))
  return None


def item(source, title, raw_price, link="", usd_inr=1.0):
  title = re.sub(r"\s+", " ", title or "").strip()
  price = parse_price(raw_price)
  if price == float("inf") or len(title) < 6:
    return None
  return {
      "source": source,
      "title": title,
      "raw_price": raw_price.strip(),
      "price_inr": round(price * usd_inr, 2),
      "link": link,
  }


def scrape_amazon(q, debug, **_):
  html = fetch("Amazon", f"https://www.amazon.in/s?k={q}", debug)
  if not html:
    return []
  soup = bs4.BeautifulSoup(html, "html.parser")
  out = []
  for card in soup.select('div[data-component-type="s-search-result"][data-asin]'):
    t = card.select_one("h2 span") or card.select_one("h2")
    p = card.select_one("span.a-price span.a-offscreen") or card.select_one("span.a-price-whole")
    a = card.select_one("h2 a") or card.select_one("a.a-link-normal")
    if not (t and p):
      continue
    link = urllib.parse.urljoin("https://www.amazon.in", a["href"]) if a and a.get("href") else ""
    it = item("Amazon", t.get_text(" ", strip=True), p.get_text(strip=True), link)
    if it:
      out.append(it)
    if len(out) >= MAX_PER_SITE:
      break
  return out


def scrape_flipkart(q, debug, **_):
  """Class names on Flipkart are obfuscated and rotate, so match structure:
  product links contain '/p/', and the nearest ancestor holding a rupee sign is the card."""
  html = fetch("Flipkart", f"https://www.flipkart.com/search?q={q}", debug,
               referer="https://www.flipkart.com/")
  if not html:
    return []
  soup = bs4.BeautifulSoup(html, "html.parser")
  out, seen = [], set()
  for a in soup.select('a[href*="/p/"]'):
    href = a.get("href", "").split("?")[0]
    if href in seen:
      continue
    card = a
    for _i in range(6):
      if "₹" in card.get_text():
        break
      card = card.parent
      if card is None:
        break
    if card is None or "₹" not in card.get_text():
      continue
    strings = list(card.stripped_strings)
    title = a.get("title") or next(
        (s for s in strings if len(s) > 15 and not s.startswith("₹")), "")
    pm = re.search(r"₹\s*[\d,]+(?:\.\d+)?", card.get_text(" "))
    if not pm:
      continue
    it = item("Flipkart", title, pm.group(0),
              urllib.parse.urljoin("https://www.flipkart.com", href))
    if it:
      seen.add(href)
      out.append(it)
    if len(out) >= MAX_PER_SITE:
      break
  return out


def scrape_snapdeal(q, debug, **_):
  html = fetch("Snapdeal", f"https://www.snapdeal.com/search?keyword={q}", debug)
  if not html:
    return []
  soup = bs4.BeautifulSoup(html, "html.parser")
  out = []
  for card in soup.select("div.product-tuple-listing")[:MAX_PER_SITE]:
    t = card.select_one("p.product-title")
    p = card.select_one("span.product-price") or card.select_one("[class*=product-price]")
    a = card.select_one("a.dp-widget-link") or card.select_one("a[href]")
    if t and p:
      it = item("Snapdeal", t.get_text(strip=True), p.get_text(strip=True),
                a["href"] if a and a.get("href") else "")
      if it:
        out.append(it)
  return out


def scrape_ebay(q, debug, usd_inr=88.0, **_):
  html = fetch("eBay", f"https://www.ebay.com/sch/i.html?_nkw={q}", debug)
  if not html:
    return []
  soup = bs4.BeautifulSoup(html, "html.parser")
  cards = soup.select("li.s-card") or soup.select("li.s-item")  # new / old layout
  out = []
  for c in cards:
    t = c.select_one(".s-card__title") or c.select_one(".s-item__title")
    p = c.select_one(".s-card__price") or c.select_one(".s-item__price")
    a = c.select_one("a.su-link") or c.select_one("a.s-item__link") or c.select_one("a[href]")
    if not (t and p):
      continue
    title = t.get_text(" ", strip=True)
    title = re.sub(r"Opens in a new window or tab|^New Listing", "", title).strip()
    if title.lower().startswith("shop on ebay"):
      continue
    it = item("eBay", title, p.get_text(" ", strip=True),
              a["href"] if a and a.get("href") else "", usd_inr=usd_inr)
    if it:
      out.append(it)
    if len(out) >= MAX_PER_SITE:
      break
  return out


def local_filter(query, items):
  """No-API fallback: title must share >=half the query tokens and not be an accessory."""
  toks = [t for t in re.findall(r"\w+", query.lower()) if len(t) > 1]
  keep = []
  for it in items:
    words = set(re.findall(r"\w+", it["title"].lower()))
    hit = sum(1 for t in toks if t in words)
    q_has_acc = any(t in ACCESSORY_WORDS for t in toks)
    if toks and hit * 2 >= len(toks) and (q_has_acc or not (words & ACCESSORY_WORDS)):
      keep.append(it)
  return keep


def ai_filter(query, items, api_key):
  """Send only indexed titles, get back only indices: cheaper, faster, can't corrupt data."""
  from google import genai
  from google.genai import types

  model = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")  # verify this id exists
  client = genai.Client(api_key=api_key)
  listing = "\n".join(f"{i}: {it['title'][:160]}" for i, it in enumerate(items))
  prompt = (
      f'Search query: "{query}"\n'
      "Below are indexed product titles. Return a JSON array of the indices that are "
      "the actual main product matching the query. Exclude accessories, parts, covers, "
      "cables, cleaning tools and unrelated items.\n\n" + listing
  )
  for attempt in range(3):
    try:
      resp = client.models.generate_content(
          model=model,
          contents=prompt,
          config=types.GenerateContentConfig(
              response_mime_type="application/json",
              response_schema=list[int],
              temperature=0.0,
          ),
      )
      idx = json.loads(resp.text)
      return [items[i] for i in idx if isinstance(i, int) and 0 <= i < len(items)]
    except Exception as e:
      print(f"[AI] attempt {attempt + 1} failed: {e}")
      time.sleep(2)
  return None  # caller falls back to local_filter


def main():
  ap = argparse.ArgumentParser()
  ap.add_argument("query", nargs="+")
  ap.add_argument("--debug", action="store_true", help="dump debug_<site>.html per site")
  ap.add_argument("--no-ai", action="store_true")
  ap.add_argument("--usd-inr", type=float, default=88.0, help="USD->INR rate for eBay")
  args = ap.parse_args()

  query = " ".join(args.query)
  enc = urllib.parse.quote_plus(query)
  scrapers = [scrape_amazon, scrape_flipkart, scrape_snapdeal, scrape_ebay]
  print(f"Scanning for: {query!r}\n" + "-" * 60)

  with ThreadPoolExecutor(max_workers=4) as ex:
    futs = [(fn.__name__, ex.submit(fn, enc, args.debug, usd_inr=args.usd_inr)) for fn in scrapers]
    raw = []
    for name, f in futs:
      try:
        res = f.result()
      except Exception as e:
        print(f"[{name}] crashed: {e}")
        res = []
      print(f"{name:<18} -> {len(res)} items")
      raw.extend(res)

  print(f"\nRaw total: {len(raw)}")
  if not raw:
    print("Nothing scraped. Re-run with --debug and inspect debug_*.html")
    sys.exit(1)

  valid = None
  api_key = os.environ.get("GEMINI_API_KEY")
  if api_key and not args.no_ai:
    valid = ai_filter(query, raw, api_key)
  if valid is None:
    print("Using local keyword filter (no AI).")
    valid = local_filter(query, raw)
  print(f"After filter: {len(valid)}")
  if not valid:
    print("Zero items passed filter.")
    sys.exit(1)

  valid.sort(key=lambda x: x["price_inr"])
  fname = "report_" + re.sub(r"\W+", "_", query).strip("_") + ".csv"
  with open(fname, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["Marketplace", "Title", "Listed price", "Price INR", "Link"])
    for p in valid:
      w.writerow([p["source"], p["title"], p["raw_price"], p["price_inr"], p["link"]])

  print("=" * 68)
  for i, p in enumerate(valid, 1):
    print(f"{i:>2}. [{p['source']:<8}] {p['title'][:45]:<45} ₹{p['price_inr']:,.0f}")
  b = valid[0]
  print("-" * 68)
  print(f"Best: {b['title'][:60]} on {b['source']} for ₹{b['price_inr']:,.0f}")
  print(f"CSV: {fname}")


if __name__ == "__main__":
  main()