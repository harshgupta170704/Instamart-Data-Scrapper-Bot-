"""
Instamart Keyword Search - Extract Module (Parallel)
=====================================================
Uses Playwright with API interception to extract keyword search data
from Swiggy Instamart (instamart.in) across multiple locations.

Performance: Runs 5 Chrome windows in parallel, each handling a
separate city. Cities are distributed across workers in round-robin.
A single shared CSV file is written to with a thread-safe lock.

Approach: Mobile browser simulation + network call interception.
The script intercepts Instamart's internal search API responses to get
clean structured JSON data instead of parsing HTML.

Usage:
    python extract.py
    python extract.py --workers 3        # use 3 windows instead of 5
    python extract.py --keywords kw.txt  # custom keywords file
    python extract.py --locations loc.csv --output C:\\data
"""
import asyncio
import argparse
import json
import os
import urllib.parse
import tempfile
import subprocess
import csv
import random
import sys
from datetime import datetime
from playwright.async_api import async_playwright


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
BASE_DEBUG_PORT = 9240  # Workers use ports 9240, 9241, 9242, 9243, 9244
MAX_WORKERS = 5

MOBILE_DEVICE = {
    "viewport": {"width": 393, "height": 852},
    "device_scale_factor": 3,
    "is_mobile": True,
    "has_touch": True,
    "user_agent": (
        "Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.6422.165 Mobile Safari/537.36 Swiggy/5.45.0"
    ),
}

MOBILE_PLATFORM_COOKIES = [
    {"name": "platform", "value": "android", "domain": ".instamart.in", "path": "/"},
    {"name": "subplatform", "value": "", "domain": ".instamart.in", "path": "/"},
    {"name": "isNative", "value": "true", "domain": ".instamart.in", "path": "/"},
]


