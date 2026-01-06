import json
from playwright.sync_api import sync_playwright
from multiprocessing import Pool, cpu_count
import time
from datetime import datetime
import os
import mysql.connector
from dotenv import load_dotenv

load_dotenv()
# List saham yang akan di-scrape
STOCK_LIST = ['ANTM', 'BBCA', 'BBRI', 'BMRI', 'TLKM', 'ASII', 'UNVR', 'ICBP']

def _to_int(text):
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
        if res.get('error'):
            continue
        ts = datetime.fromisoformat(res.get('timestamp'))
        code = res.get('stock_code')
        for i, bid in enumerate(res.get('bids', []), start=1):
            rows.append((code, 'B', _to_int(bid.get('price')), _to_int(bid.get('volume')), i, ts))
        for i, ask in enumerate(res.get('asks', []), start=1):
            rows.append((code, 'A', _to_int(ask.get('price')), _to_int(ask.get('volume')), i, ts))
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
        print(f"✅ Inserted {len(rows)} rows into DB")
    finally:
        cur.close()
        conn.close()

def scrape_orderbook(stock_code):
    """
    Fungsi untuk scrape orderbook satu saham
    """
    url = f"https://indopremier.com/#ipot/app/ipotbuzz/home/{stock_code}"

    try:
        with sync_playwright() as p:
            # Launch browser
            browser = p.chromium.launch(headless=False)
            context = browser.new_context()
            page = context.new_page()

            print(f"[{stock_code}] Mengakses URL: {url}")

            # Set default timeout ke 0 (unlimited)
            page.set_default_timeout(0)

            page.goto(url, wait_until="domcontentloaded", timeout=0)

            # refresh halaman ketika selector bidoff tidak muncul dalam 10 detik
            for i in range(3):
                try:
                    page.wait_for_selector('.bidoff', timeout=10000)
                except TimeoutError:
                    print(
                        f"[{stock_code}] Selector .bidoff tidak ditemukan, me-refresh halaman...")
                    page.reload()
                    i += 1

            # Struktur data
            orderbook_data = {
                'stock_code': stock_code,
                'timestamp': datetime.now().isoformat(),
                'market_info': {},
                'bids': [],
                'asks': [],
                'total_bid_lot': None,
                'total_ask_lot': None
            }

            # Scrape Market Info (Prev, Chg, Open, High, Low, dll)
            try:
                mi_labels = page.query_selector_all(
                    '.container-mi .mi .ob-mi-label')
                mi_values = page.query_selector_all(
                    '.container-mi .mi .ob-mi-value')

                for label, value in zip(mi_labels, mi_values):
                    label_text = label.inner_text().strip()
                    value_text = value.inner_text().strip()
                    orderbook_data['market_info'][label_text] = value_text

                print(
                    f"[{stock_code}] Market info: {len(orderbook_data['market_info'])} items")
            except Exception as e:
                print(f"[{stock_code}] Error scraping market info: {e}")

            # Scrape Bid Orders (sisi kiri)
            try:
                bid_container = page.query_selector(
                    '.bidoff .col-50:first-child')
                if bid_container:
                    bid_prices = bid_container.query_selector_all('.ob-price')
                    bid_volumes = bid_container.query_selector_all(
                        '.ob-value.padding-right-half-half')

                    # Volume dan price berpasangan
                    for i in range(len(bid_prices)):
                        try:
                            price = bid_prices[i].inner_text().strip()
                            # Volume ada sebelum price
                            if i < len(bid_volumes):
                                volume = bid_volumes[i].inner_text().strip()
                                orderbook_data['bids'].append({
                                    'price': price,
                                    'volume': volume
                                })
                        except Exception as e:
                            print(f"[{stock_code}] Error parsing bid {i}: {e}")

                print(f"[{stock_code}] Bids: {len(orderbook_data['bids'])} orders")
            except Exception as e:
                print(f"[{stock_code}] Error scraping bids: {e}")

            # Scrape Ask Orders (sisi kanan)
            try:
                ask_container = page.query_selector(
                    '.bidoff .col-50:last-child')
                if ask_container:
                    ask_prices = ask_container.query_selector_all('.ob-price')
                    ask_volumes = ask_container.query_selector_all(
                        '.ob-value.padding-right-half-half')

                    # Volume dan price berpasangan
                    for i in range(len(ask_prices)):
                        try:
                            price = ask_prices[i].inner_text().strip()
                            # Volume ada setelah price
                            if i < len(ask_volumes):
                                volume = ask_volumes[i].inner_text().strip()
                                orderbook_data['asks'].append({
                                    'price': price,
                                    'volume': volume
                                })
                        except Exception as e:
                            print(f"[{stock_code}] Error parsing ask {i}: {e}")

                print(f"[{stock_code}] Asks: {len(orderbook_data['asks'])} orders")
            except Exception as e:
                print(f"[{stock_code}] Error scraping asks: {e}")

            # Scrape Total Bid/Ask Lot (bagian bawah)
            try:
                totals = page.query_selector_all(
                    '.ob-mi-value.padding-right-half-half')
                if len(totals) >= 2:
                    orderbook_data['total_bid_lot'] = totals[0].inner_text(
                    ).strip()
                    orderbook_data['total_ask_lot'] = totals[1].inner_text(
                    ).strip()
                    print(
                        f"[{stock_code}] Total lots - Bid: {orderbook_data['total_bid_lot']}, Ask: {orderbook_data['total_ask_lot']}")
            except Exception as e:
                print(f"[{stock_code}] Error scraping totals: {e}")

            browser.close()

            print(f"[{stock_code}] ✓ Selesai")
            return orderbook_data

    except Exception as e:
        print(f"[{stock_code}] ✗ Error: {e}")
        return {
            'stock_code': stock_code,
            'timestamp': datetime.now().isoformat(),
            'error': str(e),
            'market_info': {},
            'bids': [],
            'asks': []
        }


