"""IPOT Orderbook Scraper

This script scrapes stock orderbook data from Indo Premier Online Trading (IPOT) website.
It uses parallel browser instances with Playwright to efficiently collect bid/ask data
and market information for multiple stocks, then stores the results in a MySQL database.

Key Features:
- Parallel scraping using multiple Firefox browser instances
- Automatic retry mechanism with exponential backoff
- Resource blocking (images, fonts, etc.) for faster page loads
- MySQL database integration for data persistence
- Support for large stock lists via Excel file input
"""

import asyncio
import json
import os
import time
from datetime import datetime

import mysql.connector
import pandas as pd
from dotenv import load_dotenv
from playwright.async_api import TimeoutError, async_playwright

load_dotenv()

# =============================================================================
# CONFIGURATION
# =============================================================================

# Stock list source file - Excel file containing stock codes to scrape
# STOCK_LIST = ['ANTM', 'BBCA', 'BBRI', 'BMRI', 'TLKM', 'ASII', 'UNVR', 'ICBP']  # Manual list (unused)
STOCK_FILE =  "Daftar 10 Saham.xlsx"   # Small test file
# STOCK_FILE =  "Daftar 955 Saham.xlsx"  # Full production file

# Parallel scraping configuration
NUM_BROWSERS = 2                     # Number of browser instances to run in parallel
MAX_CONCURRENT_PER_BROWSER = 5       # Max concurrent pages per browser (controls memory usage)
MAX_RETRIES = 3                      # Number of retry attempts for failed scrapes
PAGE_TIMEOUT = 30000                 # Page load timeout in milliseconds
HEADLESS = True                      # Run browsers in headless mode (no GUI)

def load_stock_list():
    """Load stock codes from Excel file.
    
    Reads the specified Excel file and extracts stock codes from the 'Kode' column.
    Validates that the column exists and contains data.
    
    Returns:
        list[str]: List of stock codes (e.g., ['BBCA', 'BMRI', 'TLKM'])
        
    Raises:
        ValueError: If 'Kode' column is missing or empty
    """
    df = pd.read_excel(STOCK_FILE)
    if "Kode" not in df.columns:
        raise ValueError(f"Column 'Kode' not found in {STOCK_FILE}")
    codes = df["Kode"].dropna().astype(str).str.strip().tolist()
    if not codes:
        raise ValueError(f"No codes found in column 'Kode' of {STOCK_FILE}")
    print(f"[INFO] Loaded {len(codes)} codes from {STOCK_FILE}")
    return codes

STOCK_LIST = load_stock_list()

def _to_int(text: str | None):
    """Convert formatted text to integer.
    
    Removes comma and dot separators commonly used in number formatting
    (e.g., '1,234,567' -> 1234567).
    
    Args:
        text: String representation of a number with possible separators
        
    Returns:
        int or None: Parsed integer value, or None if conversion fails
    """
    if not text:
        return None
    cleaned = text.replace(',', '').replace('.', '').strip()
    if not cleaned:
        return None
    try:
        return int(cleaned)
    except ValueError:
        return None

def _to_decimal(text: str | None):
    """Convert formatted text to decimal number.
    
    Handles comma as thousand separator and converts to float.
    (e.g., '1,234.56' -> 1234.56)
    
    Args:
        text: String representation of a decimal number
        
    Returns:
        float or None: Parsed float value, or None if conversion fails
    """
    if not text:
        return None
    # Remove commas (thousand separator) and strip
    cleaned = text.replace(',', '').strip()
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None

def flatten_rows(results):
    """Flatten scraped orderbook data into database-ready rows.
    
    Converts nested orderbook data structure into flat tuples for MySQL insertion.
    Each bid/ask level becomes a separate row with its position number.
    
    Args:
        results: List of scraping results, each containing bids and asks
        
    Returns:
        list[tuple]: List of tuples in format:
                     (stock_code, side, price, volume, position_num, timestamp)
                     where side is 'B' for bid or 'A' for ask
    """
    rows = []
    for res in results:
        if res.get("error"):
            continue
        ts = datetime.fromisoformat(res.get("timestamp"))
        code = res.get("stock_code")
        # Process all bid levels (best bid = position 1)
        for i, bid in enumerate(res.get("bids", []), start=1):
            rows.append((code, "B", _to_int(bid.get("price")), _to_int(bid.get("volume")), i, ts))
        # Process all ask levels (best ask = position 1)
        for i, ask in enumerate(res.get("asks", []), start=1):
            rows.append((code, "A", _to_int(ask.get("price")), _to_int(ask.get("volume")), i, ts))
    return rows

