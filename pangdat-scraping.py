"""Ajaib/Pangdat Orderbook Scraper

This script scrapes stock orderbook data from Ajaib investment platform (invest.ajaib.co.id).
It uses Playwright with authenticated sessions to access protected pages, then extracts bid/ask
data for multiple stocks using parallel browser instances. Results are stored in MySQL database.

Key Features:
- Single login shared across multiple browser instances (session reuse)
- Parallel scraping with multiple Chromium browsers
- Automatic retry mechanism with exponential backoff
- Screenshot capture on failures for debugging
- Resource blocking optimization for faster page loads
- MySQL database integration for data persistence
- Failed stock logging to CSV for tracking
- Support for large stock lists via Excel file input

Authentication:
    Requires EMAIL, PASSWORD, and PINCODE environment variables for Ajaib login.
    Session state is captured once and reused across all browser instances.

Usage:
    python pangdat-scraping.py    # Run once and exit
    
Note:
    For periodic execution, use worker.py which runs this script at intervals.
"""

import asyncio
import os
import time
import pandas as pd
import mysql.connector
from dotenv import load_dotenv
from playwright.async_api import async_playwright
from itertools import zip_longest
from datetime import datetime

load_dotenv()

# =============================================================================
# CONFIGURATION
# =============================================================================

# Authentication credentials from environment variables
EMAIL = os.getenv("EMAIL")
PASSWORD = os.getenv("PASSWORD")
PIN_CODE = os.getenv("PINCODE")

# Ajaib platform URLs
LOGIN_URL = "https://login.ajaib.co.id/login"
BASE_SAHAM_URL = "https://invest.ajaib.co.id/home/saham"

# Timing and file configuration
PIN_CHECK_INTERVAL = 5000            # Wait time after PIN entry (ms)
CSV_FILE = "scrap_result.csv"        # Legacy CSV output (unused - MySQL is used instead)
FAILED_LOG_FILE = "failed_emiten.csv"  # Log file for failed scrapes

# Stock list source - Excel file containing stock codes to scrape
# df_saham = pd.read_excel("Daftar Saham.xlsx")      # Full list
# df_saham = pd.read_excel("daftar 50 saham.xlsx")   # Medium test
df_saham = pd.read_excel("Daftar 10 Saham.xlsx")     # Small test file
list_kode = df_saham["Kode"].tolist()

# Parallel scraping configuration
NUM_BROWSERS = 2                     # Number of browser instances to run in parallel
MAX_CONCURRENT_PER_BROWSER = 5       # Max concurrent pages per browser (reduced for stability)
MAX_RETRIES = 5                      # Number of retry attempts for failed scrapes
TIMEOUT = 90000                      # Page load timeout in milliseconds (90s)

# Async lock for CSV file writing (prevents race conditions)
csv_lock = asyncio.Lock()


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

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


def flatten_rows_ajaib(results):
    """Convert scraped DataFrames to database-ready rows.
    
    Transforms Ajaib's DataFrame format (with separate bid/ask columns) into
    flat tuples suitable for MySQL insertion. Each bid and ask entry becomes
    a separate row.
    
    Args:
        results: List of pandas DataFrames from scraping, each with columns:
                 kode, bid_lot, bid_price, ask_price, ask_lot, timestamp
        
    Returns:
        list[tuple]: List of tuples in format:
                     (stock_code, side, price, lot, num, timestamp)
                     where side is 'B' for bid or 'A' (converted from 'S') for ask
                     
    Note:
        - The 'num' field (position/level) is set to None as Ajaib scraper
          doesn't track orderbook depth positions
        - Only rows with valid price and lot data are included
    """
    rows = []
    for df in results:
        if df.empty:
            continue
        for _, row in df.iterrows():
            kode = row.get("kode")
            timestamp = pd.to_datetime(row.get("timestamp"))
            
            # Process bid data if both price and lot are present
            if pd.notna(row.get("bid_price")) and pd.notna(row.get("bid_lot")):
                rows.append((
                    kode,
                    "B",  # Bid side
                    _to_int(row.get("bid_price")),
                    _to_int(row.get("bid_lot")),
                    None,  # num - position/level not tracked in Ajaib scraper
                    timestamp
                ))
            
            # Process ask data if both price and lot are present
            if pd.notna(row.get("ask_price")) and pd.notna(row.get("ask_lot")):
                rows.append((
                    kode,
                    "A",  # Ask side (converted from 'S' for consistency)
                    _to_int(row.get("ask_price")),
                    _to_int(row.get("ask_lot")),
                    None,  # num
                    timestamp
                ))
    return rows


