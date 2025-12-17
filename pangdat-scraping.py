import asyncio
import os
import time
import pandas as pd
from dotenv import load_dotenv
from playwright.async_api import async_playwright
from itertools import zip_longest
from datetime import datetime

load_dotenv()

EMAIL = os.getenv("EMAIL")
PASSWORD = os.getenv("PASSWORD")
PIN_CODE = os.getenv("PINCODE")

LOGIN_URL = "https://login.ajaib.co.id/login"
BASE_SAHAM_URL = "https://invest.ajaib.co.id/home/saham"

PIN_CHECK_INTERVAL = 5000
CSV_FILE = "scrap_result.csv"
FAILED_LOG_FILE = "failed_emiten.csv"

# df_saham = pd.read_excel("Daftar Saham.xlsx")
df_saham = pd.read_excel("daftar 50 saham.xlsx")
list_kode = df_saham["Kode"].tolist()

# Config - Conservative for Stability
NUM_BROWSERS = 2
MAX_CONCURRENT_PER_BROWSER = 5  # Reduced to prevent timeouts
MAX_RETRIES = 3
TIMEOUT = 60000  # Increased to 60 seconds

csv_lock = asyncio.Lock()


# ============================================================
# LOGIN FUNCTION
# ============================================================
async def login_once_and_get_storage_state(playwright):
    """Login 1x untuk semua browser"""
    print(f"🔐 Login...")

    browser = await playwright.chromium.launch(headless=False)
    context = await browser.new_context()
    page = await context.new_page()

    try:
        await page.goto(LOGIN_URL)
        await page.fill('input[name=email]', EMAIL)
        await page.fill('input[name=password]', PASSWORD)
        await page.click('button[type=submit]')
        await page.wait_for_selector('.pincode-input-container', timeout=15000)

        await page.locator('.pincode-input-text').first.click()
        await page.keyboard.type(PIN_CODE, delay=150)
        await page.wait_for_timeout(PIN_CHECK_INTERVAL)
        await page.wait_for_url('**/home')

        try:
            await page.get_by_role("button", name="Mengerti").click()
        except:
            pass

        storage_state = await context.storage_state()
        print(f"✅ Login sukses! Session shared ke {NUM_BROWSERS} browsers")
        return storage_state

    finally:
        await context.close()
        await browser.close()


# ============================================================
# ENSURE LOGGED IN
# ============================================================
async def ensure_logged_in(page):
    """Check session validity"""
    try:
        current_url = page.url
    except Exception:
        raise Exception("Page is closed")

    if "/pin" in current_url:
        print(f"⚠️ PIN diminta ulang")
        await page.locator('.pincode-input-text').first.click()
        await page.keyboard.type(PIN_CODE, delay=150)
        await page.wait_for_timeout(PIN_CHECK_INTERVAL)

    if "/login" in current_url:
        raise Exception("Session expired")


# ============================================================
# SCRAPE 1 EMITEN
# ============================================================
async def scrape_stock(page, kode):
    """Scrape single stock"""
    await ensure_logged_in(page)

    url = f"{BASE_SAHAM_URL}/{kode}"
    # Wait domcontentloaded instead of load (faster)
    await page.goto(url, timeout=TIMEOUT, wait_until="domcontentloaded")
    await page.wait_for_url(f"**/{kode}", timeout=TIMEOUT)

    curr_time = time.strftime('%Y-%m-%d %H:%M:%S')

    # Wait for the orderbook container or price items to appear
    try:
        # Wait specifically for the item-price class which indicates data loaded
        # Timeout slightly less than function timeout to allow for capture
        await page.wait_for_selector(".item-price", timeout=10000)
    except Exception:
        # If timeout, it means data didn't load -> Raise error to trigger retry
        raise Exception("Timeout waiting for orderbook data (selector .item-price not found)")

    # BID
    # Using specific class selectors as before, but wrapped in try-catch logic above implicitly
    bid_lots = await page.locator("div.css-jw5rjj:nth-child(1) .item-lot").all_inner_texts()
    bid_prices = await page.locator("div.css-jw5rjj:nth-child(1) .item-price").all_inner_texts()

    # ASK
    ask_prices = await page.locator("div.css-jw5rjj:nth-child(2) .item-price").all_inner_texts()
    ask_lots = await page.locator("div.css-jw5rjj:nth-child(2) .item-lot").all_inner_texts()

    max_len = max(len(bid_lots), len(bid_prices),
                  len(ask_prices), len(ask_lots))

    if max_len == 0:
        # Raise exception so it counts as a failure and triggers retry
        raise Exception("Data found but empty rows (possible DOM change or empty market)")

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


