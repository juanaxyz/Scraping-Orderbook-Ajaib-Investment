# IPOT Orderbook Scraper

A high-performance web scraper for collecting orderbook data from Indo Premier Sekuritas (IPOT) trading platform. This tool scrapes real-time bid/ask data and market information for multiple stocks concurrently and stores the results in a MySQL database.

## Features

- 🚀 **Parallel Scraping**: Multi-browser architecture with configurable concurrency
- 📊 **Comprehensive Data**: Captures orderbook depth, market data, and trading statistics
- 🔄 **Automatic Retry**: Built-in retry mechanism with exponential backoff
- 💾 **MySQL Integration**: Direct database storage for efficient data management
- 📈 **Excel-based Stock Lists**: Easy configuration via Excel files
- ⚡ **Resource Optimization**: Blocks unnecessary resources (images, fonts, media) for faster scraping

## Data Collected

### Orderbook Data

- Bid prices and volumes (up to 5 levels)
- Ask prices and volumes (up to 5 levels)
- Total bid/ask lots

### Market Data

- Last traded price
- Daily high/low prices
- Bid quantity
- Highest bid price
- Timestamp for each record

## Prerequisites

- Python 3.8 or higher
- MySQL 5.7+ or MariaDB 10.3+
- Firefox browser (used by Playwright)

## Installation

1. **Clone the repository**

```bash
git clone <repository-url>
cd Scraping-Orderbook-Ajaib-Investment
```

2. **Install Python dependencies**

```bash
pip install -r requirements.txt
```

3. **Install Playwright browsers**

```bash
playwright install firefox
```

4. **Set up MySQL database**

Create the required tables:

```sql
-- Orderbook table
CREATE TABLE orderbook_ipot (
    id INT AUTO_INCREMENT PRIMARY KEY,
    kode VARCHAR(10) NOT NULL,
    side ENUM('B', 'A') NOT NULL,
    price INT,
    lot INT,
    num INT,
    timestamp DATETIME NOT NULL,
    INDEX idx_kode_timestamp (kode, timestamp),
    INDEX idx_timestamp (timestamp)
);

-- Market overview table
CREATE TABLE ipot_overview (
    id INT AUTO_INCREMENT PRIMARY KEY,
    kode VARCHAR(10) NOT NULL,
    last_price DECIMAL(15,2),
    high DECIMAL(15,2),
    low DECIMAL(15,2),
    bid_qty INT,
    h_bid DECIMAL(15,2),
    timestamp DATETIME NOT NULL,
    INDEX idx_kode_timestamp (kode, timestamp),
    INDEX idx_timestamp (timestamp)
);
```

5. **Configure environment variables**

Create a `.env` file in the project root:

```env
DB_HOST=localhost
DB_USER=your_username
DB_PASSWORD=your_password
DB_NAME=your_database
```

6. **Prepare stock list**

Create an Excel file with stock codes (default: `Daftar 10 Saham.xlsx`):

| Kode |
| ---- |
| BBCA |
| BBRI |
| TLKM |
| ASII |

## Configuration

Edit `ipot_scrapping.py` to customize scraping parameters:

```python
# Stock list file
STOCK_FILE = "Daftar 10 Saham.xlsx"  # Change to your Excel file

# Parallel scraping configuration
NUM_BROWSERS = 2                      # Number of browser instances
MAX_CONCURRENT_PER_BROWSER = 5        # Concurrent pages per browser
MAX_RETRIES = 3                       # Retry attempts for failed scrapes
PAGE_TIMEOUT = 30000                  # Page load timeout (ms)
HEADLESS = True                       # Run browsers in headless mode
```

**Performance Tips:**

- Total concurrency = `NUM_BROWSERS × MAX_CONCURRENT_PER_BROWSER`
- For 100 stocks: Try `NUM_BROWSERS=4` and `MAX_CONCURRENT_PER_BROWSER=5` (20 concurrent)
- Increase `PAGE_TIMEOUT` if experiencing timeouts on slower connections

