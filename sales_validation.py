import csv
import datetime
from abc import ABC, abstractmethod
from ftplib import FTP
import os
import re
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import requests
import uuid

class ValidationStrategy(ABC):
    @abstractmethod
    def validate(self, filepath: str, filename: str) -> list:
        pass


class FilenameFormatRule(ValidationStrategy):
    def validate(self, filepath: str, filename: str) -> list:
        pattern = r"^SALES_DATA_\d{14}\.csv$"
        if not re.match(pattern, filename):
            return ["Incorrect filename format."]
        return []


class FileIntegrityRule(ValidationStrategy):
    def validate(self, filepath: str, filename: str) -> list:
        if os.path.getsize(filepath) == 0:
            return ["CSV file is empty (0-byte file)."]
        return []


class RowContentRule(ValidationStrategy):
    REQUIRED_HEADERS = [
        "transaction_id", "timestamp", "store_id",
        "product_id", "quantity", "unit_price",
        "total_amount", "payment_method"
    ]

    def validate(self, filepath: str, filename: str) -> list:
        errors = []
        transaction_ids = set()
        timestamps = []

        try:
            with open(filepath, "r", newline="", encoding="utf-8") as file:
                reader = csv.DictReader(file)

                if reader.fieldnames is None:
                    return ["Missing headers."]

                headers = [h.strip().lower() for h in reader.fieldnames]
                reader.fieldnames = headers

                for field in self.REQUIRED_HEADERS:
                    if field not in headers:
                        errors.append(f"Missing or incorrect header: {field}")

                if any(field not in headers for field in self.REQUIRED_HEADERS):
                    return errors

                for row_number, row in enumerate(reader, start=2):
                    for field in self.REQUIRED_HEADERS:
                        if row[field] is None or row[field].strip() == "":
                            errors.append(f"Row {row_number}: Missing {field}")

                    transaction_id = row["transaction_id"]
                    if transaction_id in transaction_ids:
                        errors.append(f"Row {row_number}: Duplicate transaction_id {transaction_id}")
                    else:
                        transaction_ids.add(transaction_id)

                    try:
                        datetime.datetime.strptime(row["timestamp"], "%Y-%m-%d %H:%M:%S")
                        timestamps.append(row["timestamp"])
                    except ValueError:
                        errors.append(f"Row {row_number}: Invalid timestamp format.")

                    try:
                        quantity = int(row["quantity"])
                        unit_price = float(row["unit_price"])
                        total_amount = float(row["total_amount"])

                        if quantity <= 0:
                            errors.append(f"Row {row_number}: Quantity must be positive.")
                        if unit_price <= 0:
                            errors.append(f"Row {row_number}: Unit price must be positive.")
                        if total_amount <= 0:
                            errors.append(f"Row {row_number}: Total amount must be positive.")
                        if abs(quantity * unit_price - total_amount) > 0.01:
                            errors.append(f"Row {row_number}: Total amount calculation incorrect.")
                    except ValueError:
                        errors.append(f"Row {row_number}: Invalid numeric value.")

                if timestamps:
                    first_date = timestamps[0][:10]
                    for index, time in enumerate(timestamps, start=2):
                        if time[:10] != first_date:
                            errors.append(f"Row {index}: Timestamp inconsistent.")

        except Exception as e:
            errors.append(f"CSV reading error: {str(e)}")

        return errors


class SalesDataValidator:

    def __init__(self, strategies: list = None):
        self.strategies = strategies or [
            FilenameFormatRule(),
            FileIntegrityRule(),
            RowContentRule()
        ]

    def add_strategy(self, strategy: ValidationStrategy):
        self.strategies.append(strategy)

    def validate_file(self, filepath: str, filename: str) -> list:
        all_errors = []
        for strategy in self.strategies:
            errors = strategy.validate(filepath, filename)
            all_errors.extend(errors)
            
            if isinstance(strategy, (FilenameFormatRule, FileIntegrityRule)) and errors:
                break

        return all_errors