# ============================================================
# SCRAPE WITH CONTEXT (SINGLE ATTEMPT)
# ============================================================
async def scrape_stock_with_context(browser, kode, browser_id, storage_state):
    """Single scrape attempt"""
    context = None
    page = None
    try:
        context = await browser.new_context(storage_state=storage_state)
        page = await context.new_page()

        # Block unnecessary resources untuk speed up
        # We cannot block 'script' because Ajaib is a React App (needs JS to render)
        await page.route("**/*", lambda route: route.abort()
                         if route.request.resource_type in ["image", "font", "stylesheet", "media"]
                         else route.continue_())

        df = await scrape_stock(page, kode)
        return {"success": True, "kode": kode, "data": df, "error": None}
    except Exception as e:
        # Capture screenshot on failure
        try:
            if page:
                if not os.path.exists("error_screenshots"):
                    os.makedirs("error_screenshots")
                
                # Format: error_KODE_HHMMSS.png
                ts = datetime.now().strftime('%H%M%S')
                await page.screenshot(path=f"error_screenshots/{kode}_{ts}.png")
        except Exception as scr_err:
            print(f"⚠️ Failed to save screenshot: {scr_err}")

        return {"success": False, "kode": kode, "data": pd.DataFrame(), "error": str(e)}
    finally:
        if context:
            try:
                await context.close()
            except:
                pass


# ============================================================
# SCRAPE WITH RETRY
# ============================================================
async def scrape_with_retry(browser, kode, browser_id, storage_state, semaphore, max_retries=MAX_RETRIES):
    """Scrape dengan retry mechanism"""
    async with semaphore:
        for attempt in range(1, max_retries + 1):
            result = await scrape_stock_with_context(browser, kode, browser_id, storage_state)

            if result["success"] and not result["data"].empty:
                if attempt > 1:
                    print(f"✅ {kode} berhasil (attempt {attempt})")
                return result

            if attempt < max_retries:
                wait_time = attempt * 2  # Exponential backoff
                await asyncio.sleep(wait_time)

        # All attempts failed
        print(
            f"❌ {kode} gagal setelah {max_retries} attempts: {result['error']}")
        return result


# ============================================================
# SCRAPE WITH ONE BROWSER
# ============================================================
async def scrape_with_one_browser(playwright, browser_id, kode_list, storage_state):
    """1 Browser handle batch kode"""
    print(f"🌐 Browser-{browser_id} starting with {len(kode_list)} emiten")

    browser = None
    try:
        browser = await playwright.chromium.launch(headless=True)
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_PER_BROWSER)

        # Create tasks with retry
        tasks = [
            scrape_with_retry(browser, kode, browser_id,
                              storage_state, semaphore)
            for kode in kode_list
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Separate success and failed
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
            f"✅ Browser-{browser_id} done: {len(success_data)}/{len(kode_list)} success")
        return {"success": success_data, "failed": failed_list}

    except Exception as e:
        print(f"❌ Browser-{browser_id} fatal error: {e}")
        return {"success": [], "failed": [{"kode": k, "error": str(e)} for k in kode_list]}
    finally:
        if browser:
            try:
                await asyncio.sleep(0.5)
                await browser.close()
            except Exception as e:
                print(f"⚠️ Error closing browser-{browser_id}: {e}")


# ============================================================
# SPLIT LIST
# ============================================================
def split_list(lst, n):
    """Split list into n chunks"""
    k, m = divmod(len(lst), n)
    return [lst[i*k+min(i, m):(i+1)*k+min(i+1, m)] for i in range(n)]