# ---------------------------------------------------------------------------
# Default 15 major Indian cities with lat/lng
# ---------------------------------------------------------------------------
DEFAULT_CITIES = [
    {"name": "Mumbai", "lat": "19.0760", "lng": "72.8777"},
    {"name": "Delhi", "lat": "28.7041", "lng": "77.1025"},
    {"name": "Bangalore", "lat": "12.9716", "lng": "77.5946"},
    {"name": "Hyderabad", "lat": "17.3850", "lng": "78.4867"},
    {"name": "Chennai", "lat": "13.0827", "lng": "80.2707"},
    {"name": "Kolkata", "lat": "22.5726", "lng": "88.3639"},
    {"name": "Pune", "lat": "18.5204", "lng": "73.8567"},
    {"name": "Ahmedabad", "lat": "23.0225", "lng": "72.5714"},
    {"name": "Jaipur", "lat": "26.9124", "lng": "75.7873"},
    {"name": "Surat", "lat": "21.1702", "lng": "72.8311"},
    {"name": "Lucknow", "lat": "26.8467", "lng": "80.9462"},
    {"name": "Kanpur", "lat": "26.4499", "lng": "80.3319"},
    {"name": "Nagpur", "lat": "21.1458", "lng": "79.0882"},
    {"name": "Indore", "lat": "22.7196", "lng": "75.8577"},
    {"name": "Chandigarh", "lat": "30.7333", "lng": "76.7794"},
]


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def load_locations(file_path=None):
    """Load locations from a CSV file (columns: lat, lon, name) or use defaults."""
    if file_path and os.path.exists(file_path):
        locations = []
        with open(file_path, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if 'lat' in row and 'lon' in row:
                    locations.append({
                        "name": row.get('name', f"{row['lat']},{row['lon']}"),
                        "lat": row['lat'].strip(),
                        "lng": row['lon'].strip(),
                    })
        if locations:
            return locations
    return DEFAULT_CITIES


def load_keywords(file_path=None):
    """Load keywords from a text file (one per line) or return empty list."""
    keywords = []
    if file_path and os.path.exists(file_path):
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                kw = line.strip()
                if kw:
                    keywords.append(kw)
    return keywords


# ---------------------------------------------------------------------------
# Thread-safe CSV writer
# ---------------------------------------------------------------------------
CSV_COLUMNS = [
    "location_name", "latitude", "longitude", "keyword", "product_position",
    "brand", "title", "mrp", "offer_price", "is_ad", "productId",
    "extraction_date",
]


class CSVWriter:
    """Async-safe CSV writer that appends rows to a shared file."""

    def __init__(self, csv_path):
        self.path = csv_path
        self.lock = asyncio.Lock()
        self.total_rows = 0
        self._initialized = False

    async def write_rows(self, rows):
        if not rows:
            return
        async with self.lock:
            with open(self.path, 'a', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, CSV_COLUMNS)
                if not self._initialized:
                    writer.writeheader()
                    self._initialized = True
                writer.writerows(rows)
            self.total_rows += len(rows)


# ---------------------------------------------------------------------------
# Core scraping functions
# ---------------------------------------------------------------------------

async def search_keyword_on_page(page, loc, keyword):
    """
    Search a single keyword on an already-open Instamart mobile page.
    Intercepts the /api/instamart/search network response for structured data.
    Returns a list of product dicts.
    """
    captured = []
    evt = asyncio.Event()

    async def handler(response):
        if "/api/instamart/search" in response.url and response.status == 200:
            try:
                body = await response.text()
                captured.append(json.loads(body))
                evt.set()
            except Exception:
                pass

    page.on("response", handler)

    encoded = urllib.parse.quote(keyword)
    search_url = f"https://www.instamart.in/search?query={encoded}&custom_back=true"
    await page.goto(search_url, wait_until='domcontentloaded')

    try:
        await asyncio.wait_for(evt.wait(), timeout=12.0)
    except asyncio.TimeoutError:
        pass

    await page.wait_for_timeout(800)
    page.remove_listener("response", handler)

    results = []
    if captured:
        data = captured[-1]
        cards = data.get('data', {}).get('cards', [])
        position = 1
        for c in cards:
            card_data = c.get('card', {}).get('card', {}) if 'card' in c else c
            if 'gridElements' in card_data:
                items = card_data['gridElements'].get('infoWithStyle', {}).get('items', [])
                for item in items:
                    is_ad = bool(item.get('adTrackingContext'))
                    variations = item.get('variations', [])
                    if not variations:
                        continue
                    var = variations[0]
                    title = var.get('displayName', '')
                    brand = var.get('brandName', '')
                    mrp = var.get('price', {}).get('mrp', {}).get('units', '0')
                    offer = var.get('price', {}).get('offerPrice', {}).get('units', mrp)
                    product_id = var.get('id', '')

                    results.append({
                        "location_name": loc["name"],
                        "latitude": loc["lat"],
                        "longitude": loc["lng"],
                        "keyword": keyword,
                        "product_position": position,
                        "brand": brand,
                        "title": title,
                        "mrp": mrp,
                        "offer_price": offer,
                        "is_ad": is_ad,
                        "productId": product_id,
                        "extraction_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    })
                    position += 1
    return results


async def scrape_single_city(p, loc, keywords, debug_port, csv_writer, worker_id):
    """
    Open a Chrome instance for one city, run ALL keywords, write results
    to the shared CSV, then tear down the browser.
    """
    city_start = datetime.now()
    print(f"  [W{worker_id}] Starting city: {loc['name']} (port {debug_port})")

    safe_name = "".join(c if c.isalnum() else "_" for c in loc['name'])
    chrome_user_data = os.path.join(
        tempfile.gettempdir(), f"chrome_instamart_w{worker_id}_{safe_name}"
    )

    chrome_args = [
        CHROME_PATH, f"--remote-debugging-port={debug_port}",
        f"--user-data-dir={chrome_user_data}",
        "--no-first-run", "--no-default-browser-check", "about:blank",
    ]
    chrome_proc = subprocess.Popen(chrome_args)
    await asyncio.sleep(3)

    city_results = []
    try:
        browser = await p.chromium.connect_over_cdp(f"http://localhost:{debug_port}")
        context = await browser.new_context(
            viewport=MOBILE_DEVICE["viewport"],
            device_scale_factor=MOBILE_DEVICE["device_scale_factor"],
            is_mobile=MOBILE_DEVICE["is_mobile"],
            has_touch=MOBILE_DEVICE["has_touch"],
            user_agent=MOBILE_DEVICE["user_agent"],
        )

        await context.add_cookies([
            {"name": "lat", "value": loc["lat"], "domain": ".instamart.in", "path": "/"},
            {"name": "lng", "value": loc["lng"], "domain": ".instamart.in", "path": "/"},
            {"name": "_device_id", "value": f"worker-{worker_id}-{safe_name}",
             "domain": ".instamart.in", "path": "/"},
        ] + MOBILE_PLATFORM_COOKIES)

        page = await context.new_page()
        geo_script = f"""
            navigator.geolocation.getCurrentPosition = function(success) {{
                success({{ coords: {{ latitude: {loc['lat']}, longitude: {loc['lng']},
                           accuracy: 50 }}, timestamp: Date.now() }});
            }};
        """
        await page.add_init_script(geo_script)

        # Establish session
        await page.goto('https://www.instamart.in/', wait_until='domcontentloaded')
        await page.wait_for_timeout(2500)

        # Run all keywords sequentially on this city's browser
        for kw_idx, kw in enumerate(keywords, 1):
            try:
                data = await search_keyword_on_page(page, loc, kw)
                city_results.extend(data)
                print(f"  [W{worker_id}] {loc['name']} | {kw_idx}/{len(keywords)} "
                      f"\"{kw}\" -> {len(data)} items")
            except Exception as e:
                print(f"  [W{worker_id}] {loc['name']} | {kw_idx}/{len(keywords)} "
                      f"\"{kw}\" -> ERROR: {e}")

        await context.close()
        await browser.close()
    except Exception as e:
        print(f"  [W{worker_id}] Error scraping {loc['name']}: {e}")
    finally:
        chrome_proc.terminate()
        try:
            chrome_proc.wait(timeout=5)
        except Exception:
            chrome_proc.kill()

    # Write city results to shared CSV
    await csv_writer.write_rows(city_results)
    elapsed = (datetime.now() - city_start).total_seconds()
    print(f"  [W{worker_id}] [Done] {loc['name']} finished: {len(city_results)} rows "
          f"in {elapsed:.0f}s  (Total: {csv_writer.total_rows})")

    return city_results


async def worker_loop(p, worker_id, debug_port, city_queue, keywords, csv_writer):
    """
    Worker coroutine: keeps pulling cities from the shared queue and
    scraping them one at a time until the queue is empty.
    """
    while True:
        try:
            city = city_queue.pop(0)
        except IndexError:
            break  # No more cities
        await scrape_single_city(p, city, keywords, debug_port, csv_writer, worker_id)
        # Small delay between cities to avoid overwhelming the system
        await asyncio.sleep(random.uniform(1, 2))


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def run_extraction(
    locations_csv=None,
    keywords_file=None,
    output_dir=None,
    num_workers=MAX_WORKERS,
):
    """
    Run the full extraction pipeline with parallel Chrome windows.

    Args:
        locations_csv: Path to CSV with lat, lon, name columns.
        keywords_file: Path to text file with one keyword per line.
        output_dir:    Directory to save the output CSV.
        num_workers:   Number of parallel Chrome windows (default 5).
    """
    locations = load_locations(locations_csv)
    keywords = load_keywords(keywords_file)

    if not keywords:
        print("ERROR: No keywords provided.")
        print("Place a 'keywords.txt' file (one keyword per line) in:")
        print("  - Same folder as this script, OR")
        print("  - Your Downloads folder")
        return None

    if not output_dir:
        output_dir = os.getcwd()

    # Cap workers to number of cities (no point having idle workers)
    num_workers = min(num_workers, len(locations))

    print()
    print("=" * 60)
    print("  Instamart Keyword Search Scraper (Parallel)")
    print("=" * 60)
    print(f"  Cities       : {len(locations)}")
    print(f"  Keywords     : {len(keywords)}")
    print(f"  Total searches: {len(locations) * len(keywords)}")
    print(f"  Workers      : {num_workers} parallel Chrome windows")
    print(f"  Output dir   : {output_dir}")
    print("=" * 60)
    print()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_file = os.path.join(output_dir, f"instamart_results_{timestamp}.csv")
    csv_writer = CSVWriter(csv_file)

    # Shared mutable list used as a queue (workers pop from front)
    city_queue = list(locations)

    start_time = datetime.now()

    async with async_playwright() as p:
        # Launch all workers concurrently
        tasks = []
        for w in range(num_workers):
            port = BASE_DEBUG_PORT + w
            task = asyncio.create_task(
                worker_loop(p, w + 1, port, city_queue, keywords, csv_writer)
            )
            tasks.append(task)
            # Stagger launches by 2 seconds so Chrome instances don't collide
            await asyncio.sleep(2)

        # Wait for all workers to finish
        await asyncio.gather(*tasks)

    elapsed = (datetime.now() - start_time).total_seconds()
    mins = int(elapsed // 60)
    secs = int(elapsed % 60)

    print()
    print("=" * 60)
    print("  [Done] Scraping Completed!")
    print(f"  Total records : {csv_writer.total_rows}")
    print(f"  Time taken    : {mins}m {secs}s")
    print(f"  Saved to      : {csv_file}")
    print("=" * 60)
    return csv_file


def main():
    parser = argparse.ArgumentParser(
        description="Instamart keyword search scraper with parallel Chrome windows"
    )
    parser.add_argument(
        "--workers", type=int, default=MAX_WORKERS,
        help=f"Number of parallel Chrome windows (default: {MAX_WORKERS})"
    )
    parser.add_argument(
        "--keywords", type=str, default=None,
        help="Path to keywords.txt file (one keyword per line)"
    )
    parser.add_argument(
        "--locations", type=str, default=None,
        help="Path to locations.csv file (columns: name, lat, lon)"
    )
    parser.add_argument(
        "--output", type=str, default=None,
        help="Output directory for CSV results (default: ~/Downloads)"
    )
    args = parser.parse_args()

    # Resolve file paths with fallbacks
    kw_file = args.keywords
    loc_file = args.locations
    output = args.output

    if not kw_file:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        kw_file = os.path.join(script_dir, "keywords.txt")
        if not os.path.exists(kw_file):
            kw_file = os.path.expanduser(r"~\Downloads\keywords.txt")

    if not loc_file:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        loc_file = os.path.join(script_dir, "locations.csv")
        if not os.path.exists(loc_file):
            loc_file = None  # Will use default 15 cities

    if not output:
        output = os.path.expanduser(r"~\Downloads")

    asyncio.run(run_extraction(
        locations_csv=loc_file,
        keywords_file=kw_file,
        output_dir=output,
        num_workers=args.workers,
    ))


if __name__ == "__main__":
    main()
