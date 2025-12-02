import asyncio
import os
import time
import pandas as pd
from dotenv import load_dotenv
from playwright.async_api import async_playwright

load_dotenv()

EMAIL = os.getenv("EMAIL")
PASSWORD = os.getenv("PASSWORD")
PIN_CODE = os.getenv("PINCODE")

LOGIN_URL = "https://login.ajaib.co.id/login"
BASE_SAHAM_URL = "https://invest.ajaib.co.id/home/saham"

PIN_CHECK_INTERVAL = 5000
CSV_FILE = "scrap_result.csv"


# ============================================================
# LOGIN FUNCTION
# ============================================================
async def login(page):
    print("🔐 Login...")

    await page.goto(LOGIN_URL)
    await page.fill('input[name=email]', EMAIL)
    await page.fill('input[name=password]', PASSWORD)
    await page.click('button[type=submit]')
    await page.wait_for_selector('.pincode-input-container', timeout=15000)

    await page.locator('.pincode-input-text').first.click()
    await page.keyboard.type(PIN_CODE, delay=150)
    await page.wait_for_timeout(PIN_CHECK_INTERVAL)

    await page.wait_for_url('**/home')

    # Klik "Mengerti" jika muncul
    try:
        await page.get_by_role("button", name="Mengerti").click()
    except:
        pass

    print("✅ Login sukses")


# ============================================================
# CHECK LOGIN / INPUT PIN KALAU KEMBALI KE /PIN
# ============================================================
async def ensure_logged_in(page):
    if "/pin" in page.url:
        print("⚠️ PIN diminta ulang, mengisi PIN...")
        await page.locator('.pincode-input-text').first.click()
        await page.keyboard.type(PIN_CODE, delay=150)
        await page.wait_for_timeout(PIN_CHECK_INTERVAL)
        print("✅ PIN berhasil diinput")

    if "home" not in page.url and "saham" not in page.url:
        print("⚠️ Tidak di halaman home/saham, login ulang...")
        await login(page)


# ============================================================
# SCRAPPING 1 KODE SAHAM
# ============================================================
async def scrape_stock(page, kode):
    await ensure_logged_in(page)

    print(f"📌 Scraping {kode} ...")
    url = f"{BASE_SAHAM_URL}/{kode}"
    await page.goto(url)
    await page.wait_for_url(f"**/{kode}", timeout=20000)

    curr_time = time.strftime('%Y-%m-%d %H:%M:%S')

    # BID
    bid_lots = await page.locator("div.css-jw5rjj:nth-child(1) .item-lot").all_inner_texts()
    bid_prices = await page.locator("div.css-jw5rjj:nth-child(1) .item-price").all_inner_texts()

    # ASK
    ask_prices = await page.locator("div.css-jw5rjj:nth-child(2) .item-price").all_inner_texts()
    ask_lots = await page.locator("div.css-jw5rjj:nth-child(2) .item-lot").all_inner_texts()

    df = pd.DataFrame({
        "kode": kode,
        "bid_lot": bid_lots,
        "bid_price": bid_prices,
        "ask_price": ask_prices,
        "ask_lot": ask_lots,
        "timestamp": curr_time
    })

    return df


# ============================================================
# SCRAPING PERIODIK TIAP 5 MENIT
# ============================================================
async def scrape_every_5_minutes(page, list_kode):
    print("⏳ Scraping dimulai... setiap 5 menit sekali.\n")

    # Jika belum ada CSV → buat header
    if not os.path.exists(CSV_FILE):
        pd.DataFrame().to_csv(CSV_FILE, index=False)

    while True:
        all_df = []

        for kode in list_kode:
            df = await scrape_stock(page, kode)
            all_df.append(df)

        final_df = pd.concat(all_df, ignore_index=True)

        print("\n📊 Hasil Scrap:")
        print(final_df)

        # Append ke CSV tanpa menghapus data sebelumnya
        final_df.to_csv(CSV_FILE, mode="a", index=False, header=False)

        print(f"💾 Data tersimpan ke {CSV_FILE}")
        print("⏱ Menunggu 5 menit untuk scrap berikutnya...\n")

        await asyncio.sleep(300)  # 300 detik = 5 menit


# ============================================================
# MAIN
# ============================================================
async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()

        await login(page)

        list_kode = ["BBCA"]  # Bisa tambah: ["BBCA", "BBRI", "BMRI"]

        await scrape_every_5_minutes(page, list_kode)


asyncio.run(main())
