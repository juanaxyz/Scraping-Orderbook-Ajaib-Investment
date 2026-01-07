import tkinter as tk
from tkinter import ttk, messagebox
import mysql.connector
import pandas as pd
from dotenv import load_dotenv
import os
from datetime import datetime

load_dotenv()

class StockFilterGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Stock Price Filter")
        self.root.geometry("1200x700")
        
        # Database connection parameters
        self.db_config = {
            'host': os.getenv('DB_HOST'),
            'user': os.getenv('DB_USER'),
            'password': os.getenv('DB_PASSWORD'),
            'database': os.getenv('DB_NAME')
        }
        
        self.create_widgets()
        
    def create_widgets(self):
        # Main frame
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Configure grid weights
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(3, weight=1)
        
        # Title
        title_label = ttk.Label(main_frame, text="Stock Orderbook Filter", 
                                font=('Arial', 16, 'bold'))
        title_label.grid(row=0, column=0, columnspan=3, pady=10)
        
        # Filter Frame
        filter_frame = ttk.LabelFrame(main_frame, text="Filters", padding="10")
        filter_frame.grid(row=1, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=10)
        
        # Source selection
        ttk.Label(filter_frame, text="Data Source:").grid(row=0, column=0, sticky=tk.W, padx=5)
        self.source_var = tk.StringVar(value="ajaib")
        source_frame = ttk.Frame(filter_frame)
        source_frame.grid(row=0, column=1, sticky=tk.W, padx=5)
        ttk.Radiobutton(source_frame, text="Ajaib", variable=self.source_var, 
                       value="ajaib").pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(source_frame, text="IPOT", variable=self.source_var, 
                       value="ipot").pack(side=tk.LEFT, padx=5)
        
        # Stock code filter
        ttk.Label(filter_frame, text="Stock Code:").grid(row=1, column=0, sticky=tk.W, padx=5, pady=5)
        self.code_var = tk.StringVar()
        code_entry = ttk.Entry(filter_frame, textvariable=self.code_var, width=15)
        code_entry.grid(row=1, column=1, sticky=tk.W, padx=5, pady=5)
        ttk.Label(filter_frame, text="(Leave empty for all)").grid(row=1, column=2, sticky=tk.W, padx=5)
        
        # Side filter
        ttk.Label(filter_frame, text="Side:").grid(row=2, column=0, sticky=tk.W, padx=5, pady=5)
        self.side_var = tk.StringVar(value="ALL")
        side_combo = ttk.Combobox(filter_frame, textvariable=self.side_var, 
                                  values=["ALL", "B (Bid)", "A (Ask)"], width=12, state="readonly")
        side_combo.grid(row=2, column=1, sticky=tk.W, padx=5, pady=5)
        
        # Price range filter
        ttk.Label(filter_frame, text="Price Range:").grid(row=3, column=0, sticky=tk.W, padx=5, pady=5)
        price_frame = ttk.Frame(filter_frame)
        price_frame.grid(row=3, column=1, columnspan=2, sticky=tk.W, padx=5, pady=5)
        
        self.price_min_var = tk.StringVar()
        self.price_max_var = tk.StringVar()
        ttk.Label(price_frame, text="Min:").pack(side=tk.LEFT, padx=2)
        ttk.Entry(price_frame, textvariable=self.price_min_var, width=12).pack(side=tk.LEFT, padx=2)
        ttk.Label(price_frame, text="Max:").pack(side=tk.LEFT, padx=2)
        ttk.Entry(price_frame, textvariable=self.price_max_var, width=12).pack(side=tk.LEFT, padx=2)
        
        # Lot range filter
        ttk.Label(filter_frame, text="Lot Range:").grid(row=4, column=0, sticky=tk.W, padx=5, pady=5)
        lot_frame = ttk.Frame(filter_frame)
        lot_frame.grid(row=4, column=1, columnspan=2, sticky=tk.W, padx=5, pady=5)
        
        self.lot_min_var = tk.StringVar()
        self.lot_max_var = tk.StringVar()
        ttk.Label(lot_frame, text="Min:").pack(side=tk.LEFT, padx=2)
        ttk.Entry(lot_frame, textvariable=self.lot_min_var, width=12).pack(side=tk.LEFT, padx=2)
        ttk.Label(lot_frame, text="Max:").pack(side=tk.LEFT, padx=2)
        ttk.Entry(lot_frame, textvariable=self.lot_max_var, width=12).pack(side=tk.LEFT, padx=2)
        
        # Limit results
        ttk.Label(filter_frame, text="Limit Results:").grid(row=5, column=0, sticky=tk.W, padx=5, pady=5)
        self.limit_var = tk.StringVar(value="100")
        limit_combo = ttk.Combobox(filter_frame, textvariable=self.limit_var, 
                                   values=["100", "500", "1000", "5000", "ALL"], width=12, state="readonly")
        limit_combo.grid(row=5, column=1, sticky=tk.W, padx=5, pady=5)
        
        # Buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=2, column=0, columnspan=3, pady=10)
        
        ttk.Button(button_frame, text="Apply Filter", command=self.apply_filter).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Clear Filter", command=self.clear_filter).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Export to CSV", command=self.export_csv).pack(side=tk.LEFT, padx=5)
        
        # Results frame
        results_frame = ttk.LabelFrame(main_frame, text="Results", padding="10")
        results_frame.grid(row=3, column=0, columnspan=3, sticky=(tk.W, tk.E, tk.N, tk.S), pady=10)
        results_frame.columnconfigure(0, weight=1)
        results_frame.rowconfigure(0, weight=1)
        
        # Treeview with scrollbars
        tree_scroll_y = ttk.Scrollbar(results_frame, orient=tk.VERTICAL)
        tree_scroll_x = ttk.Scrollbar(results_frame, orient=tk.HORIZONTAL)
        
        self.tree = ttk.Treeview(results_frame, 
                                 columns=("Code", "Side", "Price", "Lot", "Num", "Timestamp"),
                                 show="headings",
                                 yscrollcommand=tree_scroll_y.set,
                                 xscrollcommand=tree_scroll_x.set)
        
        tree_scroll_y.config(command=self.tree.yview)
        tree_scroll_x.config(command=self.tree.xview)
        
        # Define columns
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
        
        self.tree.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        tree_scroll_y.grid(row=0, column=1, sticky=(tk.N, tk.S))
        tree_scroll_x.grid(row=1, column=0, sticky=(tk.W, tk.E))
        
        # Status bar
        self.status_var = tk.StringVar(value="Ready")
        status_bar = ttk.Label(main_frame, textvariable=self.status_var, 
                              relief=tk.SUNKEN, anchor=tk.W)
        status_bar.grid(row=4, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=5)
        
        # Store current data for export
        self.current_data = None
        
    def get_connection(self):
        """Create database connection"""
        try:
            conn = mysql.connector.connect(**self.db_config)
            return conn
        except Exception as e:
            messagebox.showerror("Database Error", f"Failed to connect to database:\n{str(e)}")
            return None
    
    def build_query(self):
        """Build SQL query based on filters"""
        source = self.source_var.get()
        table = f"orderbook_{source}"
        
        query = f"SELECT kode, side, price, lot, num, timestamp FROM {table} WHERE 1=1"
        params = []
        
        # Stock code filter
        code = self.code_var.get().strip().upper()
        if code:
            query += " AND kode = %s"
            params.append(code)
        
        # Side filter
        side = self.side_var.get()
        if side != "ALL":
            side_char = side[0]  # Extract 'B' or 'A'
            query += " AND side = %s"
            params.append(side_char)
        
        # Price range filter
        try:
            price_min = self.price_min_var.get().strip()
            if price_min:
                query += " AND price >= %s"
                params.append(float(price_min))
        except ValueError:
            pass
        
        try:
            price_max = self.price_max_var.get().strip()
            if price_max:
                query += " AND price <= %s"
                params.append(float(price_max))
        except ValueError:
            pass
        
        # Lot range filter
        try:
            lot_min = self.lot_min_var.get().strip()
            if lot_min:
                query += " AND lot >= %s"
                params.append(int(lot_min))
        except ValueError:
            pass
        
        try:
            lot_max = self.lot_max_var.get().strip()
            if lot_max:
                query += " AND lot <= %s"
                params.append(int(lot_max))
        except ValueError:
            pass
        
        # Order by timestamp (most recent first)
        query += " ORDER BY timestamp DESC"
        
        # Limit
        limit = self.limit_var.get()
        if limit != "ALL":
            query += f" LIMIT {limit}"
        
        return query, params
    
    def apply_filter(self):
        """Apply filters and display results"""
        # Clear existing data
        for item in self.tree.get_children():
            self.tree.delete(item)
        
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
            
            # Store data for export
            self.current_data = results
            
            # Display results
            for row in results:
                # Format the data
                kode, side, price, lot, num, timestamp = row
                side_text = "BID" if side == "B" else "ASK"
                price_str = f"{float(price):,.2f}" if price else "N/A"
                lot_str = f"{lot:,}" if lot else "N/A"
                timestamp_str = timestamp.strftime("%Y-%m-%d %H:%M:%S") if timestamp else "N/A"
                
                self.tree.insert("", tk.END, values=(
                    kode, side_text, price_str, lot_str, num, timestamp_str
                ))
            
            self.status_var.set(f"Found {len(results)} records")
            
            if len(results) == 0:
                messagebox.showinfo("No Results", "No records found matching the filter criteria.")
            
        except Exception as e:
            messagebox.showerror("Query Error", f"Failed to execute query:\n{str(e)}")
            self.status_var.set("Error occurred")
        finally:
            cursor.close()
            conn.close()
    
    def clear_filter(self):
        """Clear all filters"""
        self.code_var.set("")
        self.side_var.set("ALL")
        self.price_min_var.set("")
        self.price_max_var.set("")
        self.lot_min_var.set("")
        self.lot_max_var.set("")
        self.limit_var.set("100")
        
        # Clear results
        for item in self.tree.get_children():
            self.tree.delete(item)
        
        self.current_data = None
        self.status_var.set("Filters cleared")
    
    def export_csv(self):
        """Export current results to CSV"""
        if not self.current_data or len(self.current_data) == 0:
            messagebox.showwarning("No Data", "No data to export. Please apply a filter first.")
            return
        
        # Create DataFrame
        df = pd.DataFrame(self.current_data, 
                         columns=["kode", "side", "price", "lot", "num", "timestamp"])
        
        # Generate filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        source = self.source_var.get()
        filename = f"stock_filter_{source}_{timestamp}.csv"
        
        try:
            df.to_csv(filename, index=False)
            messagebox.showinfo("Export Success", f"Data exported to:\n{filename}")
            self.status_var.set(f"Exported to {filename}")
        except Exception as e:
            messagebox.showerror("Export Error", f"Failed to export data:\n{str(e)}")

def main():
    root = tk.Tk()
    app = StockFilterGUI(root)
    root.mainloop()

if __name__ == "__main__":
    main()