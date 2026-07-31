# Instamart Data Scrapper Bot

A high-performance, parallelized web scraper that extracts **keyword search results** from [Swiggy Instamart](https://www.instamart.in) across multiple Indian cities simultaneously.

Built with **Playwright** and **asyncio**, this bot launches **5 Chrome windows in parallel** — each simulating a mobile device — to intercept Instamart's internal search API and extract clean, structured product data at scale.

---

## How It Works

```
                    +------------------+
                    |   extract.py     |
                    |  (Orchestrator)  |
                    +--------+---------+
                             |
              +--------------+--------------+
              |       |       |       |      |
           [W1]    [W2]    [W3]    [W4]   [W5]
          Chrome  Chrome  Chrome  Chrome  Chrome
          :9240   :9241   :9242   :9243   :9244
              |       |       |       |      |
              v       v       v       v      v
          City A   City B  City C  City D  City E
              \       \       |      /      /
               \       \      |     /      /
                +------+------+----+------+
                |   Shared CSV Writer     |
                |   (asyncio.Lock)        |
                +---------+---------------+
                          |
                          v
                 instamart_results.csv
```

### Architecture

1. **Mobile Browser Simulation** — Each Chrome window emulates a Pixel 8 Pro (Android 14) with Swiggy's mobile user-agent, touch support, and geolocation cookies.

2. **API Interception** — Instead of parsing HTML, the bot intercepts Instamart's internal `/api/instamart/search` network responses to capture clean JSON data directly from the API.

3. **Parallel Workers** — 5 async workers pull cities from a shared queue. Each worker opens its own isolated Chrome instance on a unique debug port.

4. **Thread-Safe CSV** — All workers write to a single output CSV through an `asyncio.Lock`-protected writer, ensuring no data corruption.

---

## Data Extracted

Each row in the output CSV contains:

| Field | Description |
|---|---|
| `location_name` | City/area name |
| `latitude` | GPS latitude of the location |
| `longitude` | GPS longitude of the location |
| `keyword` | Search term used |
| `product_position` | Rank position in search results |
| `brand` | Product brand name |
| `title` | Full product title |
| `mrp` | Maximum retail price |
| `offer_price` | Discounted/offer price |
| `is_ad` | Whether the listing is a paid ad |
| `productId` | Instamart product ID |
| `extraction_date` | Timestamp of data extraction |

---

## Setup

### Prerequisites

- **Python 3.10+**
- **Google Chrome** installed at `C:\Program Files\Google\Chrome\Application\chrome.exe`
- **Playwright** with Chromium

### Installation

```bash
# Clone the repo
git clone https://github.com/harshgupta170704/Instamart-Data-Scrapper-Bot-.git
cd Instamart-Data-Scrapper-Bot-

# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers (if not already installed)
playwright install chromium
```

---

## Usage

### Quick Start

```bash
python extract.py
```

This will:
- Load cities from `locations.csv` (76 locations across 15 cities)
- Load keywords from `keywords.txt` (29 search terms)
- Open 5 parallel Chrome windows
- Scrape all keyword x city combinations
- Save results to `~/Downloads/instamart_results_YYYYMMDD_HHMMSS.csv`

### Custom Options

```bash
# Use 3 workers instead of 5
python extract.py --workers 3

# Custom keywords file
python extract.py --keywords my_keywords.txt

# Custom locations and output directory
python extract.py --locations my_cities.csv --output C:\data

# All options combined
python extract.py --workers 4 --keywords kw.txt --locations cities.csv --output ./output
```

---

## Configuration Files

### `keywords.txt`

One keyword per line. The bot searches each keyword across every city.

```
trimmer
men trimmer
body trimmer
beard trimmer
bombay shaving company
...
```

### `locations.csv`

CSV with columns: `name`, `lat`, `lon`. Multiple entries per city represent different pin-code areas to capture location-specific inventory.

```csv
name,lat,lon
Bangalore,12.9352,77.6245
Mumbai,19.0596,72.8295
Pune,18.5362,73.8938
...
```

**Default coverage:** Bangalore, Mumbai, Pune, Thane, Hyderabad, Ahmedabad, Chennai, Gurgaon, Jaipur, Surat, Noida, West Delhi, Ernakulam, Ghaziabad, Kolkata (76 location points across 15 cities)

---

## Sample Output

A sample output CSV from a real scraping run is included in the `sample_output/` folder:

```
sample_output/
  instamart_results_sample.csv    (~36,000+ rows, 15 cities x 29 keywords)
```

---

## Performance

| Metric | Value |
|---|---|
| **Workers** | 5 parallel Chrome windows |
| **Cities** | 76 locations (15 cities) |
| **Keywords** | 29 search terms |
| **Total Searches** | 2,204 |
| **Records Extracted** | ~36,000+ per run |
| **Time** | ~22 minutes |

---

## Tech Stack

- **Python 3.12** — Core language
- **Playwright** — Browser automation (headful Chrome via CDP)
- **asyncio** — Concurrent parallel execution
- **subprocess** — Chrome process management
- **csv** — Data output with thread-safe writing

---

## Project Structure

```
Instamart-Data-Scrapper-Bot-/
|-- extract.py              # Main scraper bot (single file, fully self-contained)
|-- keywords.txt            # Search keywords (one per line)
|-- locations.csv           # City coordinates (name, lat, lon)
|-- requirements.txt        # Python dependencies
|-- sample_output/          # Example output from a real run
|   |-- instamart_results_sample.csv
|-- README.md
```

---

## License

This project is for **personal/educational use only**. Scraping third-party websites may violate their Terms of Service. Use responsibly.

---

## Author

**Harsh Gupta** — [GitHub](https://github.com/harshgupta170704)