class FTPClientManager:

    def __init__(self):
        self.ftp = None
        self.is_connected = False
        self.all_files = []

    def connect(self, host, username, password):
        if not host:
            raise ValueError("Host address is empty.")
        
        self.ftp = FTP(host, timeout=10)
        self.ftp.login(username, password)
        self.is_connected = True

        try:
            self.all_files = self.ftp.nlst() or []
        except Exception:
            self.all_files = []
            
        return self.all_files

    def disconnect(self):
        if self.ftp:
            try:
                self.ftp.quit()
            except Exception:
                pass
            finally:
                self.ftp = None
        self.is_connected = False
        self.all_files = []

    def download_file(self, filename, local_filepath):
        if not self.is_connected or not self.ftp:
            raise ConnectionError("FTP server is not connected.")
        
        with open(local_filepath, "wb") as file:
            self.ftp.retrbinary(f"RETR {filename}", file.write)


class LoggerManager:

    def __init__(self, text_widget):
        self.text_widget = text_widget

    def log_activity(self, message):
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        self.text_widget.insert(tk.END, f"[{timestamp}] {message}\n")
        self.text_widget.see(tk.END)

    def clear(self):
        self.text_widget.delete("1.0", tk.END)

    def generate_uuid(self):
        try:
            response = requests.get("https://www.uuidtools.com/api/generate/v1", timeout=3)
            if response.status_code == 200:
                return response.json()[0]
        except Exception:
            pass
        return str(uuid.uuid4())

    def write_and_log_errors(self, filename, errors, log_path):
        if errors:
            self.log_activity(f"File '{filename}' FAILED verification rules checks.")

            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            with open(log_path, "a", encoding="utf-8") as log_file:
                for error_item in errors:
                    error_type, details = (
                        error_item if isinstance(error_item, tuple) 
                        else ("Validation Error", error_item)
                    )
                    entry_uuid = self.generate_uuid()
                    entry_time = datetime.datetime.now().isoformat()
                    log_entry = (
                        f"UUID: {entry_uuid}\n"
                        f"Time: {entry_time}\n"
                        f"File: {filename}\n"
                        f"Type: {error_type}\n"
                        f"Details: {details}\n"
                        f"{'-'*73}\n\n"
                    )

                    log_file.write(log_entry)
                    self.log_activity(f"  > [{error_type}] {details}")
            messagebox.showerror(
                "Validation Failed",
                f"File '{filename}' contains data structural errors."
            )
        else:
            self.log_activity(f"Success check file verification complete. File '{filename}' verified clean.")
            messagebox.showinfo(
                "Validation Passed",
                f"File '{filename}' successfully verified against execution rules parameters safely.",
            )


