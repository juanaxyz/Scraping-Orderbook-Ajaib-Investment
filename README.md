# Stock Orderbook Scraper - Complete Documentation

## Overview

This project provides complete web scraping solutions for collecting real-time orderbook data from two major Indonesian investment platforms:

1. **Ajaib Scraper** (`main.py`) - Scrapes from Ajaib investment platform via API
2. **IPOT Scraper** (`ipot_scrapping.py`) - Scrapes from Indo Premier Online Trading via web interface
3. **Pangdat Scraper** (`pangdat-scraping.py`) - Advanced browser-based scraper for Ajaib orderbook
4. **Filter GUI** (`filter.py`) - Interactive GUI tool for querying and exporting scraped data

All data is stored in MySQL database for analysis and reporting.

---

## Table of Contents

- [Quick Start](#quick-start)
- [Ajaib Scraper (main.py)](#ajaib-scraper-mainpy)
- [IPOT Scraper (ipot_scrapping.py)](#ipot-scraper-ipot_scrappingpy)
- [Installation & Setup](#installation--setup)
- [Configuration](#configuration)
- [Database Schema](#database-schema)
- [Usage Examples](#usage-examples)
- [Filter GUI](#filter-gui)
- [Architecture & Performance](#architecture--performance)
- [Troubleshooting](#troubleshooting)
- [Project Structure](#project-structure)

---

## Quick Start

### Prerequisites
- Python 3.8+
- MySQL 5.7+ or MariaDB 10.3+
- Firefox & Chromium browsers (for Playwright)

### Installation

```bash
# Clone repository
git clone <repository-url>
cd Scraping-Orderbook-Ajaib-Investment

# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers
playwright install firefox chromium

# Create .env file with credentials
cp .env.example .env
```

### Run Scrapers

```bash
# Ajaib scraper (API-based)
python main.py

# IPOT scraper (web-based)
python ipot_scrapping.py

# Ajaib advanced scraper (Playwright-based)
python pangdat-scraping.py

# Scheduled execution (runs both)
python worker.py -i 900  # Run every 15 minutes
```

---

## Ajaib Scraper (main.py)

### Overview

Scrapes orderbook data from **Ajaib investment platform** using HTTP API requests. Uses header interception to capture authentication tokens, then fetches data in batches with automatic re-login on token expiration.


### Key Features

✅ API-based approach (faster than web scraping)  
✅ Automatic re-login on 401 Unauthorized  
✅ Rate limit handling (429 responses)  
✅ Batch processing with configurable concurrency  
✅ Real-time data parsing  
✅ MySQL database integration  

### How It Works

#### Phase 1: Authentication
```python
# Logs into Ajaib platform via Playwright
# Intercepts API requests to capture JWT token and headers
headers = await login_and_get_headers(p)
```

#### Phase 2: Data Fetching
```python
# Fetches orderbook data for all stocks in batches
# Automatically re-logs in if token expires (401 error)
results = await fetch_batch_with_relogin(p, CODES, headers)
```

#### Phase 3: Data Processing & Storage
```python
# Parses JSON responses into DataFrame format
# Inserts into MySQL database
push_to_database(final_df)
```

### Configuration

Edit `main.py`:

```python
# API endpoint
URL = "https://ht2.ajaib.co.id/api/v1/stock/bestquote/"

# Rate limiting
MAX_CONCURRENT = 5              # Concurrent requests
DELAY_BETWEEN_REQUESTS = 0.2    # 200ms between requests
RETRY_ON_429_DELAY = 5          # Wait time on rate limit (seconds)

# Stock list
CODES = pd.read_excel("Daftar 10 Saham.xlsx")["Kode"].tolist()
```

### Data Structure

**Input JSON from API:**
```json
{
  "code": "BBCA",
  "buy_side": {
    "unix_time": 1673420400000,
    "items": [
      {"price": 16500, "lot": 234, "num": 1},
      {"price": 16400, "lot": 456, "num": 2}
    ]
  },
  "sell_side": {
    "unix_time": 1673420400000,
    "items": [
      {"price": 16600, "lot": 123, "num": 1},
      {"price": 16700, "lot": 789, "num": 2}
    ]
  }
}
```

**Parsed Output:**
```python
{
  'kode': 'BBCA',
  'side': 'B',              # 'B' for Bid, 'S' for Ask/Sell
  'price': 16500,
  'lot': 234,
  'num': 1,
  'timestamp': datetime(2023, 1, 11, 6, 0, 0)
}
```

### Usage Example

```bash
python main.py
```

**Expected Output:**
```
============================================================
🔐 Login Ajaib via Playwright...
✅ Login sukses
📡 Triggering API request...
✅ Headers captured successfully!

📋 Using headers:
   Authorization: Bearer eyJhbGc...
   X-Device-Signature: xyz...
============================================================

🚀 Starting to fetch 10 codes...
⚙️  Config: 5 concurrent, 0.2s delay

📦 Processing batch 1/2 (10 codes)
✅ BBCA success - 8 rows
✅ BBRI success - 6 rows
...

============================================================
✅ SUCCESS!
📊 Saved 156 rows to saham_idx.csv
📈 Success rate: 10/10 (100.0%)
============================================================
```

### Error Handling

| Error | Handling |
|-------|----------|
| **401 Unauthorized** | Automatic re-login with new token |
| **429 Rate Limited** | Exponential backoff (5s, 10s, 15s...) |
| **Connection Error** | Retry with delay |
| **Invalid Data Format** | Skip record and log |

---

## IPOT Scraper (ipot_scrapping.py)

### Overview

Scrapes orderbook and market data from **Indo Premier Online Trading (IPOT)** platform using Playwright. Uses parallel browser instances to efficiently collect orderbook depth data.

**Status**: ✅ *Production Ready*

### Key Features

✅ Multi-browser parallel scraping  
✅ Orderbook depth (5 levels bid/ask)  
✅ Market overview data (price, high, low, etc.)  
✅ Automatic retry with exponential backoff  
✅ Resource optimization (blocks images/fonts)  
✅ Excel-based stock list support  
✅ Comprehensive error logging  

### How It Works

#### Phase 1: Initialization
```python
# Load stock list from Excel file
STOCK_LIST = load_stock_list()  # e.g., ['BBCA', 'BBRI', 'TLKM']
```

#### Phase 2: Parallel Scraping
```python
# Distribute stocks among multiple Firefox browsers
# Each browser handles up to 5 concurrent pages
# Total concurrency = NUM_BROWSERS × MAX_CONCURRENT_PER_BROWSER
#   Example: 2 browsers × 5 concurrent = 10 parallel pages
success, failed = await scrape_all(p, STOCK_LIST)
```

#### Phase 3: Data Transformation & Storage
```python
# Transform scraped data into database format
rows = flatten_rows(success)                    # Bid/Ask levels
market_data_rows = flatten_market_data(success) # Market overview

# Insert into MySQL
push_to_database(rows, market_data_rows)
```

### Configuration

Edit `ipot_scrapping.py`:

```python
# Stock list source
STOCK_FILE = "Daftar 10 Saham.xlsx"     # Small test file
# STOCK_FILE = "Daftar 955 Saham.xlsx"  # Full production file

# Browser configuration
NUM_BROWSERS = 2                        # Number of parallel browser instances
MAX_CONCURRENT_PER_BROWSER = 5          # Concurrent pages per browser
MAX_RETRIES = 3                         # Retry attempts on failure
PAGE_TIMEOUT = 30000                    # Page load timeout (30 seconds)
HEADLESS = True                         # Run browsers without GUI

# Performance Tips:
# - Total concurrency = NUM_BROWSERS × MAX_CONCURRENT_PER_BROWSER
# - For 100 stocks: NUM_BROWSERS=4, MAX_CONCURRENT_PER_BROWSER=5 (20 concurrent)
# - For 955 stocks: NUM_BROWSERS=8, MAX_CONCURRENT_PER_BROWSER=10 (80 concurrent)
```

### Data Collection

**Orderbook Data** (orderbook_ipot table):
```
Stock: BBCA, Timestamp: 2024-01-15 09:30:45

BID SIDE (Buy Orders)           ASK SIDE (Sell Orders)
Level 1:  16500 @ 234 lots      Level 1:  16600 @ 123 lots
Level 2:  16400 @ 456 lots      Level 2:  16700 @ 789 lots
Level 3:  16300 @ 789 lots      Level 3:  16800 @ 456 lots
Level 4:  16200 @ 234 lots      Level 4:  16900 @ 234 lots
Level 5:  16100 @ 567 lots      Level 5:  17000 @ 567 lots

Total Bid Lot: 2,280
Total Ask Lot: 2,069
```

**Market Data** (ipot_overview table):
```
Last Price: 16550
High:       16750
Low:        16200
Bid Qty:    2280
H.Bid:      16500
Timestamp:  2024-01-15 09:30:45
```

### Scraping Process

#### Step 1: Navigate to Stock Page
```python
url = f"https://indopremier.com/#ipot/app/ipotbuzz/home/{stock_code}"
await page.goto(url, wait_until="domcontentloaded")
```

#### Step 2: Extract Market Info
```python
# Wait for market info container to load
mi_labels = await page.query_selector_all(".container-mi .mi .ob-mi-label")
mi_values = await page.query_selector_all(".container-mi .mi .ob-mi-value")

# Parse label-value pairs (Last, High, Low, Bid Qty, H.Bid)
for label, value in zip(mi_labels, mi_values):
    market_info_dict[label] = value
```

#### Step 3: Extract Bid Levels
```python
# Bid orders in left column
bid_container = await page.query_selector(".bidoff .col-50:first-child")
bid_prices = await bid_container.query_selector_all(".ob-price")
bid_volumes = await bid_container.query_selector_all(".ob-value")

# Parse each level (1-5)
for i in range(len(bid_prices)):
    price = await bid_prices[i].inner_text()
    volume = await bid_volumes[i].inner_text()
    data["bids"].append({"price": price, "volume": volume})
```

#### Step 4: Extract Ask Levels
```python
# Ask orders in right column
ask_container = await page.query_selector(".bidoff .col-50:last-child")
# ... same process as bids
```

#### Step 5: Extract Totals
```python
# Total bid/ask quantities
totals = await page.query_selector_all(".ob-mi-value.padding-right-half-half")
data["total_bid_lot"] = await totals[0].inner_text()
data["total_ask_lot"] = await totals[1].inner_text()
```

### Usage Example

```bash
python ipot_scrapping.py
```

**Expected Output:**
```
============================================================
Orderbook Scraper - IPOT (parallel)
Targets: 10 | Browsers: 2 | Concurrency/browser: 5
============================================================

[INFO] Loaded 10 codes from Daftar 10 Saham.xlsx
[BROWSER-1] Handling 5 stocks
[BROWSER-2] Handling 5 stocks
[BROWSER-1] Done: 5/5 success
[BROWSER-2] Done: 5/5 success
[SUCCESS] Inserted 100 orderbook rows and 10 market data rows into DB

============================================================
SUMMARY
Time: 12.34s (0.21 min)
Success: 10/10 (100.0%)
Failed : 0/10
============================================================

Failed samples: (none)
```

### Error Handling & Retry Logic

**Exponential Backoff Strategy:**
```
Attempt 1: Immediate execution
Attempt 2: Wait 2 seconds, then retry
Attempt 3: Wait 4 seconds, then retry
Attempt 4: Wait 6 seconds, then retry (max)
```

**Resource Blocking:**
```python
# Speed up page loads by blocking heavy resources
await page.route("**/*", lambda route: 
    route.abort() if route.request.resource_type 
    in {"image", "font", "media", "stylesheet"} 
    else route.continue_()
)
```

---

## Installation & Setup

### 1. Clone Repository

```bash
git clone https://github.com/yourusername/Scraping-Orderbook-Ajaib-Investment.git
cd Scraping-Orderbook-Ajaib-Investment
```

### 2. Install Python Dependencies

```bash
pip install -r requirements.txt
```

**requirements.txt:**
```
playwright>=1.40.0
mysql-connector-python>=8.2.0
python-dotenv>=1.0.0
pandas>=2.1.0
openpyxl>=3.1.0
aiohttp>=3.8.0
```

### 3. Install Playwright Browsers

```bash
# Install Firefox (for IPOT scraper)
playwright install firefox

# Install Chromium (for Ajaib/Pangdat scraper)
playwright install chromium

# Or install all
playwright install
```

### 4. Setup MySQL Database

Create database and tables:

```sql
-- Create database
CREATE DATABASE IF NOT EXISTS orderbook_db;
USE orderbook_db;

-- Ajaib orderbook table
CREATE TABLE IF NOT EXISTS orderbook_ajaib (
    id INT AUTO_INCREMENT PRIMARY KEY,
    kode VARCHAR(10) NOT NULL,
    side ENUM('B', 'S') NOT NULL,     -- B=Bid, S=Ask
    price INT,
    lot INT,
    num INT,                           -- Order depth level
    timestamp DATETIME NOT NULL,
    INDEX idx_kode_timestamp (kode, timestamp),
    INDEX idx_timestamp (timestamp)
);

-- IPOT orderbook table
CREATE TABLE IF NOT EXISTS orderbook_ipot (
    id INT AUTO_INCREMENT PRIMARY KEY,
    kode VARCHAR(10) NOT NULL,
    side ENUM('B', 'A') NOT NULL,     -- B=Bid, A=Ask
    price INT,
    lot INT,
    num INT,                           -- Order depth level (1-5)
    timestamp DATETIME NOT NULL,
    INDEX idx_kode_timestamp (kode, timestamp),
    INDEX idx_timestamp (timestamp)
);

-- IPOT market overview table
CREATE TABLE IF NOT EXISTS ipot_overview (
    id INT AUTO_INCREMENT PRIMARY KEY,
    kode VARCHAR(10) NOT NULL,
    last_price DECIMAL(15,2),
    high DECIMAL(15,2),
    low DECIMAL(15,2),
    bid_qty INT,
    h_bid DECIMAL(15,2),
    timestamp DATETIME NOT NULL,
    INDEX idx_kode_timestamp (kode, timestamp)
);
```

### 5. Create Environment File

Create `.env` file in project root:

```env
# Database Configuration
DB_HOST=localhost
DB_USER=root
DB_PASSWORD=your_password
DB_NAME=orderbook_db

# Ajaib Credentials
EMAIL=your_email@gmail.com
PASSWORD=your_password
PINCODE=123456

# IPOT Platform
IPOT_USERNAME=your_username
IPOT_PASSWORD=your_password
```

### 6. Prepare Stock List

Create Excel file with stock codes (e.g., `Daftar 10 Saham.xlsx`):

| Kode |
|------|
| BBCA |
| BBRI |
| TLKM |
| ASII |
| UNVR |
| ICBP |
| BMRI |
| MNCN |
| LPKR |
| MRT  |

---

## Configuration

### Ajaib Scraper (main.py)

```python
# main.py line ~20
MAX_CONCURRENT = 5                   # Concurrent API requests
DELAY_BETWEEN_REQUESTS = 0.2         # Delay between requests (seconds)
RETRY_ON_429_DELAY = 5               # Wait time on rate limit (seconds)

# Stock list
CODES = pd.read_excel("Daftar 10 Saham.xlsx")["Kode"].tolist()
```

**Performance Tuning:**
- Increase `MAX_CONCURRENT` for faster execution (max ~10 before rate limit)
- Increase `DELAY_BETWEEN_REQUESTS` if experiencing 429 errors
- Use smaller stock list for testing

### IPOT Scraper (ipot_scrapping.py)

```python
# ipot_scrapping.py line ~35
NUM_BROWSERS = 2                     # Number of parallel browsers
MAX_CONCURRENT_PER_BROWSER = 5       # Concurrent pages per browser
MAX_RETRIES = 3                      # Retry attempts
PAGE_TIMEOUT = 30000                 # Page timeout (ms)
HEADLESS = True                      # Headless mode

# Stock file
STOCK_FILE = "Daftar 10 Saham.xlsx"
```

**Performance Benchmarks:**
| Stocks | Browsers | Concurrency | Time | Success Rate |
|--------|----------|-------------|------|--------------|
| 10     | 2        | 5           | 12s  | 100%         |
| 100    | 4        | 5           | 2min | 95-100%      |
| 955    | 8        | 10          | 15min| 90-95%       |

**Optimization Tips:**
```python
# For slow networks
PAGE_TIMEOUT = 60000              # Increase to 60 seconds
MAX_RETRIES = 5                   # More retries

# For fast networks
NUM_BROWSERS = 8                  # More parallel instances
MAX_CONCURRENT_PER_BROWSER = 10   # Higher concurrency

# For memory-constrained systems
NUM_BROWSERS = 2                  # Fewer browsers
MAX_CONCURRENT_PER_BROWSER = 3    # Lower concurrency
```

---

## Database Schema

### Ajaib Orderbook (orderbook_ajaib)

```sql
CREATE TABLE orderbook_ajaib (
    id INT AUTO_INCREMENT PRIMARY KEY,
    kode VARCHAR(10) NOT NULL,        -- Stock code (e.g., BBCA)
    side ENUM('B', 'S') NOT NULL,     -- B=Bid, S=Ask
    price INT NOT NULL,               -- Price in IDR
    lot INT NOT NULL,                 -- Volume in lots
    num INT,                          -- Order depth level
    timestamp DATETIME NOT NULL,      -- Scrape timestamp
    
    INDEX idx_kode_timestamp (kode, timestamp),
    INDEX idx_timestamp (timestamp)
);
```

**Sample Data:**
```
id  | kode | side | price | lot | num | timestamp
----|------|------|-------|-----|-----|---------------------
1   | BBCA | B    | 16500 | 234 | 1   | 2024-01-15 09:30:45
2   | BBCA | B    | 16400 | 456 | 2   | 2024-01-15 09:30:45
3   | BBCA | S    | 16600 | 123 | 1   | 2024-01-15 09:30:45
4   | BBCA | S    | 16700 | 789 | 2   | 2024-01-15 09:30:45
```

### IPOT Orderbook (orderbook_ipot)

```sql
CREATE TABLE orderbook_ipot (
    id INT AUTO_INCREMENT PRIMARY KEY,
    kode VARCHAR(10) NOT NULL,        -- Stock code
    side ENUM('B', 'A') NOT NULL,     -- B=Bid, A=Ask
    price INT NOT NULL,               -- Price in IDR
    lot INT NOT NULL,                 -- Volume in lots
    num INT NOT NULL,                 -- Depth level (1-5)
    timestamp DATETIME NOT NULL,      -- Scrape timestamp
    
    INDEX idx_kode_timestamp (kode, timestamp),
    INDEX idx_timestamp (timestamp)
);
```

**Sample Data:**
```
id | kode | side | price | lot | num | timestamp
---|------|------|-------|-----|-----|---------------------
1  | BBCA | B    | 16500 | 234 | 1   | 2024-01-15 09:30:45
2  | BBCA | B    | 16400 | 456 | 2   | 2024-01-15 09:30:45
3  | BBCA | A    | 16600 | 123 | 1   | 2024-01-15 09:30:45
4  | BBCA | A    | 16700 | 789 | 2   | 2024-01-15 09:30:45
```

### IPOT Market Overview (ipot_overview)

```sql
CREATE TABLE ipot_overview (
    id INT AUTO_INCREMENT PRIMARY KEY,
    kode VARCHAR(10) NOT NULL,        -- Stock code
    last_price DECIMAL(15,2),         -- Last traded price
    high DECIMAL(15,2),               -- Daily high
    low DECIMAL(15,2),                -- Daily low
    bid_qty INT,                      -- Total bid quantity
    h_bid DECIMAL(15,2),              -- Highest bid price
    timestamp DATETIME NOT NULL,      -- Scrape timestamp
    
    INDEX idx_kode_timestamp (kode, timestamp)
);
```

**Sample Data:**
```
id | kode | last_price | high  | low   | bid_qty | h_bid  | timestamp
---|------|------------|-------|-------|---------|--------|---------------------
1  | BBCA | 16550.00   | 16750 | 16200 | 2280    | 16500  | 2024-01-15 09:30:45
2  | BBRI | 5230.00    | 5280  | 5150  | 1890    | 5225   | 2024-01-15 09:30:45
```

---

## Usage Examples

### Run Ajaib Scraper (API-based)

```bash
python main.py
```

**What It Does:**
1. Logs into Ajaib platform
2. Captures authentication headers
3. Fetches orderbook data for all stocks
4. Handles re-login on token expiration
5. Saves data to MySQL database

### Run IPOT Scraper (Web-based)

```bash
python ipot_scrapping.py
```

**What It Does:**
1. Loads stock list from Excel file
2. Launches parallel Firefox browsers
3. Scrapes orderbook depth and market data
4. Retries failed stocks with backoff
5. Saves data to MySQL database

### Run Scheduled Execution

```bash
# Run both scrapers every 15 minutes
python worker.py

# Run with custom interval (300s = 5 minutes)
python worker.py -i 300

# Run with 30 minute interval
python worker.py --interval 1800
```

### Advanced: Pangdat Scraper

```bash
python pangdat-scraping.py
```

**Features:**
- Shares session across multiple browsers
- More stable than main.py
- Screenshot capture on errors
- Better for large stock lists

---

## Filter GUI

### Launch Interactive Dashboard

```bash
python filter.py
```

### Features

✅ Interactive filtering by stock code  
✅ Filter by bid/ask side  
✅ Price range filtering  
✅ Lot range filtering  
✅ Bid/Ask ratio analysis (e.g., Bid ≥ 4× Ask)  
✅ Result limit selection  
✅ CSV export with timestamps  
✅ Real-time result count display  

### Usage Guide

1. **Select Data Source:** Choose between Ajaib or IPOT data
2. **Set Filters:**
   - Stock Code: Enter code (e.g., BBCA) or leave blank for all
   - Side: Select BID, ASK, or ALL
   - Price Range: Enter min/max (optional)
   - Lot Range: Enter min/max (optional)
   - Limit: Select result count
3. **Apply Filter:** Click "Apply Filter" button
4. **View Results:** See filtered data in table
5. **Export:** Click "Export to CSV" to save results

### Example Queries

**Find all bid orders for BBCA above 16,500:**
- Stock Code: `BBCA`
- Side: `BID`
- Price Min: `16500`
- Click "Apply Filter"

**Find high-volume ask orders:**
- Side: `ASK`
- Lot Min: `1000`
- Limit: `100`

**Special Filter: Find stocks where Bid ≥ 4× Ask:**
- Enable: "Bid Price ≥"
- Set Multiplier: `4`
- Click "Apply Filter"

---

## Architecture & Performance

### Ajaib Scraper Architecture

```
┌─────────────┐
│   Login     │  Step 1: Authenticate and capture headers
│  (1 time)   │
└──────┬──────┘
       │
       ▼
┌─────────────────────────────────────────┐
│  Fetch Data in Batches                  │  Step 2: Process in batches
│  (5 concurrent requests)                │
├─────────────────────────────────────────┤
│ Req 1: BBCA  │ Req 2: BBRI │ Req 3: ... │  Batch 1
│ Req 4: ASII  │ Req 5: UNVR │            │  (5 codes)
├─────────────────────────────────────────┤
│ Req 6: ICBP  │ Req 7: MNCN │ Req 8: ... │  Batch 2
│ Req 9: LPKR  │ Req 10: MRT │            │  (5 codes)
└──────┬───────────────────────────────────┘
       │
       ▼
┌─────────────────────┐
│  Parse JSON Data    │  Step 3: Transform to DataFrame
│  (All stocks)       │
└──────┬──────────────┘
       │
       ▼
┌─────────────────────┐
│  Save to MySQL      │  Step 4: Store in database
│  (Bulk insert)      │
└─────────────────────┘
```

### IPOT Scraper Architecture

```
┌──────────────────────────────────────┐
│  Load Stock List from Excel File     │
│  (e.g., 955 stocks)                  │
└──────┬───────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────────────────┐
│  Split Stocks Among Browsers                     │
├──────────────────────────────────────────────────┤
│  Browser 1  │  Browser 2  │  Browser 3  │ ... │
│  239 stocks │  239 stocks │  239 stocks │     │
└──────┬──────────────┬──────────────┬────────────┘
       │              │              │
       ▼              ▼              ▼
  ┌────────────┐ ┌────────────┐ ┌────────────┐
  │ Firefox 1  │ │ Firefox 2  │ │ Firefox 3  │
  │ (5 pages)  │ │ (5 pages)  │ │ (5 pages)  │
  └────┬───────┘ └────┬───────┘ └────┬───────┘
       │ Scrape       │ Scrape       │ Scrape
       │ Stock A      │ Stock B      │ Stock C
       │ Stock D      │ Stock E      │ Stock F
       │ ...          │ ...          │ ...
       │              │              │
       └──────────┬───┴──────────┬───┘
                  │              │
                  ▼              ▼
          ┌──────────────────────────────┐
          │  Aggregate Results           │
          │  (All successful scrapers)   │
          └──────┬───────────────────────┘
                 │
                 ▼
          ┌──────────────────────────────┐
          │  Transform Data              │
          │  - orderbook_ipot table      │
          │  - ipot_overview table       │
          └──────┬───────────────────────┘
                 │
                 ▼
          ┌──────────────────────────────┐
          │  Save to MySQL               │
          │  (Bulk insert)               │
          └──────────────────────────────┘
```

### Performance Metrics

**Ajaib Scraper (main.py):**
- 10 stocks: ~2 seconds
- 100 stocks: ~20 seconds
- 955 stocks: ~3 minutes

**IPOT Scraper (ipot_scrapping.py):**
- 10 stocks: ~12 seconds (2 browsers × 5 concurrent)
- 100 stocks: ~2 minutes (4 browsers × 5 concurrent)
- 955 stocks: ~15 minutes (8 browsers × 10 concurrent)

**Pangdat Scraper (pangdat-scraping.py):**
- 10 stocks: ~15 seconds (1 browser, 5 concurrent)
- 100 stocks: ~2.5 minutes (2 browsers, 5 concurrent)
- 955 stocks: ~18 minutes (4 browsers, 5 concurrent)

---

## Troubleshooting

### Common Issues & Solutions

#### 1. **"Column 'Kode' not found"**

**Problem:** Excel file doesn't have a column named "Kode"

**Solution:**
```python
# Check Excel file columns
import pandas as pd
df = pd.read_excel("Daftar 10 Saham.xlsx")
print(df.columns)  # See available columns

# Rename column if needed
df.rename(columns={'Stock': 'Kode'}, inplace=True)
df.to_excel("Daftar 10 Saham.xlsx", index=False)
```

#### 2. **"Connection refused" - MySQL Error**

**Problem:** Cannot connect to MySQL database

**Solution:**
```bash
# Check MySQL is running
mysql -u root -p  # Try to login

# Or start MySQL service
# Windows
net start MySQL

# Linux
sudo systemctl start mysql

# macOS
brew services start mysql
```

#### 3. **"401 Unauthorized" - Ajaib Scraper**

**Problem:** Authentication token expired

**Solution:**
- Automatic re-login is built in, but verify `.env` credentials
```env
EMAIL=your_email@gmail.com
PASSWORD=your_password
PINCODE=123456
```

#### 4. **"429 Too Many Requests"**

**Problem:** Rate limited by API/website

**Solution:**
```python
# Ajaib Scraper - Increase delays
MAX_CONCURRENT = 3              # Reduce from 5
DELAY_BETWEEN_REQUESTS = 0.5    # Increase from 0.2

# IPOT Scraper - Reduce concurrency
NUM_BROWSERS = 2                # Reduce from 4
MAX_CONCURRENT_PER_BROWSER = 3  # Reduce from 5
```

#### 5. **"Timeout waiting for orderbook data"**

**Problem:** Page takes too long to load

**Solution:**
```python
# IPOT Scraper
PAGE_TIMEOUT = 60000            # Increase from 30000 (60 seconds)
MAX_RETRIES = 5                 # More retry attempts
```

#### 6. **"Browser failed to launch"**

**Problem:** Playwright browsers not installed

**Solution:**
```bash
# Reinstall browsers
playwright install firefox chromium --force

# Or specific browser
playwright install firefox --force
```

#### 7. **Database Connection Fails**

**Problem:** Wrong credentials or database doesn't exist

**Solution:**
```sql
-- Check database exists
SHOW DATABASES;

-- Create if missing
CREATE DATABASE IF NOT EXISTS orderbook_db;

-- Check tables
USE orderbook_db;
SHOW TABLES;

-- Create tables if missing (see Database Schema section)
```

#### 8. **"Permission denied" - Excel File**

**Problem:** Cannot read Excel file

**Solution:**
```bash
# Close Excel if open (file is locked)
# Or copy to new file
cp "Daftar 10 Saham.xlsx" "Daftar 10 Saham - Copy.xlsx"

# Update code to use copy
STOCK_FILE = "Daftar 10 Saham - Copy.xlsx"
```

### Debug Mode

Enable logging for troubleshooting:

```python
# Add to main.py or ipot_scrapping.py
import logging

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Then use:
logger.debug("Scraping stock: " + code)
logger.error("Failed to scrape: " + str(e))
```

---

## Project Structure

```
Scraping-Orderbook-Ajaib-Investment/
├── main.py                      # Ajaib API scraper (deprecated)
├── pangdat-scraping.py          # Ajaib web scraper (advanced)
├── ipot_scrapping.py            # IPOT web scraper (main)
├── filter.py                    # Interactive filter GUI
├── worker.py                    # Scheduled job runner
│
├── Daftar 10 Saham.xlsx         # Small stock list (testing)
├── Daftar 955 Saham.xlsx        # Full stock list (production)
├── saham_idx.csv                # Sample output CSV
│
├── .env.example                 # Environment template
├── requirements.txt             # Python dependencies
├── README.md                    # This file
│
├── .gitignore                   # Git ignore rules
├── env.yml                      # Conda environment file
└── stock_data_db.sql            # Database schema dump
```

---

## Quick Reference

### Commands Cheat Sheet

```bash
# Ajaib API scraper
python main.py

# IPOT web scraper
python ipot_scrapping.py

# Ajaib web scraper
python pangdat-scraping.py

# Filter GUI
python filter.py

# Scheduled execution (15 min interval)
python worker.py

# Scheduled execution (5 min interval)
python worker.py -i 300

# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers
playwright install firefox chromium

# Test database connection
mysql -h localhost -u root -p -e "USE orderbook_db; SELECT COUNT(*) FROM orderbook_ajaib;"
```

### Environment Variables

```env
# Database
DB_HOST=localhost
DB_USER=root
DB_PASSWORD=password
DB_NAME=orderbook_db

# Ajaib Authentication
EMAIL=user@example.com
PASSWORD=password
PINCODE=123456

# Optional: IPOT Authentication (if needed)
IPOT_USERNAME=username
IPOT_PASSWORD=password
```

---

## Support & Resources

- **Issues:** Open GitHub issue with error logs
- **Documentation:** See README.md sections above
- **Stock Data:** Use provided Excel files or create custom
- **Database:** MySQL 5.7+ or MariaDB 10.3+

---

## License

MIT License - Feel free to use and modify

## Disclaimer

This tool is for educational and research purposes. Ensure compliance with platform terms of service and applicable regulations regarding web scraping.

---

**Last Updated:** January 2026  
**Version:** 2.0  
**Tested On:** Python 3.9+, MySQL 8.0+