## Usage

Run the scraper:

```bash
python ipot_scrapping.py
```

**Sample Output:**

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
```

## Database Schema

### orderbook_ipot

| Column    | Type          | Description                |
| --------- | ------------- | -------------------------- |
| id        | INT           | Auto-increment primary key |
| kode      | VARCHAR(10)   | Stock code (e.g., BBCA)    |
| side      | ENUM('B','A') | B=Bid, A=Ask               |
| price     | INT           | Price in IDR (integer)     |
| lot       | INT           | Volume in lots             |
| num       | INT           | Order book level (1-5)     |
| timestamp | DATETIME      | Scraping timestamp         |

### ipot_overview

| Column     | Type          | Description                |
| ---------- | ------------- | -------------------------- |
| id         | INT           | Auto-increment primary key |
| kode       | VARCHAR(10)   | Stock code                 |
| last_price | DECIMAL(15,2) | Last traded price          |
| high       | DECIMAL(15,2) | Daily high price           |
| low        | DECIMAL(15,2) | Daily low price            |
| bid_qty    | INT           | Total bid quantity         |
| h_bid      | DECIMAL(15,2) | Highest bid price          |
| timestamp  | DATETIME      | Scraping timestamp         |

## Project Structure

```
Scraping-Orderbook-Ajaib-Investment/
├── ipot_scrapping.py           # Main scraper script
├── Daftar 10 Saham.xlsx        # Stock list (10 stocks)
├── Daftar 955 Saham.xlsx       # Stock list (955 stocks)
├── Indo Premier Sekuritas...htm # Reference HTML file
├── .env                        # Environment variables (create this)
├── requirements.txt            # Python dependencies (create this)
└── README.md                   # This file
```

## Technical Details

### Architecture

- **Multi-browser**: Distributes stock list across multiple Firefox instances
- **Concurrency control**: Semaphores limit concurrent pages per browser
- **Resource blocking**: Blocks images, fonts, media, and stylesheets for speed
- **Auto-retry**: Retries failed scrapes with exponential backoff

### Error Handling

- Network timeouts with configurable retry
- Graceful browser cleanup on failures
- Detailed error logging with stock codes
- Database transaction rollback on errors

## Troubleshooting

### Common Issues

**1. Timeout errors**

```
Solution: Increase PAGE_TIMEOUT or reduce MAX_CONCURRENT_PER_BROWSER
```

**2. Database connection errors**

```
Solution: Verify .env file credentials and MySQL service is running
```

**3. "Column 'Kode' not found" error**

```
Solution: Ensure Excel file has a column named 'Kode' with stock codes
```

**4. Browser launch failures**

```bash
# Reinstall Playwright browsers
playwright install firefox --force
```

**5. High failure rate**

```
Solution:
- Check internet connection
- Reduce NUM_BROWSERS and MAX_CONCURRENT_PER_BROWSER
- Increase MAX_RETRIES
```

## Performance Benchmarks

| Stocks | Browsers | Concurrency | Time   | Success Rate |
| ------ | -------- | ----------- | ------ | ------------ |
| 10     | 2        | 5           | ~12s   | 100%         |
| 100    | 4        | 5           | ~2min  | 95-100%      |
| 955    | 8        | 10          | ~15min | 90-95%       |

_Benchmarks may vary based on network speed and system resources_

## Dependencies

```txt
playwright>=1.40.0
mysql-connector-python>=8.2.0
python-dotenv>=1.0.0
pandas>=2.1.0
openpyxl>=3.1.0
```

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License.

## Disclaimer

This tool is for educational and research purposes only. Ensure compliance with Indo Premier Sekuritas' Terms of Service and applicable laws regarding web scraping. The authors are not responsible for any misuse of this software.

## Support

For issues or questions, please open an issue on the GitHub repository.

---

**Note**: Market data is scraped from the public IPOT web interface. Always respect rate limits and trading hours.