def main():
    """
    Main function untuk menjalankan scraping dengan multiprocessing
    """
    print(f"{'='*60}")
    print(f"Orderbook Scraper - Indo Premier")
    print(f"{'='*60}")
    print(f"Target: {len(STOCK_LIST)} saham")
    print(f"Processes: {min(cpu_count(), len(STOCK_LIST))}")
    print(f"{'='*60}\n")

    start_time = time.time()

    # Gunakan multiprocessing Pool
    with Pool(processes=min(cpu_count(), len(STOCK_LIST))) as pool:
        results = pool.map(scrape_orderbook, STOCK_LIST)

    end_time = time.time()

    # Simpan hasil ke file JSON
    output_file = f"orderbook_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    rows = flatten_rows(results)
    if rows:
        try:
            push_to_database(rows)
        except Exception as e:
            print(f"❌ DB insert failed: {e}")

    # Summary
    print(f"\n{'='*60}")
    print(f"SUMMARY")
    print(f"{'='*60}")
    print(f"Durasi: {end_time - start_time:.2f} detik")
    print(f"Output: {output_file}")

    success_count = len([r for r in results if not r.get('error')])
    print(f"Berhasil: {success_count}/{len(STOCK_LIST)}")
    print(f"{'='*60}\n")

    # Detail per saham
    print("DETAIL:")
    for result in results:
        if result.get('error'):
            print(
                f"  ✗ {result['stock_code']:6s} - ERROR: {result['error'][:50]}")
        else:
            bids = len(result['bids'])
            asks = len(result['asks'])
            market_info = len(result['market_info'])
            print(
                f"  ✓ {result['stock_code']:6s} - Bids: {bids:2d}, Asks: {asks:2d}, Info: {market_info:2d}")

    print(f"\n{'='*60}")


if __name__ == "__main__":
    main()
