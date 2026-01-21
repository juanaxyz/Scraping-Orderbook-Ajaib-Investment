"""Stock Orderbook Filter GUI

This script provides a graphical user interface for filtering and analyzing stock orderbook
data from the MySQL database. Users can query data from both Ajaib and IPOT sources with
various filtering options and export results to CSV.

Key Features:
- Interactive Tkinter GUI for easy data filtering
- Support for multiple data sources (Ajaib/IPOT)
- Advanced filtering: stock code, side (bid/ask), price range, lot range
- Special Bid/Ask ratio filter (e.g., Bid ≥ 4x Ask)
- Real-time result display in sortable table
- CSV export functionality with timestamped filenames
- Database connection via environment variables

Usage:
    python filter.py    # Launch the GUI application
"""

import tkinter as tk
from tkinter import ttk, messagebox
import mysql.connector
import pandas as pd
from dotenv import load_dotenv
import os
from datetime import datetime

load_dotenv()

class StockFilterGUI:
    """Main GUI application class for stock orderbook filtering.
    
    This class creates and manages a Tkinter-based graphical interface that allows
    users to query, filter, and export stock orderbook data from MySQL database.
    Supports both Ajaib and IPOT data sources with various filtering criteria.
    
    Attributes:
        root: Tkinter root window
        db_config: Database connection configuration dictionary
        current_data: Cached query results for export functionality
        Various tk.StringVar and tk.BooleanVar for widget state management
    
    Example:
        root = tk.Tk()
        app = StockFilterGUI(root)
        root.mainloop()
    """
    
    def __init__(self, root):
        """Initialize the GUI application.
        
        Sets up the main window, loads database configuration from environment
        variables, and creates all GUI widgets.
        
        Args:
            root: Tkinter root window instance
        """
        self.root = root
        self.root.title("Stock Price Filter")
        self.root.geometry("1200x700")
        
        # Database connection parameters from environment variables
        self.db_config = {
            'host': os.getenv('DB_HOST'),
            'user': os.getenv('DB_USER'),
            'password': os.getenv('DB_PASSWORD'),
            'database': os.getenv('DB_NAME')
        }
        
        self.create_widgets()
        
    def create_widgets(self):
        """Create and layout all GUI widgets.
        
        Builds the complete user interface including:
        - Title label
        - Filter controls frame (source, stock code, side, price/lot range, limit)
        - Special bid/ask ratio filter
        - Action buttons (Apply, Clear, Export)
        - Results table with scrollbars
        - Status bar
        
        Uses grid layout manager for organized widget placement.
        """
        # =============================================================================
        # MAIN FRAME SETUP
        # =============================================================================
        
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Configure grid weights for responsive resizing
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(3, weight=1)
        
        # =============================================================================
        # TITLE AND FILTER CONTROLS
        # =============================================================================
        
        # Application title
        title_label = ttk.Label(main_frame, text="Stock Orderbook Filter", 
                                font=('Arial', 16, 'bold'))
        title_label.grid(row=0, column=0, columnspan=3, pady=10)
        
        # Filter controls container
        filter_frame = ttk.LabelFrame(main_frame, text="Filters", padding="10")
        filter_frame.grid(row=1, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=10)
        
        # --- Bid/Ask Ratio Filter ---
        # Special filter to find stocks where Bid volume ≥ N × Ask volume
        self.bid_ask_filter_var = tk.BooleanVar()
        ttk.Label(filter_frame, text="Price Filter:").grid(row=0, column=2, sticky=tk.W, padx=5, pady=5)
        bid_ask_frame = ttk.Frame(filter_frame)
        bid_ask_frame.grid(row=0, column=3, sticky=tk.W, padx=5, pady=5)
        
        ttk.Checkbutton(
            bid_ask_frame,
            text="Bid Price ≥",
            variable=self.bid_ask_filter_var
        ).pack(side=tk.LEFT, padx=2)
        
        # Multiplier dropdown (2x, 3x, 4x, etc.)
        self.bid_multiplier_var = tk.StringVar(value="4")
        multiplier_combo = ttk.Combobox(bid_ask_frame, textvariable=self.bid_multiplier_var, 
                                       values=["2", "3", "4", "5", "6", "7", "8", "9", "10"], 
                                       width=5, state="readonly")
        multiplier_combo.pack(side=tk.LEFT, padx=2)
        ttk.Label(bid_ask_frame, text="x Ask Price").pack(side=tk.LEFT, padx=2)
        
        # --- Data Source Selection (Ajaib or IPOT) ---
        ttk.Label(filter_frame, text="Data Source:").grid(row=1, column=0, sticky=tk.W, padx=5)
        self.source_var = tk.StringVar(value="ajaib")
        source_frame = ttk.Frame(filter_frame)
        source_frame.grid(row=1, column=1, sticky=tk.W, padx=5)
        ttk.Radiobutton(source_frame, text="Ajaib", variable=self.source_var, 
                       value="ajaib").pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(source_frame, text="IPOT", variable=self.source_var, 
                       value="ipot").pack(side=tk.LEFT, padx=5)
        
        # --- Stock Code Filter ---
        ttk.Label(filter_frame, text="Stock Code:").grid(row=2, column=0, sticky=tk.W, padx=5, pady=5)
        self.code_var = tk.StringVar()
        code_entry = ttk.Entry(filter_frame, textvariable=self.code_var, width=15)
        code_entry.grid(row=2, column=1, sticky=tk.W, padx=5, pady=5)
        ttk.Label(filter_frame, text="(Leave empty for all)").grid(row=2, column=2, sticky=tk.W, padx=5)
        
        # --- Side Filter (Bid/Ask/All) ---
        ttk.Label(filter_frame, text="Side:").grid(row=3, column=0, sticky=tk.W, padx=5, pady=5)
        self.side_var = tk.StringVar(value="ALL")
        side_combo = ttk.Combobox(filter_frame, textvariable=self.side_var, 
                                  values=["ALL", "B (Bid)", "S (Sell/Ask)"], width=12, state="readonly")
        side_combo.grid(row=3, column=1, sticky=tk.W, padx=5, pady=5)
        
        # --- Price Range Filter ---
        ttk.Label(filter_frame, text="Price Range:").grid(row=4, column=0, sticky=tk.W, padx=5, pady=5)
        price_frame = ttk.Frame(filter_frame)
        price_frame.grid(row=4, column=1, columnspan=2, sticky=tk.W, padx=5, pady=5)
        
        self.price_min_var = tk.StringVar()
        self.price_max_var = tk.StringVar()
        ttk.Label(price_frame, text="Min:").pack(side=tk.LEFT, padx=2)
        ttk.Entry(price_frame, textvariable=self.price_min_var, width=12).pack(side=tk.LEFT, padx=2)
        ttk.Label(price_frame, text="Max:").pack(side=tk.LEFT, padx=2)
        ttk.Entry(price_frame, textvariable=self.price_max_var, width=12).pack(side=tk.LEFT, padx=2)
        
        # --- Lot Range Filter ---
        ttk.Label(filter_frame, text="Lot Range:").grid(row=5, column=0, sticky=tk.W, padx=5, pady=5)
        lot_frame = ttk.Frame(filter_frame)
        lot_frame.grid(row=5, column=1, columnspan=2, sticky=tk.W, padx=5, pady=5)
        
        self.lot_min_var = tk.StringVar()
        self.lot_max_var = tk.StringVar()
        ttk.Label(lot_frame, text="Min:").pack(side=tk.LEFT, padx=2)
        ttk.Entry(lot_frame, textvariable=self.lot_min_var, width=12).pack(side=tk.LEFT, padx=2)
        ttk.Label(lot_frame, text="Max:").pack(side=tk.LEFT, padx=2)
        ttk.Entry(lot_frame, textvariable=self.lot_max_var, width=12).pack(side=tk.LEFT, padx=2)
        
        # --- Result Limit ---
        ttk.Label(filter_frame, text="Limit Results:").grid(row=6, column=0, sticky=tk.W, padx=5, pady=5)
        self.limit_var = tk.StringVar(value="100")
        limit_combo = ttk.Combobox(filter_frame, textvariable=self.limit_var, 
                                   values=["100", "500", "1000", "5000", "ALL"], width=12, state="readonly")
        limit_combo.grid(row=6, column=1, sticky=tk.W, padx=5, pady=5)
        
        # =============================================================================
        # ACTION BUTTONS
        # =============================================================================
        
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=2, column=0, columnspan=3, pady=10)
        
        ttk.Button(button_frame, text="Apply Filter", command=self.apply_filter).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Clear Filter", command=self.clear_filter).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Export to CSV", command=self.export_csv).pack(side=tk.LEFT, padx=5)
        
        # =============================================================================
        # RESULTS TABLE
        # =============================================================================
        results_frame = ttk.LabelFrame(main_frame, text="Results", padding="10")
        results_frame.grid(row=3, column=0, columnspan=3, sticky=(tk.W, tk.E, tk.N, tk.S), pady=10)
        results_frame.columnconfigure(0, weight=1)
        results_frame.rowconfigure(0, weight=1)
        
        # Scrollbars for table navigation
        tree_scroll_y = ttk.Scrollbar(results_frame, orient=tk.VERTICAL)
        tree_scroll_x = ttk.Scrollbar(results_frame, orient=tk.HORIZONTAL)
        
        # Treeview widget for displaying tabular data
        self.tree = ttk.Treeview(results_frame, 
                                 columns=("Code", "Timestamp", "Bid_Price", "Ask_Price", "Ratio", "Details"),
                                 show="headings",
                                 yscrollcommand=tree_scroll_y.set,
                                 xscrollcommand=tree_scroll_x.set)
        
        tree_scroll_y.config(command=self.tree.yview)
        tree_scroll_x.config(command=self.tree.xview)
        
        # Configure column headers and widths
        self.tree.heading("Code", text="Stock Code")
        self.tree.heading("Timestamp", text="Timestamp")
        self.tree.heading("Bid_Price", text="Bid Price")
        self.tree.heading("Ask_Price", text="Ask Price")
        self.tree.heading("Ratio", text="Ratio")
        self.tree.heading("Details", text="Details")
        
        self.tree.column("Code", width=80, anchor=tk.CENTER)
        self.tree.column("Timestamp", width=180, anchor=tk.CENTER)
        self.tree.column("Bid_Price", width=100, anchor=tk.E)
        self.tree.column("Ask_Price", width=100, anchor=tk.E)
        self.tree.column("Ratio", width=80, anchor=tk.CENTER)
        self.tree.column("Details", width=200, anchor=tk.W)
        
        self.tree.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        tree_scroll_y.grid(row=0, column=1, sticky=(tk.N, tk.S))
        tree_scroll_x.grid(row=1, column=0, sticky=(tk.W, tk.E))
        
        # =============================================================================
        # STATUS BAR
        # =============================================================================
        
        self.status_var = tk.StringVar(value="Ready")
        status_bar = ttk.Label(main_frame, textvariable=self.status_var, 
                              relief=tk.SUNKEN, anchor=tk.W)
        status_bar.grid(row=4, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=5)
        
        # Cache for storing current query results (used for CSV export)
        self.current_data = None
        
    def get_connection(self):
        """Create and return a MySQL database connection.
        
        Uses configuration from environment variables (.env file).
        Displays error dialog if connection fails.
        
        Returns:
            mysql.connector.connection.MySQLConnection or None: 
                Active database connection, or None if connection failed
        """
        try:
            conn = mysql.connector.connect(**self.db_config)
            return conn
        except Exception as e:
            messagebox.showerror("Database Error", f"Failed to connect to database:\n{str(e)}")
            return None
    
    def build_query(self):
        """Build SQL query based on current filter settings.
        
        Constructs different queries depending on whether the Bid/Ask ratio filter
        is enabled. For ratio filter, aggregates bid and ask volumes by stock and price.
        For normal filter, retrieves individual orderbook entries.
        
        Returns:
            tuple: (query_string, parameters_list) where:
                   - query_string is the SQL query with %s placeholders
                   - parameters_list contains values to substitute
                   
        Note:
            When Bid/Ask filter is active, returns aggregated data grouped by
            stock code and price level, filtering for Bid ≥ N × Ask.
        """
        source = self.source_var.get()
        table = f"orderbook_{source}"
        multiplier = self.bid_multiplier_var.get()

        # === Special Case: Bid/Ask Ratio Filter ===
        # Groups by stock code and price, calculates bid and ask totals
        if self.bid_ask_filter_var.get():
            query = f"""
            SELECT 
                b.kode,
                b.timestamp,
                b.price AS bid_price,
                s.price AS ask_price,
                b.lot AS bid_lot,
                s.lot AS ask_lot
            FROM {table} b
            INNER JOIN {table} s 
                ON b.kode = s.kode 
                AND b.timestamp = s.timestamp
            WHERE b.side = 'B' 
                AND s.side = 'S'
                AND b.timestamp IS NOT NULL
                AND b.price >= {multiplier} * s.price
            ORDER BY b.timestamp DESC
            """
            
            limit = self.limit_var.get()
            if limit != "ALL":
                query += f" LIMIT {limit}"
            
            params = []
            return query, params

        # === Normal Query: Individual Orderbook Entries ===
        query = f"""
            SELECT kode, side, price, lot, num, timestamp
            FROM {table}
            WHERE timestamp IS NOT NULL AND side IN ('B', 'S')
        """
        params = []

        # Add stock code filter if specified
        code = self.code_var.get().strip().upper()
        if code:
            query += " AND kode = %s"
            params.append(code)

        # Add side filter (Bid or Ask)
        side = self.side_var.get()
        if side != "ALL":
            query += " AND side = %s"
            params.append(side[0])  # Extract 'B' or 'S' from "B (Bid)" or "S (Sell/Ask)"

        query += " ORDER BY timestamp DESC"

        # Apply result limit
        limit = self.limit_var.get()
        if limit != "ALL":
            query += f" LIMIT {limit}"

        return query, params
 
    def apply_filter(self):
        """Execute the filter query and display results in the table.
        
        Builds the SQL query based on current filter settings, executes it,
        and populates the treeview table with results. Handles two different
        result formats: aggregated (for Bid/Ask ratio filter) and detailed
        (for normal filtering).
        
        Updates:
            - Clears existing table data
            - Caches results in self.current_data for export
            - Updates status bar with result count
            - Shows info dialog if no results found
        """
        # Clear existing data from table
        for item in self.tree.get_children():
            self.tree.delete(item)
        
        # Adjust columns based on filter type
        if self.bid_ask_filter_var.get():
            self.tree["columns"] = ("Code", "Timestamp", "Bid_Price", "Ask_Price", "Ratio", "Details")
            self.tree.heading("Code", text="Stock Code")
            self.tree.heading("Timestamp", text="Timestamp")
            self.tree.heading("Bid_Price", text="Bid Price")
            self.tree.heading("Ask_Price", text="Ask Price")
            self.tree.heading("Ratio", text="Ratio")
            self.tree.heading("Details", text="Details")
            
            self.tree.column("Code", width=80, anchor=tk.CENTER)
            self.tree.column("Timestamp", width=180, anchor=tk.CENTER)
            self.tree.column("Bid_Price", width=100, anchor=tk.E)
            self.tree.column("Ask_Price", width=100, anchor=tk.E)
            self.tree.column("Ratio", width=80, anchor=tk.CENTER)
            self.tree.column("Details", width=200, anchor=tk.W)
        else:
            self.tree["columns"] = ("Code", "Side", "Price", "Lot", "Num", "Timestamp")
            self.tree.heading("Code", text="Stock Code")
            self.tree.heading("Side", text="Side")
            self.tree.heading("Price", text="Price")
            self.tree.heading("Lot", text="Lot")
            self.tree.heading("Num", text="Number")
            self.tree.heading("Timestamp", text="Timestamp")
            
            self.tree.column("Code", width=80, anchor=tk.CENTER)
            self.tree.column("Side", width=60, anchor=tk.CENTER)
            self.tree.column("Price", width=100, anchor=tk.E)
            self.tree.column("Lot", width=100, anchor=tk.E)
            self.tree.column("Num", width=80, anchor=tk.CENTER)
            self.tree.column("Timestamp", width=180, anchor=tk.CENTER)
        
        self.status_var.set("Fetching data...")
        self.root.update()
        
        conn = self.get_connection()
        if not conn:
            return
        
        try:
            query, params = self.build_query()
            cursor = conn.cursor()
            cursor.execute(query, params)
            results = cursor.fetchall()

            # Cache results for CSV export
            self.current_data = results

            # Process and display results based on filter type
            for row in results:
                # === Bid/Ask Ratio Filter Results (Aggregated) ===
                if self.bid_ask_filter_var.get():
                    kode, timestamp, bid_price, ask_price, bid_lot, ask_lot = row
                    
                    # Handle None values gracefully
                    price_str = f"{price:,.2f}" if price is not None else "0.00"
                    bid_lot_str = f"{bid_lot:,}" if bid_lot is not None else "0"
                    ask_lot_str = f"{ask_lot:,}" if ask_lot is not None else "0"
                    timestamp_str = timestamp.strftime("%Y-%m-%d %H:%M:%S") if timestamp is not None else "N/A"
                    
                    details = f"BID:{bid_lot} lots | ASK:{ask_lot} lots"
                    
                    # Insert row with special formatting for ratio filter
                    self.tree.insert("", tk.END, values=(
                        kode or "N/A",
                        f"B≥{multiplier}S",  # Show ratio in Side column
                        price_str,
                        bid_lot_str,
                        f"ASK:{ask_lot_str}",  # Show ask lot in Num column
                        timestamp_str
                    ))
                # === Normal Filter Results (Detailed) ===
                else:
                    kode, side, price, lot, num, timestamp = row
                    
                    # Handle None values gracefully
                    side_text = "BID" if side == "B" else "ASK" if side == "S" else "N/A"
                    price_str = f"{price:,.2f}" if price is not None else "0.00"
                    lot_str = str(lot) if lot is not None else "0"
                    num_str = str(num) if num is not None else "0"
                    timestamp_str = timestamp.strftime("%Y-%m-%d %H:%M:%S") if timestamp is not None else "N/A"
                    
                    # Insert row with standard formatting
                    self.tree.insert("", tk.END, values=(
                        kode or "N/A", 
                        side_text, 
                        price_str, 
                        lot_str, 
                        num_str,
                        timestamp_str
                    ))

            # Update status bar with result count
            self.status_var.set(f"Found {len(results)} records")
            
            # Notify user if no results found
            if len(results) == 0:
                messagebox.showinfo("No Results", "No records found matching the filter criteria.")
            
        except Exception as e:
            messagebox.showerror("Query Error", f"Failed to execute query:\n{str(e)}")
            self.status_var.set("Error occurred")
        finally:
            # Always close database resources
            if cursor:
                cursor.close()
            if conn:
                conn.close()
    
    def clear_filter(self):
        """Reset all filter controls to default values.
        
        Clears all filter inputs, resets dropdowns to defaults, and empties
        the results table. Also clears cached data.
        """
        # Reset all filter variables to defaults
        self.code_var.set("")
        self.side_var.set("ALL")
        self.price_min_var.set("")
        self.price_max_var.set("")
        self.lot_min_var.set("")
        self.lot_max_var.set("")
        self.limit_var.set("100")
        self.bid_ask_filter_var.set(False)
        self.bid_multiplier_var.set("4")
        
        # Clear results table
        for item in self.tree.get_children():
            self.tree.delete(item)
        
        # Clear cached data
        self.current_data = None
        self.status_var.set("Filters cleared")
    
    def export_csv(self):
        """Export current query results to CSV file.
        
        Creates a pandas DataFrame from cached results and saves to a
        timestamped CSV file. Column names differ based on whether
        Bid/Ask ratio filter was active.
        
        CSV filename format: stock_filter_{source}_{timestamp}.csv
        Example: stock_filter_ajaib_20260121_143052.csv
        
        Shows success or error dialog after export attempt.
        """
        # Check if there's data to export
        if not self.current_data or len(self.current_data) == 0:
            messagebox.showwarning("No Data", "No data to export. Please apply a filter first.")
            return
        
        # Create DataFrame with appropriate columns based on filter type
        if self.bid_ask_filter_var.get():
            # Aggregated data columns
            df = pd.DataFrame(self.current_data, 
                             columns=["kode", "timestamp", "bid_price", "ask_price", "bid_lot", "ask_lot"])
        else:
            # Detailed orderbook columns
            df = pd.DataFrame(self.current_data, 
                             columns=["kode", "side", "price", "lot", "num", "timestamp"])
        
        # Generate filename with timestamp and data source
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        source = self.source_var.get()
        filename = f"stock_filter_{source}_{timestamp}.csv"
        
        try:
            df.to_csv(filename, index=False)
            messagebox.showinfo("Export Success", f"Data exported to:\n{filename}")
            self.status_var.set(f"Exported to {filename}")
        except Exception as e:
            messagebox.showerror("Export Error", f"Failed to export data:\n{str(e)}")

# =============================================================================
# SCRIPT ENTRY POINT
# =============================================================================

def main():
    """Initialize and run the GUI application.
    
    Creates the Tkinter root window, instantiates the StockFilterGUI class,
    and starts the main event loop.
    """
    root = tk.Tk()
    app = StockFilterGUI(root)
    root.mainloop()

if __name__ == "__main__":
    main()