def push_to_database(rows, table_name="orderbook_ajaib"):
    """Insert scraped orderbook rows into MySQL database.
    
    Performs bulk insert of orderbook data into the specified table.
    Database credentials are read from environment variables (.env file).
    
    Args:
        rows: List of orderbook tuples (kode, side, price, lot, num, timestamp)
        table_name: Target database table name (default: "orderbook_ajaib")
        
    Raises:
        Exception: If database connection or insertion fails
        
    Note:
        Uses executemany() for efficient bulk insertion.
        Automatically commits transaction and closes connection.
    """
    if not rows:
        print("[WARN] No rows to insert")
        return
    
    conn = mysql.connector.connect(
        host=os.getenv("DB_HOST"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME"),
    )
    try:
        cur = conn.cursor()
        cur.executemany(
            f"INSERT INTO {table_name} (kode, side, price, lot, num, timestamp) VALUES (%s, %s, %s, %s, %s, %s)",
            rows,
        )
        conn.commit()
        print(f"[SUCCESS]Inserted {len(rows)} rows into DB table '{table_name}'")
    except Exception as e:
        print(f"[ERROR] Database insertion failed: {e}")
        raise
    finally:
        cur.close()
        conn.close()


# =============================================================================
# AUTHENTICATION
# =============================================================================

async def login_once_and_get_storage_state(playwright):
    """Perform one-time login and capture session state for reuse.
    
    Opens a visible browser, logs into Ajaib platform with email/password,
    enters PIN code, and captures the authenticated session state. This state
    is then shared across all parallel browser instances to avoid repeated logins.
    
    Args:
        playwright: Playwright instance
        
    Returns:
        dict: Browser storage state (cookies, localStorage, etc.) for session reuse
        
    Raises:
        Exception: If login fails or times out
        
    Note:
        - Uses headless=False for login to handle any CAPTCHAs manually if needed
        - Automatically dismisses "Mengerti" (Understand) popup if present
        - Session state includes authentication cookies and tokens
    """
    print(f"[LOGIN] Login...")

    # Use visible browser for login (easier to debug if issues arise)
    browser = await playwright.chromium.launch(headless=False)
    context = await browser.new_context()
    page = await context.new_page()

    try:
        # Navigate to login page and fill credentials
        await page.goto(LOGIN_URL)
        await page.fill('input[name=email]', EMAIL)
        await page.fill('input[name=password]', PASSWORD)
        await page.click('button[type=submit]')
        
        # Wait for PIN entry screen
        await page.wait_for_selector('.pincode-input-container', timeout=15000)

        # Enter PIN code character by character
        await page.locator('.pincode-input-text').first.click()
        await page.keyboard.type(PIN_CODE, delay=150)
        await page.wait_for_timeout(PIN_CHECK_INTERVAL)
        
        # Wait for successful redirect to home page
        await page.wait_for_url('**/home')

        # Dismiss popup if present
        try:
            await page.get_by_role("button", name="Mengerti").click()
        except:
            pass

        # Capture session state for reuse
        storage_state = await context.storage_state()
        print(f"[SUCCESS]Login sukses! Session shared ke {NUM_BROWSERS} browsers")
        return storage_state

    finally:
        await context.close()
        await browser.close()


async def ensure_logged_in(page):
    """Verify session validity and handle re-authentication if needed.
    
    Checks if the page is still on an authenticated page. If redirected to
    PIN or login page, attempts to re-authenticate.
    
    Args:
        page: Playwright page object
        
    Raises:
        Exception: If page is closed or session has expired (needs full re-login)
        
    Note:
        - Handles PIN re-entry automatically if prompted
        - Raises exception for full login requirement (session expired)
    """
    try:
        current_url = page.url
    except Exception:
        raise Exception("Page is closed")

    # Handle PIN re-entry if prompted
    if "/pin" in current_url:
        print(f"[WARN] PIN diminta ulang")
        await page.locator('.pincode-input-text').first.click()
        await page.keyboard.type(PIN_CODE, delay=150)
        await page.wait_for_timeout(PIN_CHECK_INTERVAL)

    # Session expired - need full re-login
    if "/login" in current_url:
        raise Exception("Session expired")


# =============================================================================
# SCRAPING FUNCTIONS
# =============================================================================

async def scrape_stock(page, kode):
    """Scrape orderbook data for a single stock from Ajaib platform.
    
    Navigates to the stock's page and extracts bid/ask orderbook data from
    the DOM. Ajaib uses a React SPA, so we wait for specific elements to load.
    
    Args:
        page: Playwright page object (already authenticated)
        kode: Stock ticker symbol (e.g., 'BBCA', 'TLKM')
        
    Returns:
        pandas.DataFrame: DataFrame with columns:
                         kode, bid_lot, bid_price, ask_price, ask_lot, timestamp
        
    Raises:
        Exception: If orderbook data fails to load or DOM selectors not found
        
    Note:
        - Waits for .item-price selector to ensure data has loaded
        - Uses CSS selectors specific to Ajaib's DOM structure
        - Returns empty rows if market data is unavailable
    """
    await ensure_logged_in(page)

    url = f"{BASE_SAHAM_URL}/{kode}"
    # Use domcontentloaded for faster page load (don't wait for all resources)
    await page.goto(url, timeout=TIMEOUT, wait_until="domcontentloaded")
    await page.wait_for_url(f"**/{kode}", timeout=TIMEOUT)

    curr_time = time.strftime('%Y-%m-%d %H:%M:%S')

    # === Wait for orderbook data to load ===
    try:
        # Wait specifically for price items which indicates orderbook is rendered
        await page.wait_for_selector(".item-price", timeout=10000)
    except Exception:
        # Timeout means data didn't load -> trigger retry
        raise Exception("Timeout waiting for orderbook data (selector .item-price not found)")

    # === Extract Bid Data (Buy Orders) ===
    # First column contains bid information
    bid_lots = await page.locator("div.css-jw5rjj:nth-child(1) .item-lot").all_inner_texts()
    bid_prices = await page.locator("div.css-jw5rjj:nth-child(1) .item-price").all_inner_texts()

    # === Extract Ask Data (Sell Orders) ===
    # Second column contains ask information
    ask_prices = await page.locator("div.css-jw5rjj:nth-child(2) .item-price").all_inner_texts()
    ask_lots = await page.locator("div.css-jw5rjj:nth-child(2) .item-lot").all_inner_texts()

    # Determine max length to handle mismatched array sizes
    max_len = max(len(bid_lots), len(bid_prices),
                  len(ask_prices), len(ask_lots))

    if max_len == 0:
        # Data found but empty -> trigger retry
        raise Exception("Data found but empty rows (possible DOM change or empty market)")

    # === Build DataFrame rows ===
    # Combine bid and ask data row by row (fillvalue=None for missing entries)
    rows = []
    for b_lot, b_price, a_price, a_lot in zip_longest(bid_lots, bid_prices, ask_prices, ask_lots, fillvalue=None):
        rows.append({
            "kode": kode,
            "bid_lot": b_lot,
            "bid_price": b_price,
            "ask_price": a_price,
            "ask_lot": a_lot,
            "timestamp": curr_time,
        })

    return pd.DataFrame(rows)


async def scrape_stock_with_context(browser, kode, browser_id, storage_state):
    """Perform single scrape attempt with isolated browser context.
    
    Creates a new browser context (tab) with the shared authentication state,
    attempts to scrape the stock, and captures a screenshot on failure for debugging.
    
    Args:
        browser: Playwright browser instance
        kode: Stock ticker to scrape
        browser_id: Browser identifier for logging
        storage_state: Shared authentication session state
        
    Returns:
        dict: Result with 'success', 'kode', 'data' (DataFrame), and 'error' fields
        
    Note:
        - Creates isolated context for each stock (prevents cross-contamination)
        - Blocks unnecessary resources (images, fonts, media) for faster loads
        - Must keep scripts/XHR enabled as Ajaib is a React SPA
        - Captures screenshot to error_screenshots/ folder on failure
    """
    context = None
    page = None
    try:
        # Create new context with shared authentication
        context = await browser.new_context(storage_state=storage_state)
        page = await context.new_page()

        # Block unnecessary resources for speed optimization
        # Cannot block 'script' because Ajaib is a React App (needs JS to render)
        await page.route("**/*", lambda route: route.continue_()
            if route.request.resource_type in ["script", "xhr", "fetch", "document"]
            else route.abort() if route.request.resource_type in ["image","font","media"] else route.continue_())
        
        df = await scrape_stock(page, kode)
        return {"success": True, "kode": kode, "data": df, "error": None}
    except Exception as e:
        # Capture screenshot on failure for debugging
        try:
            if page:
                if not os.path.exists("error_screenshots"):
                    os.makedirs("error_screenshots")
                
                # Filename format: KODE_HHMMSS.png
                ts = datetime.now().strftime('%H%M%S')
                await page.screenshot(path=f"error_screenshots/{kode}_{ts}.png")
        except Exception as scr_err:
            print(f"[WARN] Failed to save screenshot: {scr_err}")

        return {"success": False, "kode": kode, "data": pd.DataFrame(), "error": str(e)}
    finally:
        # Always clean up context
        if context:
            try:
                await context.close()
            except:
                pass


async def scrape_with_retry(browser, kode, browser_id, storage_state, semaphore, max_retries=MAX_RETRIES):
    """Scrape a single stock with automatic retry and exponential backoff.
    
    Uses a semaphore to limit concurrent scraping operations per browser.
    Implements retry logic with exponential backoff on failure.
    
    Args:
        browser: Playwright browser instance
        kode: Stock ticker to scrape
        browser_id: Browser identifier for logging
        storage_state: Shared authentication session state
        semaphore: Asyncio semaphore to limit concurrency
        max_retries: Maximum number of retry attempts (default: MAX_RETRIES)
        
    Returns:
        dict: Final result after all retries with 'success', 'kode', 'data', 'error' fields
        
    Note:
        - Exponential backoff: waits attempt*2 seconds between retries (2s, 4s, 6s...)
        - Only returns success if data DataFrame is non-empty
        - Logs success on retry attempts > 1
    """
    async with semaphore:  # Limit concurrent operations
        for attempt in range(1, max_retries + 1):
            result = await scrape_stock_with_context(browser, kode, browser_id, storage_state)

            # Success if result is successful AND data is not empty
            if result["success"] and not result["data"].empty:
                if attempt > 1:
                    print(f"[SUCCESS]{kode} berhasil (attempt {attempt})")
                return result

            # Wait before next retry with exponential backoff
            if attempt < max_retries:
                wait_time = attempt * 2  # 2s, 4s, 6s...
                await asyncio.sleep(wait_time)

        # All attempts failed
        print(
            f"[ERROR] {kode} gagal setelah {max_retries} attempts: {result['error']}")
        return result


# =============================================================================
# BROWSER MANAGEMENT
# =============================================================================

async def scrape_with_one_browser(playwright, browser_id, kode_list, storage_state):
    """Manage one browser instance to scrape multiple stocks concurrently.
    
    Launches a Chromium browser and creates multiple concurrent scraping tasks
    within that browser, controlled by a semaphore to prevent memory overload.
    Each stock is scraped with retry logic.
    
    Args:
        playwright: Playwright instance
        browser_id: Identifier for logging (e.g., 1, 2, 3)
        kode_list: List of stock codes assigned to this browser
        storage_state: Shared authentication session state
        
    Returns:
        dict: {'success': list of DataFrames, 'failed': list of error dicts}
              where each error dict has 'kode' and 'error' keys
    """
    print(f"[BROWSER] Browser-{browser_id} starting with {len(kode_list)} emiten")

    browser = None
    try:
        browser = await playwright.chromium.launch(headless=True)
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_PER_BROWSER)  # Limit concurrent pages

        # Create all scraping tasks with retry logic
        tasks = [
            scrape_with_retry(browser, kode, browser_id,
                              storage_state, semaphore)
            for kode in kode_list
        ]

        # Execute all tasks concurrently
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Separate successful and failed results
        success_data = []
        failed_list = []

        for result in results:
            if isinstance(result, Exception):
                failed_list.append({"kode": "unknown", "error": str(result)})
            elif result["success"] and not result["data"].empty:
                success_data.append(result["data"])
            else:
                failed_list.append(
                    {"kode": result["kode"], "error": result["error"]})

        print(
            f"[SUCCESS]Browser-{browser_id} done: {len(success_data)}/{len(kode_list)} success")
        return {"success": success_data, "failed": failed_list}

    except Exception as e:
        print(f"[ERROR] Browser-{browser_id} fatal error: {e}")
        return {"success": [], "failed": [{"kode": k, "error": str(e)} for k in kode_list]}
    finally:
        # Always close browser to free resources
        if browser:
            try:
                await asyncio.sleep(0.5)  # Small delay for graceful shutdown
                await browser.close()
            except Exception as e:
                print(f"[WARN] Error closing browser-{browser_id}: {e}")


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

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
    return [lst[i*k+min(i, m):(i+1)*k+min(i+1, m)] for i in range(n)]