class SalesValidationSystem(tk.Tk):

    def __init__(self):
        super().__init__()
        self.title("Sales Data Validation System")
        self.geometry("1100x700")
        self.configure(bg="#C0DDDA")

        self.ftp_manager = FTPClientManager()
        self.validator = SalesDataValidator()

        style = ttk.Style()
        style.theme_use("clam")

        self._build_header()
        self._build_top_panels()
        self._build_bottom_panels()

        self.logger = LoggerManager(self.activity_text_box)
        self.logger.log_activity("Sale Data Console initialized.")
        self.logger.log_activity("Ready for connection. Please configure FTP settings.")

    def _build_header(self):
        frame1 = tk.Frame(self, bg="#C0DDDA")
        frame1.pack(fill="x", padx=15, pady=10)

        frame1_label = tk.Label(
            frame1,
            text="SALE DATA VALIDATION SYSTEM",
            font=("Arial", 14, "bold"),
            bg="#C0DDDA"
        )
        frame1_label.pack(side="left", pady=5)

        self.status_label = tk.Label(
            frame1,
            text="Disconnected",
            font=("Arial", 10, "bold"),
            bg="#C0DDDA",
            foreground="#555555"
        )
        self.status_label.pack(side="right", pady=5, padx=10)

    def _build_top_panels(self):
        top_panels_frame = tk.Frame(self, bg="#C0DDDA")
        top_panels_frame.pack(fill="x", padx=10, pady=5)

        # 1. Connection Panel
        connection_frame = ttk.LabelFrame(top_panels_frame, text="Connection", width=200, height=280)
        connection_frame.pack(side="left", padx=5, pady=5)
        connection_frame.pack_propagate(False)

        tk.Label(connection_frame, text="FTP Host", anchor="w").pack(fill="x", padx=10, pady=(10, 2))
        self.host_entry = ttk.Entry(connection_frame, width=25)
        self.host_entry.insert(0, "127.0.0.1")
        self.host_entry.pack(padx=10, pady=(0, 15))

        tk.Label(connection_frame, text="Username", anchor="w").pack(fill="x", padx=10, pady=(2, 2))
        self.user_entry = ttk.Entry(connection_frame, width=25, textvariable=tk.StringVar(value="chew"))
        self.user_entry.pack(padx=10, pady=(0, 15))

        tk.Label(connection_frame, text="Password", anchor="w").pack(fill="x", padx=10, pady=(2, 2))
        self.pass_entry = ttk.Entry(connection_frame, show="*", width=25, textvariable=tk.StringVar(value="882007"))
        self.pass_entry.pack(padx=10, pady=(0, 15))

        conn_btn_frame = tk.Frame(connection_frame)
        conn_btn_frame.pack(fill="x", padx=10, pady=(0, 15))

        self.connect_btn = ttk.Button(conn_btn_frame, text="Connect", width=10, command=self.connect_ftp)
        self.connect_btn.pack(side="left", padx=(0, 5))

        self.disconnect_btn = ttk.Button(conn_btn_frame, text="Disconnect", width=12, command=self.disconnect_ftp)
        self.disconnect_btn.pack(side="left")

        # 2. Server Browser Panel
        browser_frame = ttk.LabelFrame(top_panels_frame, text="Server Browser", width=1100, height=280)
        browser_frame.pack(side="left", padx=5, pady=5)
        browser_frame.pack_propagate(False)

        filter_frame = tk.Frame(browser_frame)
        filter_frame.pack(fill="x", padx=10, pady=10)

        tk.Label(filter_frame, text="Filter:").pack(side="left", padx=(0, 5))
        self.filter_entry = ttk.Entry(filter_frame)
        self.filter_entry.pack(side="left", fill="x", expand=True, padx=(0, 5))

        ttk.Button(filter_frame, text="Apply", width=6, command=self.filter_files).pack(side="left", padx=(0, 2))
        ttk.Button(filter_frame, text="Res", width=5, command=self.clear_search).pack(side="left")

        listbox_frame = tk.Frame(browser_frame)
        listbox_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        scrollbar = tk.Scrollbar(listbox_frame)
        scrollbar.pack(side="right", fill="y")

        self.server_listbox = tk.Listbox(listbox_frame, bd=1, height=10, background="white", yscrollcommand=scrollbar.set)
        self.server_listbox.pack(fill="both", expand=True)
        scrollbar.config(command=self.server_listbox.yview)

    def _build_bottom_panels(self):
        # 3. Workspace & Actions Panel
        workspace_frame = ttk.LabelFrame(self, text="Workspace & Actions", width=600, height=300)
        workspace_frame.pack(side="left", padx=15, pady=5)
        workspace_frame.pack_propagate(False)

        tk.Label(workspace_frame, text="Download directory", anchor="w").pack(fill="x", padx=10, pady=(5, 2))
        dir1_frame = tk.Frame(workspace_frame)
        dir1_frame.pack(fill="x", padx=10, pady=(0, 5))
        self.dir1_entry = ttk.Entry(dir1_frame)
        self.dir1_entry.pack(side="left", fill="x", expand=True, padx=(0, 5))
        ttk.Button(dir1_frame, text="Browse...", width=10, command=lambda: self.browse_directory(self.dir1_entry)).pack(side="right")

        tk.Label(workspace_frame, text="Archive (Correct Files) directory", anchor="w").pack(fill="x", padx=10, pady=(5, 2))
        dir2_frame = tk.Frame(workspace_frame)
        dir2_frame.pack(fill="x", padx=10, pady=(0, 5))
        self.dir2_entry = ttk.Entry(dir2_frame)
        self.dir2_entry.pack(side="left", fill="x", expand=True, padx=(0, 5))
        ttk.Button(dir2_frame, text="Browse...", width=10, command=lambda: self.browse_directory(self.dir2_entry)).pack(side="right")

        tk.Label(workspace_frame, text="Errors directory", anchor="w").pack(fill="x", padx=10, pady=(5, 2))
        dir3_frame = tk.Frame(workspace_frame)
        dir3_frame.pack(fill="x", padx=10, pady=(0, 10))
        self.dir3_entry = ttk.Entry(dir3_frame)
        self.dir3_entry.pack(side="left", fill="x", expand=True, padx=(0, 5))
        ttk.Button(dir3_frame, text="Browse...", width=10, command=lambda: self.browse_directory(self.dir3_entry)).pack(side="right")

        ttk.Button(workspace_frame, text="Validate Selected File", command=self.validate_selected_file).pack(side="left", padx=10, pady=2)
        ttk.Button(workspace_frame, text="Process Selected File", command=self.process_selected_file).pack(side="left", padx=10, pady=2)

        split_btn_frame = tk.Frame(workspace_frame)
        split_btn_frame.pack(side="left", padx=10, pady=2)

        ttk.Button(split_btn_frame, text="Open Error Log", command=self.open_error_log).pack(side="left", padx=10, pady=2)
        ttk.Button(split_btn_frame, text="Clear Activity Feed", command=lambda: self.logger.clear()).pack(side="left", padx=10, pady=2)

        # 4. Activity Feed Panel
        activity_frame = ttk.LabelFrame(self, text="Activity Feed", width=750, height=300)
        activity_frame.pack(side="left", padx=15, pady=(5, 15))
        activity_frame.pack_propagate(False)

        self.activity_text_box = tk.Text(activity_frame, bg="white", bd=1, height=8)
        self.activity_text_box.pack(fill="both", expand=True, padx=10, pady=10)

    def browse_directory(self, entry_widget):
        selected_dir = filedialog.askdirectory()
        if selected_dir:
            entry_widget.delete(0, tk.END)
            entry_widget.insert(0, os.path.normpath(selected_dir))
            self.logger.log_activity(f"Directory configuration linked: {selected_dir}")

    def connect_ftp(self):
        if self.ftp_manager.is_connected:
            return

        host = self.host_entry.get().strip()
        username = self.user_entry.get().strip()
        password = self.pass_entry.get()

        if not host:
            self.logger.log_activity("Connection failed: Host field is empty.")
            messagebox.showwarning("Warning", "Please enter a host address.")
            return

        self.logger.log_activity(f"Connecting to {host}...")

        try:
            files = self.ftp_manager.connect(host, username, password)
            self.logger.log_activity("Connected successfully.")
            self.status_label.config(text="Connected", foreground="#2E7D32")

            self.server_listbox.delete(0, tk.END)
            self.filter_entry.delete(0, tk.END)

            if files:
                for file in files:
                    self.server_listbox.insert(tk.END, file)
                self.logger.log_activity(f"Found {len(files)} CSV files on server.")
            else:
                self.server_listbox.insert(tk.END, "No files found")
                self.logger.log_activity("Directory listing returned empty.")

        except Exception as e:
            self.server_listbox.delete(0, tk.END)
            self.logger.log_activity(f"ERROR: Connection failed: {str(e)}")
            messagebox.showerror("FTP Error", str(e))

    def disconnect_ftp(self):
        if not self.ftp_manager.is_connected:
            return

        self.ftp_manager.disconnect()
        self.filter_entry.delete(0, tk.END)
        self.server_listbox.delete(0, tk.END)
        self.logger.log_activity("Disconnected from server.")
        self.status_label.config(text="Disconnected", foreground="#555555")

    def _ensure_file_downloaded(self, filename, download_dir):
        local_filepath = os.path.join(download_dir, filename)
        if not os.path.exists(local_filepath):
            if self.ftp_manager.is_connected:
                self.logger.log_activity(f"Downloading {filename}...")
                self.ftp_manager.download_file(filename, local_filepath)
            else:
                raise FileNotFoundError("File not found locally and FTP is not connected.")
        return local_filepath

    def validate_selected_file(self):
        download_dir = self.dir1_entry.get().strip()
        errors_dir = self.dir3_entry.get().strip()

        if not download_dir:
            messagebox.showwarning("Warning", "Please select Download directory first.")
            return

        selected_index = self.server_listbox.curselection()
        if not selected_index:
            messagebox.showwarning("Warning", "Please select a file first.")
            return

        filename = self.server_listbox.get(selected_index)
        os.makedirs(download_dir, exist_ok=True)

        try:
            filepath = self._ensure_file_downloaded(filename, download_dir)
            errors = self.validator.validate_file(filepath, filename)

            if errors:
                if errors_dir:
                    log_path = os.path.join(errors_dir, "validation_errors.log")
                    self.logger.write_and_log_errors(filename, errors, log_path)
                else:
                    messagebox.showerror("Validation Failed", f"File '{filename}' contains data structural errors.")
            else:
                self.logger.log_activity(f"{filename} PASSED validation.")
                messagebox.showinfo("Validation Passed", f"File '{filename}' is valid.")

        except Exception as e:
            messagebox.showerror("Error", str(e))

    def process_selected_file(self):
        download_dir = self.dir1_entry.get().strip()
        archive_dir = self.dir2_entry.get().strip()
        errors_dir = self.dir3_entry.get().strip()

        if not download_dir or not archive_dir or not errors_dir:
            messagebox.showwarning("Warning", "Please select Download, Archive, and Errors directories first.")
            return

        selected_index = self.server_listbox.curselection()
        if not selected_index:
            messagebox.showwarning("Warning", "Please select a file from the server browser first.")
            return

        filename = self.server_listbox.get(selected_index)

        os.makedirs(download_dir, exist_ok=True)
        os.makedirs(archive_dir, exist_ok=True)
        os.makedirs(errors_dir, exist_ok=True)

        try:
            local_filepath = self._ensure_file_downloaded(filename, download_dir)
        except Exception as e:
            self.logger.log_activity(f"Processing Error: {str(e)}")
            messagebox.showerror("Error", str(e))
            return

        self.logger.log_activity(f"Processing file routing for: {filename}")
        errors_found = self.validator.validate_file(local_filepath, filename)

        if not errors_found:
            destination_path = os.path.join(archive_dir, filename)
            os.replace(local_filepath, destination_path)
            self.logger.log_activity(f"SUCCESS: Clean file routed to Archive -> {destination_path}")
            messagebox.showinfo("Success", "Valid file successfully processed into the Archive folder!")
        else:
            log_path = os.path.join(errors_dir, "validation_errors.log")
            self.logger.write_and_log_errors(filename, errors_found, log_path)

            destination_path = os.path.join(errors_dir, filename)
            os.replace(local_filepath, destination_path)

            self.logger.log_activity(f"REJECTED: Malformed file routed to Errors -> {destination_path}")

    def open_error_log(self):
        errors_dir = self.dir3_entry.get().strip()
        if not errors_dir:
            messagebox.showwarning("Warning", "Please configure your Errors directory pathway first.")
            return

        log_filepath = os.path.join(errors_dir, "validation_errors.log")
        if os.path.exists(log_filepath):
            if hasattr(os, "startfile"):
                os.startfile(log_filepath)
            else:
                os.system(f'xdg-open "{log_filepath}"')
        else:
            messagebox.showinfo("Log Empty", "No log records found.")

    def filter_files(self):
        search_term = self.filter_entry.get().strip().lower()

        if not self.ftp_manager.is_connected:
            self.logger.log_activity("Search ignored: Not connected to an FTP server.")
            return

        self.server_listbox.delete(0, tk.END)
        filtered_files = [f for f in self.ftp_manager.all_files if search_term in f.lower()]

        if filtered_files:
            for file in filtered_files:
                self.server_listbox.insert(tk.END, file)
        else:
            self.server_listbox.insert(tk.END, "No matching files found")

    def clear_search(self):
        self.filter_entry.delete(0, tk.END)
        self.server_listbox.delete(0, tk.END)
        if self.ftp_manager.all_files:
            for file in self.ftp_manager.all_files:
                self.server_listbox.insert(tk.END, file)


if __name__ == "__main__":
    app = SalesValidationSystem()
    app.mainloop()