def flatten_market_data(results):
    """Extract market overview data into database-ready rows.
    
    Extracts summary market information (last price, high, low, etc.) from
    scraped results and formats them for the ipot_overview table.
    
    Args:
        results: List of scraping results containing market_data dictionaries
        
    Returns:
        list[tuple]: List of tuples in format:
                     (stock_code, last_price, high, low, bid_qty, h_bid, timestamp)
    """
    rows = []
    for res in results:
        if res.get("error"):
            continue
        ts = datetime.fromisoformat(res.get("timestamp"))
        code = res.get("stock_code")
        md = res.get("market_data", {})
        
        rows.append((
            code,
            _to_decimal(md.get("last_price")),
            _to_decimal(md.get("high")),
            _to_decimal(md.get("low")),
            _to_int(md.get("bid_qty")),
            _to_decimal(md.get("h_bid")),
            ts
        ))
    return rows

def push_to_database(rows, market_data_rows):
    """Insert scraped data into MySQL database.
    
    Performs bulk insert of orderbook and market data into their respective tables.
    Database credentials are read from environment variables (.env file).
    
    Args:
        rows: List of orderbook tuples for orderbook_ipot table
        market_data_rows: List of market data tuples for ipot_overview table
        
    Note:
        Uses executemany() for efficient bulk insertion.
        Automatically commits transaction and closes connection.
    """
    conn = mysql.connector.connect(
        host=os.getenv("DB_HOST"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME"),
    )
    try:
        cur = conn.cursor()
        # Insert orderbook data (bid/ask levels)
        if rows:
            cur.executemany(
                "INSERT INTO orderbook_ipot (kode, side, price, lot, num, timestamp) VALUES (%s, %s, %s, %s, %s, %s)",
                rows,
            )
        # Insert market overview data (last price, high, low, etc.)
        if market_data_rows:
            cur.executemany(
                "INSERT INTO ipot_overview (kode, last_price, high, low, bid_qty, h_bid, timestamp) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                market_data_rows,
            )
        conn.commit()
        print(f"[SUCCESS] Inserted {len(rows)} orderbook rows and {len(market_data_rows)} market data rows into DB")
    finally:
        cur.close()
        conn.close()

async def scrape_orderbook(page, stock_code):
    """Scrape orderbook data for a single stock from IPOT website.
    
    Navigates to the stock's page, waits for orderbook to load, then extracts:
    - Market info (last price, high, low, bid qty, h.bid)
    - Bid levels (price and volume for each level)
    - Ask levels (price and volume for each level)
    - Total bid/ask lot counts
    
    Args:
        page: Playwright page object (browser tab)
        stock_code: Stock ticker symbol (e.g., 'BBCA', 'TLKM')
        
    Returns:
        dict: Complete orderbook data structure with timestamp
        
    Raises:
        Exception: If orderbook doesn't load after retries or no data found
        
    Note:
        The website may not always display all market data fields in the web view.
    """
    url = f"https://indopremier.com/#ipot/app/ipotbuzz/home/{stock_code}"
    page.set_default_timeout(PAGE_TIMEOUT)
    await page.goto(url, wait_until="domcontentloaded")

    # Wait for orderbook container to load, retry up to 3 times with page reload
    for _ in range(3):
        try:
            await page.wait_for_selector(".bidoff", timeout=10000)
            break
        except TimeoutError:
            await page.reload()
    else:
        raise Exception("Timeout: .bidoff not found after retries")

    # Initialize data structure for scraped information
    data = {
        "stock_code": stock_code,
        "timestamp": datetime.now().isoformat(),
        "market_info": {},      # Raw label-value pairs from website
        "market_data": {},      # Structured data for database
        "bids": [],             # List of bid levels [{price, volume}, ...]
        "asks": [],             # List of ask levels [{price, volume}, ...]
        "total_bid_lot": None,
        "total_ask_lot": None,
    }

    # === SECTION 1: Extract Market Info (Last Price, High, Low, etc.) ===
    try:
        mi_labels = await page.query_selector_all(".container-mi .mi .ob-mi-label")
        mi_values = await page.query_selector_all(".container-mi .mi .ob-mi-value")
        market_info_dict = {}
        for label, value in zip(mi_labels, mi_values):
            ltext = (await label.inner_text()).strip()
            vtext = (await value.inner_text()).strip()
            market_info_dict[ltext] = vtext
        data["market_info"] = market_info_dict
        
        # Map website labels to database fields
        # Handle various label naming conventions used on the website
        data["market_data"]["last_price"] = (
            market_info_dict.get("Last") or 
            market_info_dict.get("Price") or 
            market_info_dict.get("Last Price")
        )
        data["market_data"]["high"] = market_info_dict.get("High")
        data["market_data"]["low"] = market_info_dict.get("Low")
        data["market_data"]["bid_qty"] = (
            market_info_dict.get("Bid Qty") or
            market_info_dict.get("BidQty")
        )
        data["market_data"]["h_bid"] = (
            market_info_dict.get("H.Bid") or
            market_info_dict.get("H Bid") or
            market_info_dict.get("Highest Bid")
        )
        
    except Exception as e:
        print(f"[{stock_code}] Market info error: {e}")

    # === SECTION 2: Extract Bid Levels (Buy Orders) ===
    try:
        bid_container = await page.query_selector(".bidoff .col-50:first-child")
        if bid_container:
            bid_prices = await bid_container.query_selector_all(".ob-price")
            bid_vols = await bid_container.query_selector_all(".ob-value.padding-right-half-half")
            for i in range(len(bid_prices)):
                price = (await bid_prices[i].inner_text()).strip()
                volume = (await bid_vols[i].inner_text()).strip() if i < len(bid_vols) else ""
                data["bids"].append({"price": price, "volume": volume})
    except Exception as e:
        print(f"[{stock_code}] Bid error: {e}")

    # === SECTION 3: Extract Ask Levels (Sell Orders) ===
    try:
        ask_container = await page.query_selector(".bidoff .col-50:last-child")
        if ask_container:
            ask_prices = await ask_container.query_selector_all(".ob-price")
            ask_vols = await ask_container.query_selector_all(".ob-value.padding-right-half-half")
            for i in range(len(ask_prices)):
                price = (await ask_prices[i].inner_text()).strip()
                volume = (await ask_vols[i].inner_text()).strip() if i < len(ask_vols) else ""
                data["asks"].append({"price": price, "volume": volume})
    except Exception as e:
        print(f"[{stock_code}] Ask error: {e}")

    # === SECTION 4: Extract Total Bid/Ask Lots ===
    try:
        totals = await page.query_selector_all(".ob-mi-value.padding-right-half-half")
        if len(totals) >= 2:
            data["total_bid_lot"] = (await totals[0].inner_text()).strip()
            data["total_ask_lot"] = (await totals[1].inner_text()).strip()
    except Exception as e:
        print(f"[{stock_code}] Totals error: {e}")

    # Validate that we got some data
    if not data["bids"] and not data["asks"]:
        raise Exception("No bid/ask rows found")
    return data

async def scrape_with_retry(browser, stock_code, semaphore, max_retries=MAX_RETRIES):
    """Scrape a single stock with automatic retry and resource optimization.
    
    Uses a semaphore to limit concurrent scraping operations per browser.
    Implements retry logic with exponential backoff on failure.
    Blocks heavy resources (images, fonts, etc.) to speed up page loads.
    
    Args:
        browser: Playwright browser instance
        stock_code: Stock ticker to scrape
        semaphore: Asyncio semaphore to limit concurrency
        max_retries: Maximum number of retry attempts
        
    Returns:
        dict: Result with 'success', 'stock_code', 'data', and 'error' fields
    """
    async with semaphore:  # Limit concurrent operations
        error = None
        for attempt in range(1, max_retries + 1):
            context = None
            page = None
            try:
                context = await browser.new_context()
                page = await context.new_page()
                
                # Block heavy resources to improve load speed and reduce bandwidth
                await page.route(
                    "**/*",
                    lambda route: route.abort()
                    if route.request.resource_type in {"image", "font", "media", "stylesheet"}
                    else route.continue_(),
                )
                
                data = await scrape_orderbook(page, stock_code)
                if attempt > 1:
                    print(f"[SUCCESS] {stock_code} succeeded on attempt {attempt}")
                return {"success": True, "stock_code": stock_code, "data": data, "error": None}
            except Exception as e:
                error = str(e)
                if attempt < max_retries:
                    await asyncio.sleep(attempt * 2)  # Exponential backoff: 2s, 4s, 6s...
            finally:
                # Always clean up browser context
                if context:
                    try:
                        await context.close()
                    except Exception:
                        pass
        print(f"[FAILED] {stock_code} failed after {max_retries} attempts: {error}")
        return {"success": False, "stock_code": stock_code, "data": {}, "error": error}

def split_list(lst, n):
    """Split a list into n roughly equal chunks.
    
    Distributes items as evenly as possible across chunks.
    Used to divide stock list among multiple browser instances.
    
    Args:
        lst: List to split
        n: Number of chunks to create
        
    Returns:
        list[list]: List of n sublists with balanced sizes
        
    Example:
        split_list([1,2,3,4,5], 2) -> [[1,2,3], [4,5]]
    """
    k, m = divmod(len(lst), n)
    return [lst[i * k + min(i, m):(i + 1) * k + min(i + 1, m)] for i in range(n)]

async def scrape_with_one_browser(playwright, browser_id, codes):
    """Manage one browser instance to scrape multiple stocks concurrently.
    
    Launches a Firefox browser and creates multiple concurrent scraping tasks
    within that browser, controlled by a semaphore to prevent memory overload.
    
    Args:
        playwright: Playwright instance
        browser_id: Identifier for logging (e.g., 1, 2, 3)
        codes: List of stock codes assigned to this browser
        
    Returns:
        tuple: (success_list, failed_list) where:
               - success_list contains scraped data dictionaries
               - failed_list contains error information
    """
    print(f"[BROWSER-{browser_id}] Handling {len(codes)} stocks")
    browser = None
    try:
        browser = await playwright.firefox.launch(headless=HEADLESS)
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_PER_BROWSER)  # Limit concurrent pages
        
        # Create all scraping tasks for this browser
        tasks = [scrape_with_retry(browser, code, semaphore) for code in codes]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Separate successful and failed results
        success, failed = [], []
        for r in results:
            if isinstance(r, Exception):
                failed.append({"stock_code": "unknown", "error": str(r)})
            elif r["success"]:
                success.append(r["data"])
            else:
                failed.append({"stock_code": r["stock_code"], "error": r["error"]})
        print(f"[BROWSER-{browser_id}] Done: {len(success)}/{len(codes)} success")
        return success, failed
    finally:
        # Always close browser to free resources
        if browser:
            try:
                await asyncio.sleep(0.2)  # Small delay for graceful shutdown
                await browser.close()
            except Exception:
                pass

