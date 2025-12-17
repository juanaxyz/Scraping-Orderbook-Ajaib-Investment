import asyncio
import aiohttp
import pandas as pd
from datetime import datetime
from playwright.async_api import async_playwright
from dotenv import load_dotenv
import os
import random
import time
import mysql.connector

load_dotenv()

# konfigurasi
LOGIN_URL = "https://invest.ajaib.co.id/login"
EMAIL = os.getenv("EMAIL")
PASSWORD = os.getenv("PASSWORD")
PIN_CODE = os.getenv("PINCODE")
PIN_CHECK_INTERVAL = 3000

CODES = pd.read_excel("daftar saham.xlsx")["Kode"].tolist()
URL = "https://ht2.ajaib.co.id/api/v1/stock/bestquote/"

# Config Rate Limiting
MAX_CONCURRENT = 5  # Turunkan drastis untuk avoid 429
DELAY_BETWEEN_REQUESTS = 0.2  # 200ms delay antar request
RETRY_ON_429_DELAY = 5  # Tunggu 5 detik jika kena rate limit

# Global
intercepted_headers = {}
playwright_instance = None
sem = asyncio.Semaphore(MAX_CONCURRENT)


def push_to_database(df):
    """Push DataFrame ke MySQL Database"""
    try:
        connection = mysql.connector.connect(
            host=os.getenv("DB_HOST"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            database=os.getenv("DB_NAME")
        )

        cursor = connection.cursor()

        for _, row in df.iterrows():
            sql = """
                INSERT INTO orderbook (kode, side, price, lot, num, timestamp)
                VALUES (%s, %s, %s, %s, %s, %s)
            """
            values = (row['kode'], row['side'], row['price'],
                      row['lot'], row['num'], row['timestamp'])
            cursor.execute(sql, values)

        connection.commit()
        print(f"✅ Inserted {len(df)} rows into database")

    except mysql.connector.Error as err:
        print(f"❌ Database error: {err}")

    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()


async def login_and_get_headers(playwright):
    """Login 1x lalu intercept request untuk ambil JWT + semua headers"""
    print("🔐 Login Ajaib via Playwright...")

    browser = await playwright.chromium.launch(headless=False)
    context = await browser.new_context()
    page = await context.new_page()

    headers_captured = asyncio.Event()

    async def handle_request(route, request):
        if "ht2.ajaib.co.id/api" in request.url:
            headers = request.headers

            intercepted_headers.clear()  # Clear old headers
            intercepted_headers["Authorization"] = headers.get(
                "authorization", "")
            intercepted_headers["X-Device-Signature"] = headers.get(
                "x-device-signature", "")
            intercepted_headers["X-Ht-Ver-Id"] = headers.get("x-ht-ver-id", "")
            intercepted_headers["User-Agent"] = headers.get("user-agent", "")
            intercepted_headers["X-Platform"] = headers.get(
                "x-platform", "WEB")
            intercepted_headers["X-Product"] = headers.get(
                "x-product", "stock-mf")
            intercepted_headers["X-Device-Name"] = headers.get(
                "x-device-name", "")
            intercepted_headers["Sec-Ch-Ua-Platform"] = headers.get(
                "sec-ch-ua-platform", "")
            intercepted_headers["Sec-Ch-Ua"] = headers.get("sec-ch-ua", "")
            intercepted_headers["Sec-Ch-Ua-Mobile"] = headers.get(
                "sec-ch-ua-mobile", "")
            intercepted_headers["Accept-Language"] = headers.get(
                "accept-language", "id")
            intercepted_headers["Origin"] = "https://invest.ajaib.co.id"
            intercepted_headers["Referer"] = "https://invest.ajaib.co.id/"
            intercepted_headers["Accept"] = "*/*"
            intercepted_headers["Sec-Fetch-Site"] = "same-site"
            intercepted_headers["Sec-Fetch-Mode"] = "cors"
            intercepted_headers["Sec-Fetch-Dest"] = "empty"

            print(f"✅ Headers intercepted")
            if intercepted_headers["Authorization"]:
                print(
                    f"🔑 Authorization: {intercepted_headers['Authorization'][:50]}...")
                headers_captured.set()

        await route.continue_()

    await page.route("**/*", handle_request)

    try:
        # Login
        await page.goto(LOGIN_URL, timeout=15000)
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

        print("✅ Login sukses")

        # Trigger API request
        print("📡 Triggering API request...")
        await page.goto("https://invest.ajaib.co.id/home/saham/BBRI", wait_until="domcontentloaded")

        try:
            await asyncio.wait_for(headers_captured.wait(), timeout=10)
            print("✅ Headers captured successfully!")
        except asyncio.TimeoutError:
            print("⚠️ Timeout waiting for headers")

        return dict(intercepted_headers)

    finally:
        await context.close()
        await browser.close()


def parse_orderbook(json_data):
    rows = []
    kode = json_data["code"]

    ts = datetime.fromtimestamp(
        json_data["buy_side"]["unix_time"] / 1000
    )

    # BID
    for item in json_data["buy_side"]["items"]:
        rows.append({
            "kode": kode,
            "side": "B",
            "price": item["price"],
            "lot": item["lot"],
            "num": item["num"],
            "timestamp": ts
        })

    # ASK
    for item in json_data["sell_side"]["items"]:
        rows.append({
            "kode": kode,
            "side": "S",
            "price": item["price"],
            "lot": item["lot"],
            "num": item["num"],
            "timestamp": ts
        })

    return rows


async def fetch(session, code, headers_ref):
    """Fetch dengan retry untuk 401 dan 429"""
    async with sem:
        # Random delay untuk avoid rate limit
        await asyncio.sleep(DELAY_BETWEEN_REQUESTS + random.uniform(0, 0.1))

        max_retries = 3
        for attempt in range(1, max_retries + 1):
            try:
                # Update headers dari reference (bisa berubah jika re-login)
                session._default_headers.update(headers_ref)

                async with session.get(URL, params={"code": code}) as r:
                    if r.status == 401:
                        print(
                            f"⚠️ 401 Unauthorized for {code} - Token expired")
                        if attempt < max_retries:
                            print(f"   🔄 Will re-login and retry...")
                            return {"code": code, "status": 401, "data": None}
                        return None

                    elif r.status == 429:
                        print(f"⚠️ 429 Rate Limited for {code}")
                        if attempt < max_retries:
                            wait_time = RETRY_ON_429_DELAY * attempt
                            print(
                                f"   ⏱️  Waiting {wait_time}s before retry...")
                            await asyncio.sleep(wait_time)
                            continue
                        return None

                    elif r.status != 200:
                        print(f"❌ Failed {code} status: {r.status}")
                        return None

                    data = await r.json()

                    if "code" not in data or "buy_side" not in data or "sell_side" not in data:
                        print(f"⚠️ Unexpected data format for {code}")
                        return None

                    rows = parse_orderbook(data)
                    df = pd.DataFrame(rows)
                    print(f"✅ {code} success - {len(rows)} rows")
                    return {"code": code, "status": 200, "data": df}

            except Exception as e:
                print(f"⚠️ Error fetching {code}: {e}")
                if attempt < max_retries:
                    await asyncio.sleep(2)
                    continue
                return None

        return None


async def fetch_batch_with_relogin(playwright, codes, initial_headers):
    """Fetch dengan auto re-login jika kena 401"""
    headers_ref = initial_headers.copy()

    async with aiohttp.ClientSession(headers=headers_ref) as session:
        results = []
        batch_size = 100  # Process in batches

        # tes 1 code dulu
        test_result = await fetch(session, codes[0], headers_ref)
        if test_result and test_result.get("status") == 401:
            print("❌ Initial token invalid, re-logging in...")
            new_headers = await login_and_get_headers(playwright)
            headers_ref.update(new_headers)
            print("✅ Re-login successful, continuing...")

        for i in range(0, len(codes), batch_size):
            batch = codes[i:i+batch_size]
            print(
                f"\n📦 Processing batch {i//batch_size + 1}/{(len(codes)-1)//batch_size + 1} ({len(batch)} codes)")

            batch_results = await asyncio.gather(*(fetch(session, c, headers_ref) for c in batch))

            # Check if need re-login
            has_401 = any(r and r.get("status") ==
                          401 for r in batch_results if r)

            if has_401:
                print("\n🔄 Detected 401 errors - Re-logging in...")
                new_headers = await login_and_get_headers(playwright)
                headers_ref.update(new_headers)
                print("✅ Re-login successful, continuing...")

                # Retry failed codes
                failed_codes = [r["code"]
                                for r in batch_results if r and r.get("status") == 401]
                print(
                    f"🔄 Retrying {len(failed_codes)} codes with new token...")
                retry_results = await asyncio.gather(*(fetch(session, c, headers_ref) for c in failed_codes))

                # Merge results
                for i, r in enumerate(batch_results):
                    if r and r.get("status") == 401:
                        # Replace with retry result
                        retry_idx = failed_codes.index(r["code"])
                        batch_results[i] = retry_results[retry_idx]

            results.extend(batch_results)

            # Small pause between batches
            if i + batch_size < len(codes):
                print("⏱️  Pause 2s between batches...")
                await asyncio.sleep(2)

        return results


async def main():
    async with async_playwright() as p:
        # 1. Initial Login
        print("="*60)
        headers = await login_and_get_headers(p)

        while True:
            if not headers.get("Authorization"):
                print("❌ Failed to get Authorization token!")
                return

            print("\n" + "="*60)
            print("📋 Using headers:")
            print(f"   Authorization: {headers['Authorization'][:50]}...")
            print(
                f"   X-Device-Signature: {headers.get('X-Device-Signature', 'N/A')}")
            print("="*60 + "\n")

            # 2. Fetch with auto re-login
            print(f"🚀 Starting to fetch {len(CODES)} codes...")
            print(
                f"⚙️  Config: {MAX_CONCURRENT} concurrent, {DELAY_BETWEEN_REQUESTS}s delay\n")

            results = await fetch_batch_with_relogin(p, CODES, headers)

            # 3. Process results
            dfs = [r["data"]
                   for r in results if r and r.get("data") is not None]

            if dfs:
                final_df = pd.concat(dfs, ignore_index=True)
                final_df.to_csv("saham_idx.csv", mode='a',
                                header=False, index=False)
                print(f"\n{'='*60}")
                print(f"✅ SUCCESS!")
                try:
                    push_to_database(final_df)
                    print("Successfully pushed data to database.")
                except Exception as e:
                    print(f"❌ Failed to push data to database: {e}")
                print(f"📊 Saved {len(final_df)} rows to saham_idx.csv")
                print(
                    f"📈 Success rate: {len(dfs)}/{len(CODES)} ({len(dfs)/len(CODES)*100:.1f}%)")
                print(f"{'='*60}")
            else:
                print("\n❌ No valid data collected")

            print("\n⏱️  Waiting 15 Minute before next run...\n")
            time.sleep(900)  # 15 minutes


if __name__ == "__main__":
    asyncio.run(main())