# ============================================================
# MAIN SCRAPING FUNCTION
# ============================================================
async def scrape_all_with_multiple_browsers(playwright, list_kode):
    """Phase 1: Main scraping dengan all browsers"""

    # Login fresh
    storage_state = await login_once_and_get_storage_state(playwright)

    # Split work
    chunks = split_list(list_kode, NUM_BROWSERS)

    print(f"\n📊 Pembagian Kerja:")
    for i, chunk in enumerate(chunks, 1):
        print(f"   Browser-{i}: {len(chunk)} emiten")
    print()

    # Run all browsers parallel
    tasks = [
        scrape_with_one_browser(playwright, i+1, chunk, storage_state)
        for i, chunk in enumerate(chunks)
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Combine results
    all_success = []
    all_failed = []

    for i, result in enumerate(results):
        if isinstance(result, Exception):
            print(f"❌ Browser-{i+1} completely failed: {result}")
        else:
            all_success.extend(result["success"])
            all_failed.extend(result["failed"])

    return all_success, all_failed


# ============================================================
# LOG FAILED EMITEN
# ============================================================
def log_failed_emiten(failed_list, cycle):
    """Save failed emiten to CSV"""
    if not failed_list:
        return

    failed_df = pd.DataFrame([
        {
            "cycle": cycle,
            "kode": f["kode"],
            "error": f["error"],
            "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        for f in failed_list
    ])

    write_header = not os.path.exists(
        FAILED_LOG_FILE) or os.path.getsize(FAILED_LOG_FILE) == 0
    failed_df.to_csv(FAILED_LOG_FILE, mode='a',
                     index=False, header=write_header)


# ============================================================
# MAIN PERIODIC SCRAPING
# ============================================================
async def scrape_every_15_minutes(playwright, list_kode):
    print("⏳ Scraping started - Every 15 minutes\n")
    print(f"📋 Total emiten: {len(list_kode)}")
    print(f"🌐 Browsers: {NUM_BROWSERS}")
    print(f"⚡ Concurrent per browser: {MAX_CONCURRENT_PER_BROWSER}")
    print(f"🔄 Max retries: {MAX_RETRIES}")
    print(f"⏱️  Timeout: {TIMEOUT/1000}s\n")

    cycle = 1
    while True:
        print(f"\n{'='*60}")
        print(f"🔄 CYCLE {cycle} - {time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*60}\n")

        start_time = time.time()

        # Main scraping
        all_success, all_failed = await scrape_all_with_multiple_browsers(playwright, list_kode)

        elapsed = time.time() - start_time

        # Summary
        total = len(list_kode)
        success_count = len(all_success)
        failed_count = len(all_failed)
        success_rate = (success_count / total * 100) if total > 0 else 0

        print(f"\n{'='*60}")
        print(f"📊 CYCLE {cycle} SUMMARY")
        print(f"{'='*60}")
        print(f"⏱️  Time: {elapsed:.2f}s ({elapsed/60:.2f} min)")
        print(f"✅ Success: {success_count}/{total} ({success_rate:.1f}%)")
        print(f"❌ Failed: {failed_count}/{total} ({100-success_rate:.1f}%)")
        print(f"{'='*60}\n")

        # Save results
        if all_success:
            final_df = pd.concat(all_success, ignore_index=True)
            async with csv_lock:
                write_header = not os.path.exists(
                    CSV_FILE) or os.path.getsize(CSV_FILE) == 0
                final_df.to_csv(CSV_FILE, mode='a',
                                index=False, header=write_header)
                print(f"💾 Data saved: {len(final_df)} rows to {CSV_FILE}")

        # Log failed
        if all_failed:
            log_failed_emiten(all_failed, cycle)
            print(
                f"📝 Failed log saved: {len(all_failed)} emiten to {FAILED_LOG_FILE}")
            print(
                f"   Failed emiten: {', '.join([f['kode'] for f in all_failed[:10]])}")
            if len(all_failed) > 10:
                print(f"   ... and {len(all_failed) - 10} more")

        print(f"\n⏱️  Waiting 15 minutes for next cycle...\n")
        await asyncio.sleep(900)
        cycle += 1


# ============================================================
# MAIN
# ============================================================
async def main():
    async with async_playwright() as p:
        try:
            await scrape_every_15_minutes(p, list_kode)
        except KeyboardInterrupt:
            print("\n⚠️ Keyboard interrupt detected")
        finally:
            print("🛑 Program stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Program dihentikan oleh user")
