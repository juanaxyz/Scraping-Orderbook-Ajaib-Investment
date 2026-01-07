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

# STOCK_LIST = ['ANTM', 'BBCA', 'BBRI', 'BMRI', 'TLKM', 'ASII', 'UNVR', 'ICBP']
STOCK_FILE = os.getenv("STOCK_FILE", "daftar 10 saham.xlsx")

# Parallel config
NUM_BROWSERS = 2
MAX_CONCURRENT_PER_BROWSER = 5
MAX_RETRIES = 3
PAGE_TIMEOUT = 30000  # ms
HEADLESS = True

def load_stock_list():
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
    if not text:
        return None
    cleaned = text.replace(',', '').replace('.', '').strip()
    if not cleaned:
        return None
    try:
        return int(cleaned)
    except ValueError:
        return None

def flatten_rows(results):
    rows = []
    for res in results:
        if res.get("error"):
            continue
        ts = datetime.fromisoformat(res.get("timestamp"))
        code = res.get("stock_code")
        for i, bid in enumerate(res.get("bids", []), start=1):
            rows.append((code, "B", _to_int(bid.get("price")), _to_int(bid.get("volume")), i, ts))
        for i, ask in enumerate(res.get("asks", []), start=1):
            rows.append((code, "A", _to_int(ask.get("price")), _to_int(ask.get("volume")), i, ts))
    return rows

def push_to_database(rows):
    conn = mysql.connector.connect(
        host=os.getenv("DB_HOST"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME"),
    )
    try:
        cur = conn.cursor()
        cur.executemany(
            "INSERT INTO orderbook_ipot (kode, side, price, lot, num, timestamp) VALUES (%s, %s, %s, %s, %s, %s)",
            rows,
        )
        conn.commit()
        print(f"[SUCCESS] Inserted {len(rows)} rows into DB")
    finally:
        cur.close()
        conn.close()

async def scrape_orderbook(page, stock_code):
    url = f"https://indopremier.com/#ipot/app/ipotbuzz/home/{stock_code}"
    page.set_default_timeout(PAGE_TIMEOUT)
    await page.goto(url, wait_until="domcontentloaded")

    # Ensure the orderbook container appears
    for _ in range(3):
        try:
            await page.wait_for_selector(".bidoff", timeout=10000)
            break
        except TimeoutError:
            await page.reload()
    else:
        raise Exception("Timeout: .bidoff not found after retries")

    data = {
        "stock_code": stock_code,
        "timestamp": datetime.now().isoformat(),
        "market_info": {},
        "bids": [],
        "asks": [],
        "total_bid_lot": None,
        "total_ask_lot": None,
    }

    # Market info
    try:
        mi_labels = await page.query_selector_all(".container-mi .mi .ob-mi-label")
        mi_values = await page.query_selector_all(".container-mi .mi .ob-mi-value")
        for label, value in zip(mi_labels, mi_values):
            ltext = (await label.inner_text()).strip()
            vtext = (await value.inner_text()).strip()
            data["market_info"][ltext] = vtext
    except Exception as e:
        print(f"[{stock_code}] Market info error: {e}")

    # Bids
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

    # Asks
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

    # Totals
    try:
        totals = await page.query_selector_all(".ob-mi-value.padding-right-half-half")
        if len(totals) >= 2:
            data["total_bid_lot"] = (await totals[0].inner_text()).strip()
            data["total_ask_lot"] = (await totals[1].inner_text()).strip()
    except Exception as e:
        print(f"[{stock_code}] Totals error: {e}")

    if not data["bids"] and not data["asks"]:
        raise Exception("No bid/ask rows found")
    return data

async def scrape_with_retry(browser, stock_code, semaphore, max_retries=MAX_RETRIES):
    async with semaphore:
        error = None
        for attempt in range(1, max_retries + 1):
            context = None
            page = None
            try:
                context = await browser.new_context()
                page = await context.new_page()
                # Skip heavy resources
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
                    await asyncio.sleep(attempt * 2)  # backoff
            finally:
                if context:
                    try:
                        await context.close()
                    except Exception:
                        pass
        print(f"[FAILED] {stock_code} failed after {max_retries} attempts: {error}")
        return {"success": False, "stock_code": stock_code, "data": {}, "error": error}

def split_list(lst, n):
    k, m = divmod(len(lst), n)
    return [lst[i * k + min(i, m):(i + 1) * k + min(i + 1, m)] for i in range(n)]

async def scrape_with_one_browser(playwright, browser_id, codes):
    print(f"[BROWSER-{browser_id}] Handling {len(codes)} stocks")
    browser = None
    try:
        browser = await playwright.chromium.launch(headless=HEADLESS)
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_PER_BROWSER)
        tasks = [scrape_with_retry(browser, code, semaphore) for code in codes]
        results = await asyncio.gather(*tasks, return_exceptions=True)

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
        if browser:
            try:
                await asyncio.sleep(0.2)
                await browser.close()
            except Exception:
                pass

async def scrape_all(playwright, codes):
    chunks = split_list(codes, NUM_BROWSERS)
    for i, chunk in enumerate(chunks, 1):
        print(f"   Browser-{i}: {len(chunk)} stocks")
    tasks = [scrape_with_one_browser(playwright, i + 1, chunk) for i, chunk in enumerate(chunks)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

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
    print(f"{'='*60}")
    print("Orderbook Scraper - IPOT (parallel)")
    print(f"Targets: {len(STOCK_LIST)} | Browsers: {NUM_BROWSERS} | Concurrency/browser: {MAX_CONCURRENT_PER_BROWSER}")
    print(f"{'='*60}\n")

    start = time.time()
    async with async_playwright() as p:
        success, failed = await scrape_all(p, STOCK_LIST)

    # NOTE: disabled saving to json since now we use MySQL
    # output_file = f"orderbook_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    # with open(output_file, "w", encoding="utf-8") as f:
    #     json.dump(success + failed, f, indent=2, ensure_ascii=False)

    rows = flatten_rows(success)
    if rows:
        try:
            push_to_database(rows)
        except Exception as e:
            print(f"[ERROR] DB insert failed: {e}")

    elapsed = time.time() - start
    success_count = len(success)
    failed_count = len(failed)
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"Time: {elapsed:.2f}s ({elapsed/60:.2f} min)")
    print(f"Success: {success_count}/{len(STOCK_LIST)} ({success_count/len(STOCK_LIST)*100:.1f}%)")
    print(f"Failed : {failed_count}/{len(STOCK_LIST)}")
    print(f"{'='*60}\n")

    if failed:
        sample = ", ".join(f["stock_code"] for f in failed[:10])
        extra = f" ... +{len(failed) - 10} more" if len(failed) > 10 else ""
        print(f"Failed samples: {sample}{extra}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[STOPPED] Stopped by user")