async def scrape_all_with_multiple_browsers(playwright, list_kode):
    """Coordinate parallel scraping across multiple browser instances.
    
    Phase 1: Performs one-time login and captures session state
    Phase 2: Splits stock list among NUM_BROWSERS browser instances
    Phase 3: Runs all browsers in parallel with shared authentication
    
    Args:
        playwright: Playwright instance
        list_kode: Complete list of stock codes to scrape
        
    Returns:
        tuple: (all_success, all_failed) where:
               - all_success is list of DataFrames with scraped data
               - all_failed is list of error dicts with 'kode' and 'error' keys
               
    Note:
        This is the main orchestration function for the scraping process.
    """

    # === Phase 1: Login once and capture session ===
    storage_state = await login_once_and_get_storage_state(playwright)

    # === Phase 2: Divide work among browsers ===
    chunks = split_list(list_kode, NUM_BROWSERS)

    print(f"\n[INFO] Pembagian Kerja:")
    for i, chunk in enumerate(chunks, 1):
        print(f"   Browser-{i}: {len(chunk)} emiten")
    print()

    # === Phase 3: Run all browsers in parallel ===
    tasks = [
        scrape_with_one_browser(playwright, i+1, chunk, storage_state)
        for i, chunk in enumerate(chunks)
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # === Aggregate results from all browsers ===
    all_success = []
    all_failed = []

    for i, result in enumerate(results):
        if isinstance(result, Exception):
            print(f"[ERROR] Browser-{i+1} completely failed: {result}")
        else:
            all_success.extend(result["success"])
            all_failed.extend(result["failed"])

    return all_success, all_failed


def log_failed_emiten(failed_list, cycle):
    """Save failed stock scrapes to CSV log file for tracking.
    
    Appends failed scrape information to a CSV file with cycle number,
    stock code, error message, and timestamp. Creates file if it doesn't exist.
    
    Args:
        failed_list: List of failure dicts with 'kode' and 'error' keys
        cycle: Cycle/run number for identification
        
    Note:
        - Appends to existing file or creates new one
        - Includes header only on first write
        - File format: cycle, kode, error, timestamp
    """
    if not failed_list:
        return

    # Create DataFrame with failure information
    failed_df = pd.DataFrame([
        {
            "cycle": cycle,
            "kode": f["kode"],
            "error": f["error"],
            "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        for f in failed_list
    ])

    # Write header only if file doesn't exist or is empty
    write_header = not os.path.exists(
        FAILED_LOG_FILE) or os.path.getsize(FAILED_LOG_FILE) == 0
    failed_df.to_csv(FAILED_LOG_FILE, mode='a',
                     index=False, header=write_header)


# =============================================================================
# MAIN EXECUTION FUNCTIONS
# =============================================================================

async def scrape_every_15_minutes(playwright, list_kode):
    """Run scraping in infinite loop with 15-minute intervals.
    
    NOTE: This function is currently unused. Periodic execution is handled by
    worker.py which runs the entire script at configurable intervals.
    
    Args:
        playwright: Playwright instance
        list_kode: List of stock codes to scrape
        
    Note:
        - Infinite loop until KeyboardInterrupt
        - Saves results to CSV and logs failures each cycle
        - 15 minute wait between cycles
    """
    print("[INFO] Scraping started - Every 15 minutes\n")
    print(f"[INFO] Total emiten: {len(list_kode)}")
    print(f"[BROWSER] Browsers: {NUM_BROWSERS}")
    print(f"[INFO] Concurrent per browser: {MAX_CONCURRENT_PER_BROWSER}")
    print(f"[INFO] Max retries: {MAX_RETRIES}")
    print(f"[INFO]  Timeout: {TIMEOUT/1000}s\n")

    cycle = 1
    while True:  # Infinite loop
        print(f"\n{'='*60}")
        print(f"[INFO] CYCLE {cycle} - {time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*60}\n")

        start_time = time.time()

        # Execute main scraping
        all_success, all_failed = await scrape_all_with_multiple_browsers(playwright, list_kode)

        elapsed = time.time() - start_time

        # Calculate statistics
        total = len(list_kode)
        success_count = len(all_success)
        failed_count = len(all_failed)
        success_rate = (success_count / total * 100) if total > 0 else 0

        print(f"\n{'='*60}")
        print(f"[INFO] CYCLE {cycle} SUMMARY")
        print(f"{'='*60}")
        print(f"[INFO]  Time: {elapsed:.2f}s ({elapsed/60:.2f} min)")
        print(f"[SUCCESS]Success: {success_count}/{total} ({success_rate:.1f}%)")
        print(f"[ERROR] Failed: {failed_count}/{total} ({100-success_rate:.1f}%)")
        print(f"{'='*60}\n")

        # Save successful results to CSV
        if all_success:
            final_df = pd.concat(all_success, ignore_index=True)
            async with csv_lock:  # Prevent concurrent writes
                write_header = not os.path.exists(
                    CSV_FILE) or os.path.getsize(CSV_FILE) == 0
                final_df.to_csv(CSV_FILE, mode='a',
                                index=False, header=write_header)
                print(f"[SAVED] Data saved: {len(final_df)} rows to {CSV_FILE}")

        # Log failures
        if all_failed:
            log_failed_emiten(all_failed, cycle)
            print(
                f"[LOG] Failed log saved: {len(all_failed)} emiten to {FAILED_LOG_FILE}")
            print(
                f"   Failed emiten: {', '.join([f['kode'] for f in all_failed[:10]])}")
            if len(all_failed) > 10:
                print(f"   ... and {len(all_failed) - 10} more")

        # Wait before next cycle
        print(f"\n[INFO]  Waiting 15 minutes for next cycle...\n")
        await asyncio.sleep(900)  # 15 minutes
        cycle += 1

async def scrape_once(playwright, list_kode):
    """Execute scraping once and exit.
    
    This is the main execution mode for the script when run standalone.
    Performs a single scraping run of all stocks and inserts results into MySQL.
    
    Workflow:
    1. Print configuration summary
    2. Execute parallel scraping with all browsers
    3. Calculate and display statistics
    4. Insert successful results into MySQL database
    5. Log failed stocks to CSV
    
    Args:
        playwright: Playwright instance
        list_kode: Complete list of stock codes to scrape
        
    Note:
        - CSV output is disabled (commented out) - uses MySQL instead
        - Failed stocks are logged to failed_emiten.csv for tracking
        - Called by main() when script is run directly
    """
    print("[START] Scraping started - Single run\n")
    print(f"[INFO] Total emiten: {len(list_kode)}")
    print(f"[BROWSER] Browsers: {NUM_BROWSERS}")
    print(f"[INFO] Concurrent per browser: {MAX_CONCURRENT_PER_BROWSER}")
    print(f"[INFO] Max retries: {MAX_RETRIES}")
    print(f"[INFO]  Timeout: {TIMEOUT/1000}s\n")

    start_time = time.time()
    all_success, all_failed = await scrape_all_with_multiple_browsers(playwright, list_kode)
    elapsed = time.time() - start_time

    # Calculate statistics
    total = len(list_kode)
    success_count = len(all_success)
    failed_count = len(all_failed)
    success_rate = (success_count / total * 100) if total > 0 else 0

    # Print execution summary
    print(f"\n{'='*60}")
    print("[INFO] RUN SUMMARY")
    print(f"{'='*60}")
    print(f"[INFO]  Time: {elapsed:.2f}s ({elapsed/60:.2f} min)")
    print(f"[SUCCESS]Success: {success_count}/{total} ({success_rate:.1f}%)")
    print(f"[ERROR] Failed: {failed_count}/{total} ({100-success_rate:.1f}%)")
    print(f"{'='*60}\n")

    # Legacy CSV saving (disabled - now using MySQL)
    # NOTE: no need to save to CSV since we use MySQL now
    # if all_success:
    #     final_df = pd.concat(all_success, ignore_index=True)
    #     async with csv_lock:
    #         write_header = not os.path.exists(CSV_FILE) or os.path.getsize(CSV_FILE) == 0
    #         final_df.to_csv(CSV_FILE, mode='a', index=False, header=write_header)
    #         print(f"[SAVED] CSV saved: {len(final_df)} rows to {CSV_FILE}")

    # Insert data to MySQL database
    if all_success:
        try:
            rows = flatten_rows_ajaib(all_success)
            push_to_database(rows, table_name="orderbook_ajaib")
        except Exception as e:
            print(f"[ERROR] DB insert failed: {e}")

    # Log failed stocks to CSV for tracking
    if all_failed:
        log_failed_emiten(all_failed, cycle=1)
        print(f"[LOG] Failed log saved: {len(all_failed)} emiten to {FAILED_LOG_FILE}")
        print(f"   Failed emiten: {', '.join([f['kode'] for f in all_failed[:10]])}"
              f"{' ...' if len(all_failed) > 10 else ''}")

# =============================================================================
# SCRIPT ENTRY POINT
# =============================================================================

async def main():
    """Main entry point for the scraper.
    
    Initializes Playwright and executes a single scraping run.
    Handles KeyboardInterrupt gracefully for clean shutdown.
    
    Note:
        Uses scrape_once() for single execution.
        For periodic execution, worker.py runs this entire script at intervals.
    """
    async with async_playwright() as p:
        try:
            await scrape_once(p, list_kode)
        except KeyboardInterrupt:
            print("\n[WARN] Keyboard interrupt detected")
        finally:
            print("[STOPPED] Program stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[STOPPED] Program dihentikan oleh user")