async def scrape_all(playwright, codes):
    """Coordinate parallel scraping across multiple browser instances.
    
    Splits the stock list among NUM_BROWSERS browser instances and runs them
    in parallel. Each browser handles its chunk of stocks concurrently.
    
    Args:
        playwright: Playwright instance
        codes: Complete list of stock codes to scrape
        
    Returns:
        tuple: (all_success, all_failed) aggregated from all browsers
    """
    # Divide work among browsers
    chunks = split_list(codes, NUM_BROWSERS)
    for i, chunk in enumerate(chunks, 1):
        print(f"   Browser-{i}: {len(chunk)} stocks")
    
    # Launch all browser instances in parallel
    tasks = [scrape_with_one_browser(playwright, i + 1, chunk) for i, chunk in enumerate(chunks)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Aggregate results from all browsers
    all_success, all_failed = [], []
    for i, res in enumerate(results):
        if isinstance(res, Exception):
            print(f"[FAILED] Browser-{i+1} fatal: {res}")
        else:
            s, f = res
            all_success.extend(s)
            all_failed.extend(f)
    return all_success, all_failed

async def main():
    """Main entry point for the scraper.
    
    Orchestrates the entire scraping workflow:
    1. Print configuration summary
    2. Execute parallel scraping
    3. Transform data for database
    4. Insert into MySQL
    5. Print execution summary and statistics
    """
    print(f"{'='*60}")
    print("Orderbook Scraper - IPOT (parallel)")
    print(f"Targets: {len(STOCK_LIST)} | Browsers: {NUM_BROWSERS} | Concurrency/browser: {MAX_CONCURRENT_PER_BROWSER}")
    print(f"{'='*60}\n")
    
    start = time.time()
    
    # Execute scraping with Playwright
    async with async_playwright() as p:
        success, failed = await scrape_all(p, STOCK_LIST)

    # Transform scraped data into database format
    # NOTE: JSON file output is disabled; all data goes directly to MySQL
    # output_file = f"orderbook_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    # with open(output_file, "w", encoding="utf-8") as f:
    #     json.dump(success + failed, f, indent=2, ensure_ascii=False)

    rows = flatten_rows(success)                    # Orderbook bid/ask levels
    market_data_rows = flatten_market_data(success) # Market overview data
    
    # Insert into database if we have data
    if rows or market_data_rows:
        try:
            push_to_database(rows, market_data_rows)
        except Exception as e:
            print(f"[ERROR] DB insert failed: {e}")

    # Print execution summary
    elapsed = time.time() - start
    success_count = len(success)
    failed_count = len(failed)
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"Time: {elapsed:.2f}s ({elapsed/60:.2f} min)")
    print(f"Success: {success_count}/{len(STOCK_LIST)} ({success_count/len(STOCK_LIST)*100:.1f}%)")
    print(f"Failed : {failed_count}/{len(STOCK_LIST)}")
    print(f"{'='*60}\n")

    # Show sample of failed stocks if any
    if failed:
        sample = ", ".join(f["stock_code"] for f in failed[:10])
        extra = f" ... +{len(failed) - 10} more" if len(failed) > 10 else ""
        print(f"Failed samples: {sample}{extra}")

# =============================================================================
# SCRIPT ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[STOPPED] Stopped by user")