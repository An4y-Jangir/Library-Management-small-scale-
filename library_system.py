"""
=============================================================================
                  LIBRARY MANAGEMENT SYSTEM (GUI)
=============================================================================
A complete, unified Library Management System built with Python & Tkinter.
Supports MySQL database with automatic SQLite fallback for zero-setup execution
on any computer.

Features:
- Student Portal: Browse catalog, search books, borrow books (with 7-day due date),
  view borrowed books, and return books.
- Admin / Librarian Portal: Manage book inventory (add, edit, delete), search catalog,
  view circulation & borrow records, mark returns, and manage user accounts.
- Dual Database Engine: Full MySQL support + Built-in SQLite mode.
- Interactive Database Configuration Dialog directly inside the GUI.
- Seamless data seeding from legacy books.txt and user accounts.
=============================================================================
"""

import os
import sys
import csv
import json
import datetime
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog

# Try importing mysql.connector gracefully
try:
    import mysql.connector
    from mysql.connector import Error as MySQLError
    MYSQL_AVAILABLE = True
except ImportError:
    MYSQL_AVAILABLE = False
    MySQLError = Exception

import sqlite3

CONFIG_FILE = "db_config.json"
SQLITE_DB_FILE = "library_database.db"


# =============================================================================
#                           DATABASE MANAGER
# =============================================================================

class DatabaseManager:
    """
    Unified database manager supporting both MySQL and SQLite.
    Translates SQL query parameter placeholders (%s to ?) automatically
    when running in SQLite mode.
    """
    def __init__(self, config_path=CONFIG_FILE):
        self.config_path = config_path
        self.db_type = "sqlite"  # 'mysql' or 'sqlite'
        self.connection = None
        self.config = self.load_config()
        self.last_error = None
        self.active_status = "Not Connected"
        self.auto_connect()

    def load_config(self):
        default = {
            "db_type": "mysql",
            "host": "localhost",
            "port": 3306,
            "user": "root",
            "password": "",
            "database": "library_db"
        }
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    default.update(data)
            except Exception as e:
                print(f"[Config] Error reading {self.config_path}: {e}")
        return default

    def save_config(self):
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=4)
        except Exception as e:
            print(f"[Config] Error saving {self.config_path}: {e}")

    def auto_connect(self):
        """
        Attempts to connect to MySQL if configured and available.
        If MySQL connection fails or is unavailable, falls back to SQLite seamlessly.
        """
        preferred = self.config.get("db_type", "mysql")
        if preferred == "mysql" and MYSQL_AVAILABLE:
            success, msg = self.connect_mysql(
                host=self.config.get("host", "localhost"),
                port=self.config.get("port", 3306),
                user=self.config.get("user", "root"),
                password=self.config.get("password", ""),
                database=self.config.get("database", "library_db")
            )
            if success:
                return True, msg
            else:
                self.last_error = msg
                # Fallback to SQLite so the app NEVER crashes on any system
                s_ok, s_msg = self.connect_sqlite()
                return False, f"MySQL connection failed: {msg}\nSwitched to Local SQLite mode."
        else:
            return self.connect_sqlite()

    def connect_mysql(self, host, port, user, password, database):
        if not MYSQL_AVAILABLE:
            return False, "mysql-connector-python is not installed. Install via: pip install mysql-connector-python"

        try:
            port = int(port)
        except ValueError:
            port = 3306

        try:
            # First connect to server to ensure database exists
            temp_conn = mysql.connector.connect(
                host=host,
                port=port,
                user=user,
                password=password,
                connection_timeout=4
            )
            cur = temp_conn.cursor()
            cur.execute(f"CREATE DATABASE IF NOT EXISTS `{database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
            cur.close()
            temp_conn.close()

            # Now connect to specific database
            if self.connection:
                try:
                    self.connection.close()
                except Exception:
                    pass

            self.connection = mysql.connector.connect(
                host=host,
                port=port,
                user=user,
                password=password,
                database=database,
                connection_timeout=5
            )
            self.db_type = "mysql"
            self.config["db_type"] = "mysql"
            self.config["host"] = host
            self.config["port"] = port
            self.config["user"] = user
            self.config["password"] = password
            self.config["database"] = database
            self.save_config()

            self.init_schema()
            self.seed_data()
            self.active_status = f"MySQL ({host}:{port}/{database})"
            return True, f"Successfully connected to MySQL database '{database}'."

        except Exception as e:
            return False, str(e)

    def connect_sqlite(self, db_path=SQLITE_DB_FILE):
        try:
            if self.connection:
                try:
                    self.connection.close()
                except Exception:
                    pass

            self.connection = sqlite3.connect(db_path, check_same_thread=False)
            self.db_type = "sqlite"
            self.config["db_type"] = "sqlite"
            self.save_config()

            self.init_schema()
            self.seed_data()
            self.active_status = f"SQLite (Local: {os.path.basename(db_path)})"
            return True, "Connected to Local SQLite database."
        except Exception as e:
            return False, str(e)

    def init_schema(self):
        """Initializes tables in the active database engine."""
        cursor = self.connection.cursor()
        if self.db_type == "mysql":
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    username VARCHAR(100) UNIQUE NOT NULL,
                    password VARCHAR(255) NOT NULL,
                    role VARCHAR(50) NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS books (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    title VARCHAR(255) UNIQUE NOT NULL,
                    author VARCHAR(255) DEFAULT 'Unknown',
                    genre VARCHAR(100) DEFAULT 'General',
                    total_copies INT DEFAULT 1,
                    available_copies INT DEFAULT 1,
                    added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS borrow_records (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    student_username VARCHAR(100) NOT NULL,
                    book_id INT,
                    book_title VARCHAR(255) NOT NULL,
                    borrow_date VARCHAR(50) NOT NULL,
                    due_date VARCHAR(50) NOT NULL,
                    return_date VARCHAR(50) DEFAULT NULL,
                    status VARCHAR(50) DEFAULT 'Borrowed'
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)
            # Auto-migrate any columns if books table pre-existed with different columns
            for col, defn in [
                ('genre', 'VARCHAR(100) DEFAULT "General"'),
                ('available_copies', 'INT DEFAULT 1'),
                ('total_copies', 'INT DEFAULT 1'),
                ('added_date', 'TIMESTAMP DEFAULT CURRENT_TIMESTAMP')
            ]:
                try:
                    cursor.execute(f"SHOW COLUMNS FROM books LIKE '{col}'")
                    if not cursor.fetchone():
                        cursor.execute(f"ALTER TABLE books ADD COLUMN {col} {defn}")
                except Exception:
                    pass
        else:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password TEXT NOT NULL,
                    role TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS books (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT UNIQUE NOT NULL,
                    author TEXT DEFAULT 'Unknown',
                    genre TEXT DEFAULT 'General',
                    total_copies INTEGER DEFAULT 1,
                    available_copies INTEGER DEFAULT 1,
                    added_date TEXT DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS borrow_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    student_username TEXT NOT NULL,
                    book_id INTEGER,
                    book_title TEXT NOT NULL,
                    borrow_date TEXT NOT NULL,
                    due_date TEXT NOT NULL,
                    return_date TEXT DEFAULT NULL,
                    status TEXT DEFAULT 'Borrowed'
                );
            """)
        self.connection.commit()
        cursor.close()

    def seed_data(self):
        """Seeds initial data (default admin, existing books.txt, user files)."""
        # 1. Default Admin account
        admin = self.get_user("admin")
        if not admin:
            self.add_user("admin", "admin123", "admin")

        # 2. Legacy student files (e.g., Anay, Jayson)
        for fname in ["Anay", "Jayson"]:
            if os.path.exists(fname):
                try:
                    with open(fname, "r", encoding="utf-8") as f:
                        lines = [line.strip() for line in f if line.strip()]
                        if len(lines) >= 2:
                            uname, pwd = lines[0], lines[1]
                            if not self.get_user(uname):
                                self.add_user(uname, pwd, "student")
                except Exception:
                    pass

        # 3. Seed default curated book collection
        existing_books = self.fetch_all("SELECT id FROM books LIMIT 1")
        if not existing_books:
            default_catalog = [
                ("The Honey Queen", "Cathy Kelly", "Fiction", 3, 3),
                ("Exile", "Shannon Messenger", "Fantasy", 3, 3),
                ("Dancing In The Moonlight", "RaeAnne Thayne", "Romance", 3, 3),
                ("Success Mathematics", "Academic Press", "Mathematics", 5, 5),
                ("Forrest Gump", "Winston Groom", "Classic Fiction", 4, 4),
                ("Meow", "Sam Stall", "Humor / Pets", 3, 3),
                ("To Kill a Mockingbird", "Harper Lee", "Classic Fiction", 5, 5),
                ("The Great Gatsby", "F. Scott Fitzgerald", "Classic Fiction", 4, 4),
                ("1984", "George Orwell", "Dystopian", 6, 6),
                ("Pride and Prejudice", "Jane Austen", "Classic Literature", 4, 4),
                ("The Catcher in the Rye", "J.D. Salinger", "Literary Fiction", 3, 3),
                ("Harry Potter and the Sorcerer's Stone", "J.K. Rowling", "Fantasy", 8, 8),
                ("The Hobbit", "J.R.R. Tolkien", "Fantasy", 5, 5),
                ("Dune", "Frank Herbert", "Science Fiction", 5, 5),
                ("Clean Code", "Robert C. Martin", "Computer Science", 4, 4),
                ("Introduction to Algorithms", "Thomas H. Cormen", "Computer Science", 5, 5),
                ("Python Crash Course", "Eric Matthes", "Programming", 6, 6),
                ("A Brief History of Time", "Stephen Hawking", "Physics / Science", 4, 4),
                ("Calculus: Early Transcendentals", "James Stewart", "Mathematics", 5, 5),
                ("Linear Algebra Done Right", "Sheldon Axler", "Mathematics", 4, 4),
                ("Atomic Habits", "James Clear", "Self-Help", 7, 7),
                ("Sapiens: A Brief History of Humankind", "Yuval Noah Harari", "History", 5, 5),
                ("Thinking, Fast and Slow", "Daniel Kahneman", "Psychology", 4, 4)
            ]
            for b in default_catalog:
                try:
                    self.execute_query(
                        "INSERT INTO books (title, author, genre, total_copies, available_copies) VALUES (%s, %s, %s, %s, %s)",
                        b
                    )
                except Exception:
                    pass

            # Also import any extra titles from books.txt if present
            if os.path.exists("books.txt"):
                try:
                    with open("books.txt", "r", encoding="utf-8") as f:
                        for line in f:
                            title = line.strip()
                            if title and not self.fetch_one("SELECT id FROM books WHERE title = %s", (title,)):
                                try:
                                    self.execute_query(
                                        "INSERT INTO books (title, author, genre, total_copies, available_copies) VALUES (%s, %s, %s, %s, %s)",
                                        (title, "Library Collection", "General", 3, 3)
                                    )
                                except Exception:
                                    pass
                except Exception as e:
                    print(f"[Seed] Error reading books.txt: {e}")

    def execute_query(self, query, params=None):
        if self.db_type == "sqlite":
            query = query.replace("%s", "?")
        cursor = self.connection.cursor()
        if params is not None:
            cursor.execute(query, params)
        else:
            cursor.execute(query)
        self.connection.commit()
        return cursor

    def fetch_all(self, query, params=None):
        if self.db_type == "sqlite":
            query = query.replace("%s", "?")
        cursor = self.connection.cursor()
        if params is not None:
            cursor.execute(query, params)
        else:
            cursor.execute(query)
        rows = cursor.fetchall()
        cursor.close()
        return rows

    def fetch_one(self, query, params=None):
        if self.db_type == "sqlite":
            query = query.replace("%s", "?")
        cursor = self.connection.cursor()
        if params is not None:
            cursor.execute(query, params)
        else:
            cursor.execute(query)
        row = cursor.fetchone()
        cursor.close()
        return row

    # --- User Operations ---
    def get_user(self, username):
        return self.fetch_one("SELECT id, username, password, role FROM users WHERE username = %s", (username,))

    def add_user(self, username, password, role):
        try:
            self.execute_query(
                "INSERT INTO users (username, password, role) VALUES (%s, %s, %s)",
                (username, password, role)
            )
            return True, "User registered successfully!"
        except Exception as e:
            return False, f"Username '{username}' already exists or registration failed."

    # --- Book Operations ---
    def get_all_books(self, search_term=""):
        if search_term:
            param = f"%{search_term}%"
            return self.fetch_all(
                "SELECT id, title, author, genre, available_copies, total_copies, added_date FROM books "
                "WHERE title LIKE %s OR author LIKE %s OR genre LIKE %s ORDER BY id ASC",
                (param, param, param)
            )
        return self.fetch_all(
            "SELECT id, title, author, genre, available_copies, total_copies, added_date FROM books ORDER BY id ASC"
        )

    def add_book(self, title, author, genre, total_copies):
        try:
            self.execute_query(
                "INSERT INTO books (title, author, genre, total_copies, available_copies) VALUES (%s, %s, %s, %s, %s)",
                (title.strip(), author.strip(), genre.strip(), total_copies, total_copies)
            )
            return True, "Book added successfully!"
        except Exception as e:
            return False, f"Book with title '{title}' already exists."

    def update_book(self, book_id, title, author, genre, total_copies):
        try:
            book = self.fetch_one("SELECT total_copies, available_copies FROM books WHERE id = %s", (book_id,))
            if not book:
                return False, "Book not found."
            old_total, old_available = book[0], book[1]
            diff = total_copies - old_total
            new_available = max(0, old_available + diff)

            self.execute_query(
                "UPDATE books SET title = %s, author = %s, genre = %s, total_copies = %s, available_copies = %s WHERE id = %s",
                (title.strip(), author.strip(), genre.strip(), total_copies, new_available, book_id)
            )
            return True, "Book updated successfully!"
        except Exception as e:
            return False, str(e)

    def delete_book(self, book_id):
        try:
            self.execute_query("DELETE FROM books WHERE id = %s", (book_id,))
            return True, "Book deleted successfully."
        except Exception as e:
            return False, str(e)

    # --- Borrowing Operations ---
    def borrow_book(self, student_username, book_id, borrow_date_str):
        # 1. Check book availability
        book = self.fetch_one("SELECT id, title, available_copies FROM books WHERE id = %s", (book_id,))
        if not book:
            return False, "Book not found."
        
        book_title = book[1]
        available = book[2]

        if available <= 0:
            return False, f"Sorry, '{book_title}' is currently out of stock."

        # 2. Check if student already has this book borrowed & unreturned
        existing = self.fetch_one(
            "SELECT id FROM borrow_records WHERE student_username = %s AND book_title = %s AND status = 'Borrowed'",
            (student_username, book_title)
        )
        if existing:
            return False, f"You already have an active borrowed copy of '{book_title}'. Please return it first."

        # 3. Calculate 7-day return due date
        try:
            borrow_dt = datetime.datetime.strptime(borrow_date_str, "%d-%m-%Y")
        except ValueError:
            return False, "Invalid date format. Please use DD-MM-YYYY."

        due_dt = borrow_dt + datetime.timedelta(days=7)
        due_date_str = due_dt.strftime("%d-%m-%Y")

        # 4. Insert borrow record and decrement available copies
        try:
            self.execute_query(
                "INSERT INTO borrow_records (student_username, book_id, book_title, borrow_date, due_date, return_date, status) "
                "VALUES (%s, %s, %s, %s, %s, NULL, 'Borrowed')",
                (student_username, book_id, book_title, borrow_date_str, due_date_str)
            )
            self.execute_query(
                "UPDATE books SET available_copies = available_copies - 1 WHERE id = %s",
                (book_id,)
            )
            return True, f"Successfully borrowed '{book_title}'!\nPlease return by: {due_date_str}"
        except Exception as e:
            return False, f"Borrowing transaction failed: {e}"

    def return_book(self, record_id):
        record = self.fetch_one("SELECT id, book_id, book_title, status FROM borrow_records WHERE id = %s", (record_id,))
        if not record:
            return False, "Borrow record not found."
        
        book_id = record[1]
        book_title = record[2]
        status = record[3]

        if status == "Returned":
            return False, "This book has already been returned."

        return_date_str = datetime.date.today().strftime("%d-%m-%Y")

        try:
            self.execute_query(
                "UPDATE borrow_records SET return_date = %s, status = 'Returned' WHERE id = %s",
                (return_date_str, record_id)
            )
            # Restore available copies
            if book_id:
                self.execute_query(
                    "UPDATE books SET available_copies = available_copies + 1 WHERE id = %s",
                    (book_id,)
                )
            else:
                self.execute_query(
                    "UPDATE books SET available_copies = available_copies + 1 WHERE title = %s",
                    (book_title,)
                )
            return True, f"Book '{book_title}' has been successfully returned!"
        except Exception as e:
            return False, f"Failed to return book: {e}"

    def get_student_borrow_records(self, student_username):
        return self.fetch_all(
            "SELECT id, book_title, borrow_date, due_date, status, return_date FROM borrow_records "
            "WHERE student_username = %s ORDER BY id DESC",
            (student_username,)
        )

    def get_all_borrow_records(self, search_term=""):
        if search_term:
            param = f"%{search_term}%"
            return self.fetch_all(
                "SELECT id, student_username, book_title, borrow_date, due_date, return_date, status FROM borrow_records "
                "WHERE student_username LIKE %s OR book_title LIKE %s ORDER BY id DESC",
                (param, param)
            )
        return self.fetch_all(
            "SELECT id, student_username, book_title, borrow_date, due_date, return_date, status FROM borrow_records "
            "ORDER BY id DESC"
        )

    def get_all_users(self):
        return self.fetch_all("SELECT id, username, role, created_at FROM users ORDER BY role ASC, username ASC")

    def get_stats(self):
        try:
            total_titles = self.fetch_one("SELECT COUNT(*) FROM books")[0] or 0
            total_copies = self.fetch_one("SELECT SUM(total_copies) FROM books")[0] or 0
            avail_copies = self.fetch_one("SELECT SUM(available_copies) FROM books")[0] or 0
            active_loans = self.fetch_one("SELECT COUNT(*) FROM borrow_records WHERE status = 'Borrowed'")[0] or 0
            students_count = self.fetch_one("SELECT COUNT(*) FROM users WHERE role = 'student'")[0] or 0
            return {
                "total_titles": int(total_titles),
                "total_copies": int(total_copies),
                "avail_copies": int(avail_copies),
                "active_loans": int(active_loans),
                "students_count": int(students_count)
            }
        except Exception:
            return {"total_titles": 0, "total_copies": 0, "avail_copies": 0, "active_loans": 0, "students_count": 0}


# Global Database Instance
db = DatabaseManager()


# =============================================================================
#                        TKINTER GUI APPLICATION
# =============================================================================

class LibraryApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Library Management System")
        self.geometry("1000x680")
        self.minsize(920, 600)
        self.configure(bg="#F1F5F9")

        # Center the window
        self.center_window(1000, 680)

        # Style configuration
        self.style = ttk.Style()
        self.configure_styles()

        # State tracking
        self.current_user = None
        self.current_role = None

        # Container frame for swapping views
        self.container = tk.Frame(self, bg="#F1F5F9")
        self.container.pack(fill="both", expand=True)

        # Create Top Header Banner
        self.create_header()

        # Create Bottom Status Bar
        self.create_status_bar()

        # Connect to Database (MySQL with SQLite fallback)
        self.init_database()

        # Show initial view (Welcome Screen)
        self.show_welcome_screen()

    def center_window(self, width, height):
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        x = (sw - width) // 2
        y = (sh - height) // 2
        self.geometry(f"{width}x{height}+{x}+{y}")

    def enable_treeview_sorting(self, tree):
        """Allows clicking any table column header to dynamically sort ascending/descending."""
        def sort_column(col, reverse):
            items = [(tree.set(k, col), k) for k in tree.get_children("")]
            try:
                items.sort(key=lambda t: int(str(t[0]).strip()), reverse=reverse)
            except ValueError:
                try:
                    items.sort(key=lambda t: float(str(t[0]).strip()), reverse=reverse)
                except ValueError:
                    items.sort(key=lambda t: str(t[0]).lower(), reverse=reverse)

            for index, (val, k) in enumerate(items):
                tree.move(k, "", index)

            tree.heading(col, command=lambda: sort_column(col, not reverse))

        for col in tree["columns"]:
            tree.heading(col, command=lambda c=col: sort_column(c, False))

    def configure_styles(self):
        try:
            self.style.theme_use("clam")
        except Exception:
            pass

        # Color Palette
        PRIMARY = "#1E3A8A"      # Deep Navy Blue
        SECONDARY = "#2563EB"    # Vivid Blue
        ACCENT = "#059669"       # Emerald Green
        DANGER = "#DC2626"       # Crimson Red
        BG_COLOR = "#F8FAFC"     # Slate 50
        CARD_BG = "#FFFFFF"

        self.style.configure(".", background=BG_COLOR, font=("Segoe UI", 10))

        # TNotebook styles
        self.style.configure("TNotebook", background="#F1F5F9")
        self.style.configure("TNotebook.Tab", font=("Segoe UI", 10, "bold"), padding=[14, 6], background="#E2E8F0")
        self.style.map("TNotebook.Tab", background=[("selected", "#2563EB")], foreground=[("selected", "#FFFFFF")])

        # Button styles
        self.style.configure("Primary.TButton", font=("Segoe UI", 10, "bold"), background=SECONDARY, foreground="#FFFFFF")
        self.style.map("Primary.TButton", background=[("active", "#1D4ED8")])

        self.style.configure("Success.TButton", font=("Segoe UI", 10, "bold"), background=ACCENT, foreground="#FFFFFF")
        self.style.map("Success.TButton", background=[("active", "#047857")])

        self.style.configure("Danger.TButton", font=("Segoe UI", 10, "bold"), background=DANGER, foreground="#FFFFFF")
        self.style.map("Danger.TButton", background=[("active", "#B91C1C")])

        self.style.configure("Outline.TButton", font=("Segoe UI", 10), background="#E2E8F0", foreground="#1E293B")

        # Treeview styling
        self.style.configure(
            "Treeview",
            background="#FFFFFF",
            foreground="#1E293B",
            rowheight=28,
            fieldbackground="#FFFFFF",
            font=("Segoe UI", 9)
        )
        self.style.configure(
            "Treeview.Heading",
            background="#1E3A8A",
            foreground="#FFFFFF",
            font=("Segoe UI", 10, "bold"),
            relief="flat"
        )
        self.style.map("Treeview.Heading", background=[("active", "#2563EB")])
        self.style.map("Treeview", background=[("selected", "#DBEAFE")], foreground=[("selected", "#1E3A8A")])

    def create_header(self):
        self.header_frame = tk.Frame(self, bg="#1E3A8A", height=60)
        self.header_frame.pack(side="top", fill="x")

        # App Title & Icon
        title_box = tk.Frame(self.header_frame, bg="#1E3A8A")
        title_box.pack(side="left", padx=20, pady=10)

        icon_label = tk.Label(title_box, text="📖", font=("Segoe UI Emoji", 20), bg="#1E3A8A", fg="#FFFFFF")
        icon_label.pack(side="left", padx=(0, 10))

        title_label = tk.Label(title_box, text="LIBRARY MANAGEMENT SYSTEM", font=("Segoe UI", 14, "bold"), bg="#1E3A8A", fg="#FFFFFF")
        title_label.pack(side="top", anchor="w")

        subtitle_label = tk.Label(title_box, text="Automated Catalog & Circulation Platform", font=("Segoe UI", 8), bg="#1E3A8A", fg="#93C5FD")
        subtitle_label.pack(side="top", anchor="w")

        # Right Header: DB Badge & Settings button
        right_box = tk.Frame(self.header_frame, bg="#1E3A8A")
        right_box.pack(side="right", padx=20, pady=12)

        self.db_badge = tk.Label(
            right_box,
            text=f"● {db.active_status}",
            font=("Segoe UI", 9, "bold"),
            bg="#065F46" if db.db_type == "mysql" else "#0369A1",
            fg="#FFFFFF",
            padx=10,
            pady=4
        )
        self.db_badge.pack(side="left", padx=8)

        db_btn = tk.Button(
            right_box,
            text="⚙️ DB Settings",
            font=("Segoe UI", 9, "bold"),
            bg="#2563EB",
            fg="#FFFFFF",
            activebackground="#1D4ED8",
            activeforeground="#FFFFFF",
            relief="flat",
            cursor="hand2",
            padx=8,
            pady=3,
            command=self.open_db_settings_dialog
        )
        db_btn.pack(side="left")

    def create_status_bar(self):
        self.status_bar = tk.Frame(self, bg="#E2E8F0", height=26)
        self.status_bar.pack(side="bottom", fill="x")

        self.status_label = tk.Label(
            self.status_bar,
            text="Ready | System Loaded",
            font=("Segoe UI", 9),
            bg="#E2E8F0",
            fg="#475569"
        )
        self.status_label.pack(side="left", padx=15)

        self.status_user_label = tk.Label(
            self.status_bar,
            text="Role: Guest",
            font=("Segoe UI", 9, "italic"),
            bg="#E2E8F0",
            fg="#475569"
        )
        self.status_user_label.pack(side="right", padx=15)

    def set_status(self, text):
        self.status_label.config(text=text)

    def update_header_badge(self):
        if db.db_type == "mysql":
            self.db_badge.config(text=f"● MySQL: {db.config.get('database','library_db')}", bg="#065F46")
        else:
            self.db_badge.config(text=f"● SQLite Mode", bg="#0369A1")

    def init_database(self):
        success, msg = db.auto_connect()
        self.update_header_badge()
        if not success:
            # Show friendly notification informing about SQLite fallback
            self.after(500, lambda: messagebox.showinfo(
                "Database Notification",
                f"{msg}\n\nYou can use the system immediately with the built-in local database, "
                f"or click '⚙️ DB Settings' at the top right to configure your MySQL connection."
            ))

    def clear_container(self):
        for widget in self.container.winfo_children():
            widget.destroy()

    # =========================================================================
    #                            WELCOME SCREEN
    # =========================================================================

    def show_welcome_screen(self):
        self.clear_container()
        self.current_user = None
        self.current_role = None
        self.status_user_label.config(text="Role: Guest")
        self.set_status("Welcome to Library Management System. Please select your portal.")

        main_frame = tk.Frame(self.container, bg="#F1F5F9")
        main_frame.place(relx=0.5, rely=0.5, anchor="center")

        # Welcome Card
        card = tk.Frame(main_frame, bg="#FFFFFF", padx=50, pady=40, relief="flat", highlightbackground="#CBD5E1", highlightthickness=1)
        card.pack()

        welcome_title = tk.Label(
            card,
            text="Welcome to the Library Portal",
            font=("Segoe UI", 20, "bold"),
            bg="#FFFFFF",
            fg="#1E293B"
        )
        welcome_title.pack(pady=(0, 6))

        welcome_sub = tk.Label(
            card,
            text="Please choose your role to sign in or register",
            font=("Segoe UI", 11),
            bg="#FFFFFF",
            fg="#64748B"
        )
        welcome_sub.pack(pady=(0, 30))

        # Portal Selection Buttons
        btn_box = tk.Frame(card, bg="#FFFFFF")
        btn_box.pack(pady=10)

        # Student Portal Card
        student_frame = tk.Frame(btn_box, bg="#EFF6FF", padx=25, pady=25, highlightbackground="#BFDBFE", highlightthickness=1)
        student_frame.grid(row=0, column=0, padx=15)

        tk.Label(student_frame, text="🎓", font=("Segoe UI Emoji", 36), bg="#EFF6FF").pack(pady=(0, 5))
        tk.Label(student_frame, text="Student Portal", font=("Segoe UI", 13, "bold"), bg="#EFF6FF", fg="#1E40AF").pack()
        tk.Label(student_frame, text="Browse books, borrow copies\nand manage return deadlines", font=("Segoe UI", 9), bg="#EFF6FF", fg="#3B82F6").pack(pady=8)
        
        tk.Button(
            student_frame,
            text="Enter as Student",
            font=("Segoe UI", 10, "bold"),
            bg="#2563EB",
            fg="#FFFFFF",
            activebackground="#1D4ED8",
            activeforeground="#FFFFFF",
            relief="flat",
            cursor="hand2",
            padx=16,
            pady=6,
            command=lambda: self.show_auth_screen("student")
        ).pack(pady=(10, 0))

        # Admin / Librarian Portal Card
        admin_frame = tk.Frame(btn_box, bg="#F0FDF4", padx=25, pady=25, highlightbackground="#BBF7D0", highlightthickness=1)
        admin_frame.grid(row=0, column=1, padx=15)

        tk.Label(admin_frame, text="🛡️", font=("Segoe UI Emoji", 36), bg="#F0FDF4").pack(pady=(0, 5))
        tk.Label(admin_frame, text="Admin / Librarian", font=("Segoe UI", 13, "bold"), bg="#F0FDF4", fg="#166534").pack()
        tk.Label(admin_frame, text="Manage inventory, circulation\nrecords, and student accounts", font=("Segoe UI", 9), bg="#F0FDF4", fg="#15803D").pack(pady=8)

        tk.Button(
            admin_frame,
            text="Enter as Librarian",
            font=("Segoe UI", 10, "bold"),
            bg="#16A34A",
            fg="#FFFFFF",
            activebackground="#15803D",
            activeforeground="#FFFFFF",
            relief="flat",
            cursor="hand2",
            padx=16,
            pady=6,
            command=lambda: self.show_auth_screen("admin")
        ).pack(pady=(10, 0))

        # Quick DB switcher note
        hint_label = tk.Label(
            card,
            text=f"Database active: {db.active_status} (Click '⚙️ DB Settings' above to change)",
            font=("Segoe UI", 9, "italic"),
            bg="#FFFFFF",
            fg="#94A3B8"
        )
        hint_label.pack(pady=(25, 0))

    # =========================================================================
    #                       AUTHENTICATION SCREEN
    # =========================================================================

    def show_auth_screen(self, role):
        self.clear_container()
        role_title = "Student" if role == "student" else "Admin / Librarian"
        self.set_status(f"{role_title} Authentication Portal")

        # Top Bar with Back Button
        nav_frame = tk.Frame(self.container, bg="#F1F5F9")
        nav_frame.pack(fill="x", padx=30, pady=(15, 0))

        back_btn = tk.Button(
            nav_frame,
            text="← Back to Role Selection",
            font=("Segoe UI", 9, "bold"),
            bg="#E2E8F0",
            fg="#334155",
            relief="flat",
            cursor="hand2",
            padx=10,
            pady=4,
            command=self.show_welcome_screen
        )
        back_btn.pack(side="left")

        # Center Card
        center_frame = tk.Frame(self.container, bg="#F1F5F9")
        center_frame.pack(expand=True, fill="both")

        card = tk.Frame(center_frame, bg="#FFFFFF", padx=40, pady=30, relief="flat", highlightbackground="#CBD5E1", highlightthickness=1)
        card.place(relx=0.5, rely=0.48, anchor="center")

        header_icon = "🎓" if role == "student" else "🛡️"
        tk.Label(card, text=f"{header_icon} {role_title} Portal", font=("Segoe UI", 16, "bold"), bg="#FFFFFF", fg="#1E293B").pack(pady=(0, 15))

        # Notebook for Login and Register tabs
        auth_notebook = ttk.Notebook(card)
        auth_notebook.pack(fill="both", expand=True)

        # --- Tab 1: Login ---
        login_tab = tk.Frame(auth_notebook, bg="#FFFFFF", padx=25, pady=25)
        auth_notebook.add(login_tab, text="  Sign In  ")

        tk.Label(login_tab, text=f"Enter your credentials to access the system", font=("Segoe UI", 9), bg="#FFFFFF", fg="#64748B").grid(row=0, column=0, columnspan=2, pady=(0, 15), sticky="w")

        id_text = "Student ID / Username:" if role == "student" else "Admin Username:"
        tk.Label(login_tab, text=id_text, font=("Segoe UI", 10, "bold"), bg="#FFFFFF", fg="#334155").grid(row=1, column=0, sticky="w", pady=6)
        login_user_entry = ttk.Entry(login_tab, width=28, font=("Segoe UI", 10))
        login_user_entry.grid(row=1, column=1, sticky="w", padx=10, pady=6)
        login_user_entry.focus()

        tk.Label(login_tab, text="Password:", font=("Segoe UI", 10, "bold"), bg="#FFFFFF", fg="#334155").grid(row=2, column=0, sticky="w", pady=6)
        login_pwd_entry = ttk.Entry(login_tab, width=28, font=("Segoe UI", 10), show="*")
        login_pwd_entry.grid(row=2, column=1, sticky="w", padx=10, pady=6)

        show_pwd_var = tk.BooleanVar(value=False)
        def toggle_login_pwd():
            login_pwd_entry.config(show="" if show_pwd_var.get() else "*")
        show_check = tk.Checkbutton(login_tab, text="Show password", variable=show_pwd_var, command=toggle_login_pwd, bg="#FFFFFF", fg="#64748B", font=("Segoe UI", 8), activebackground="#FFFFFF")
        show_check.grid(row=3, column=1, sticky="w", padx=10)

        def do_login():
            username = login_user_entry.get().strip()
            password = login_pwd_entry.get()

            if not username or not password:
                messagebox.showerror("Login Error", "Please fill in both Username and Password.")
                return

            user_row = db.get_user(username)
            if not user_row:
                messagebox.showerror("Login Error", "Account does not exist. Please register first.")
                return

            # Check role & password
            db_id, db_user, db_pass, db_role = user_row[0], user_row[1], user_row[2], user_row[3]
            if db_role != role:
                messagebox.showerror("Access Denied", f"This account is registered as '{db_role}', not '{role}'.")
                return

            if db_pass != password:
                messagebox.showerror("Login Error", "Invalid password. Please try again.")
                return

            # Success
            self.current_user = username
            self.current_role = role
            self.status_user_label.config(text=f"User: {username} ({role})")

            if role == "student":
                self.show_student_dashboard()
            else:
                self.show_admin_dashboard()

        login_pwd_entry.bind("<Return>", lambda e: do_login())
        login_user_entry.bind("<Return>", lambda e: do_login())

        login_btn = tk.Button(
            login_tab,
            text="Sign In",
            font=("Segoe UI", 10, "bold"),
            bg="#2563EB",
            fg="#FFFFFF",
            relief="flat",
            cursor="hand2",
            padx=20,
            pady=6,
            command=do_login
        )
        login_btn.grid(row=4, column=0, columnspan=2, pady=(20, 0))

        if role == "admin":
            admin_note = tk.Label(login_tab, text="Default Admin: admin | admin123", font=("Segoe UI", 8, "italic"), bg="#FFFFFF", fg="#94A3B8")
            admin_note.grid(row=5, column=0, columnspan=2, pady=(10, 0))

        # --- Tab 2: Register ---
        reg_tab = tk.Frame(auth_notebook, bg="#FFFFFF", padx=25, pady=25)
        auth_notebook.add(reg_tab, text="  Create Account  ")

        tk.Label(reg_tab, text=f"Create a new {role} account", font=("Segoe UI", 9), bg="#FFFFFF", fg="#64748B").grid(row=0, column=0, columnspan=2, pady=(0, 15), sticky="w")

        tk.Label(reg_tab, text=id_text, font=("Segoe UI", 10, "bold"), bg="#FFFFFF", fg="#334155").grid(row=1, column=0, sticky="w", pady=6)
        reg_user_entry = ttk.Entry(reg_tab, width=28, font=("Segoe UI", 10))
        reg_user_entry.grid(row=1, column=1, sticky="w", padx=10, pady=6)

        tk.Label(reg_tab, text="Create Password:", font=("Segoe UI", 10, "bold"), bg="#FFFFFF", fg="#334155").grid(row=2, column=0, sticky="w", pady=6)
        reg_pwd_entry = ttk.Entry(reg_tab, width=28, font=("Segoe UI", 10), show="*")
        reg_pwd_entry.grid(row=2, column=1, sticky="w", padx=10, pady=6)

        tk.Label(reg_tab, text="Confirm Password:", font=("Segoe UI", 10, "bold"), bg="#FFFFFF", fg="#334155").grid(row=3, column=0, sticky="w", pady=6)
        reg_confirm_entry = ttk.Entry(reg_tab, width=28, font=("Segoe UI", 10), show="*")
        reg_confirm_entry.grid(row=3, column=1, sticky="w", padx=10, pady=6)

        def do_register():
            new_u = reg_user_entry.get().strip()
            new_p = reg_pwd_entry.get()
            conf_p = reg_confirm_entry.get()

            if not new_u or not new_p:
                messagebox.showerror("Registration Error", "All fields are required.")
                return

            if new_p != conf_p:
                messagebox.showerror("Registration Error", "Passwords do not match!")
                return

            success, msg = db.add_user(new_u, new_p, role)
            if success:
                messagebox.showinfo("Registration Successful", f"Account '{new_u}' created successfully!\nYou can now sign in.")
                reg_user_entry.delete(0, tk.END)
                reg_pwd_entry.delete(0, tk.END)
                reg_confirm_entry.delete(0, tk.END)
                auth_notebook.select(0)
                login_user_entry.delete(0, tk.END)
                login_user_entry.insert(0, new_u)
                login_pwd_entry.focus()
            else:
                messagebox.showerror("Registration Error", msg)

        reg_btn = tk.Button(
            reg_tab,
            text="Register Account",
            font=("Segoe UI", 10, "bold"),
            bg="#16A34A",
            fg="#FFFFFF",
            relief="flat",
            cursor="hand2",
            padx=20,
            pady=6,
            command=do_register
        )
        reg_btn.grid(row=4, column=0, columnspan=2, pady=(20, 0))

    # =========================================================================
    #                       ADMIN / LIBRARIAN DASHBOARD
    # =========================================================================

    def show_admin_dashboard(self):
        self.clear_container()
        self.set_status(f"Admin Dashboard | Active Session: {self.current_user}")

        # Top Bar
        top_bar = tk.Frame(self.container, bg="#F1F5F9")
        top_bar.pack(fill="x", padx=25, pady=(15, 10))

        welcome_lbl = tk.Label(
            top_bar,
            text=f"🛡️ Librarian Dashboard  |  Welcome, {self.current_user}",
            font=("Segoe UI", 14, "bold"),
            bg="#F1F5F9",
            fg="#1E293B"
        )
        welcome_lbl.pack(side="left")

        logout_btn = tk.Button(
            top_bar,
            text="🚪 Logout",
            font=("Segoe UI", 9, "bold"),
            bg="#EF4444",
            fg="#FFFFFF",
            relief="flat",
            cursor="hand2",
            padx=12,
            pady=4,
            command=self.show_welcome_screen
        )
        logout_btn.pack(side="right")

        # KPI Metric Cards Bar
        stats = db.get_stats()
        kpi_bar = tk.Frame(self.container, bg="#F1F5F9")
        kpi_bar.pack(fill="x", padx=25, pady=(0, 10))

        def create_kpi_card(parent, title, val, icon, color):
            card = tk.Frame(parent, bg="#FFFFFF", padx=14, pady=8, highlightbackground="#E2E8F0", highlightthickness=1)
            card.pack(side="left", fill="x", expand=True, padx=4)
            tk.Label(card, text=icon, font=("Segoe UI Emoji", 16), bg="#FFFFFF").pack(side="left", padx=(0, 10))
            box = tk.Frame(card, bg="#FFFFFF")
            box.pack(side="left")
            tk.Label(box, text=title, font=("Segoe UI", 8), bg="#FFFFFF", fg="#64748B").pack(anchor="w")
            tk.Label(box, text=str(val), font=("Segoe UI", 13, "bold"), bg="#FFFFFF", fg=color).pack(anchor="w")

        create_kpi_card(kpi_bar, "Total Titles", stats["total_titles"], "📚", "#1E3A8A")
        create_kpi_card(kpi_bar, "Available Copies", stats["avail_copies"], "✅", "#16A34A")
        create_kpi_card(kpi_bar, "Active Loans", stats["active_loans"], "⏳", "#D97706")
        create_kpi_card(kpi_bar, "Registered Students", stats["students_count"], "🎓", "#2563EB")

        # Admin Tabs
        notebook = ttk.Notebook(self.container)
        notebook.pack(fill="both", expand=True, padx=25, pady=(0, 15))

        # --- Tab 1: Book Inventory ---
        inv_tab = tk.Frame(notebook, bg="#FFFFFF")
        notebook.add(inv_tab, text="  📚 Book Catalog & Inventory  ")
        self.setup_admin_inventory_tab(inv_tab)

        # --- Tab 2: Circulation & Borrow Records ---
        circ_tab = tk.Frame(notebook, bg="#FFFFFF")
        notebook.add(circ_tab, text="  📋 Circulation & Borrow Records  ")
        self.setup_admin_circulation_tab(circ_tab)

        # --- Tab 3: Registered Users ---
        users_tab = tk.Frame(notebook, bg="#FFFFFF")
        notebook.add(users_tab, text="  👥 Registered Users  ")
        self.setup_admin_users_tab(users_tab)

    def setup_admin_inventory_tab(self, parent):
        # Search & Toolbar frame
        bar = tk.Frame(parent, bg="#FFFFFF", padx=15, pady=12)
        bar.pack(fill="x")

        tk.Label(bar, text="Search Books:", font=("Segoe UI", 10, "bold"), bg="#FFFFFF", fg="#334155").pack(side="left", padx=(0, 8))
        search_entry = ttk.Entry(bar, width=28, font=("Segoe UI", 10))
        search_entry.pack(side="left", padx=(0, 8))

        def perform_search():
            term = search_entry.get().strip()
            rows = db.get_all_books(term)
            self.populate_admin_books_table(tree, rows)
            self.set_status(f"Found {len(rows)} book(s) matching '{term}'")

        def reset_search():
            search_entry.delete(0, tk.END)
            rows = db.get_all_books("")
            self.populate_admin_books_table(tree, rows)
            self.set_status(f"Loaded all {len(rows)} books.")

        search_btn = tk.Button(bar, text="🔍 Search", font=("Segoe UI", 9), bg="#2563EB", fg="#FFFFFF", relief="flat", cursor="hand2", padx=10, pady=3, command=perform_search)
        search_btn.pack(side="left", padx=4)

        reset_btn = tk.Button(bar, text="🔄 Reset", font=("Segoe UI", 9), bg="#E2E8F0", fg="#334155", relief="flat", cursor="hand2", padx=10, pady=3, command=reset_search)
        reset_btn.pack(side="left", padx=4)

        search_entry.bind("<Return>", lambda e: perform_search())

        # Action Buttons on Right
        del_btn = tk.Button(bar, text="🗑️ Delete Book", font=("Segoe UI", 9, "bold"), bg="#DC2626", fg="#FFFFFF", relief="flat", cursor="hand2", padx=10, pady=3, command=lambda: self.admin_delete_book(tree))
        del_btn.pack(side="right", padx=4)

        edit_btn = tk.Button(bar, text="✏️ Edit Book", font=("Segoe UI", 9, "bold"), bg="#D97706", fg="#FFFFFF", relief="flat", cursor="hand2", padx=10, pady=3, command=lambda: self.admin_edit_book(tree))
        edit_btn.pack(side="right", padx=4)

        add_btn = tk.Button(bar, text="➕ Add New Book", font=("Segoe UI", 9, "bold"), bg="#16A34A", fg="#FFFFFF", relief="flat", cursor="hand2", padx=10, pady=3, command=lambda: self.admin_add_book_dialog(tree))
        add_btn.pack(side="right", padx=4)

        # Treeview Table
        table_frame = tk.Frame(parent, bg="#FFFFFF", padx=15, pady=10)
        table_frame.pack(fill="both", expand=True)

        columns = ("id", "title", "author", "genre", "available", "total", "added")
        tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse")

        tree.heading("id", text="ID")
        tree.heading("title", text="Book Title")
        tree.heading("author", text="Author")
        tree.heading("genre", text="Genre")
        tree.heading("available", text="Available Copies")
        tree.heading("total", text="Total Copies")
        tree.heading("added", text="Date Added")

        tree.column("id", width=50, anchor="center")
        tree.column("title", width=250, anchor="w")
        tree.column("author", width=180, anchor="w")
        tree.column("genre", width=120, anchor="w")
        tree.column("available", width=110, anchor="center")
        tree.column("total", width=100, anchor="center")
        tree.column("added", width=140, anchor="center")

        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.enable_treeview_sorting(tree)
        self.enable_treeview_sorting(tree)

        # Initial populate
        rows = db.get_all_books("")
        self.populate_admin_books_table(tree, rows)

    def populate_admin_books_table(self, tree, rows):
        tree.delete(*tree.get_children())
        for r in rows:
            # (id, title, author, genre, available_copies, total_copies, added_date)
            added_str = str(r[6])[:19] if r[6] else "N/A"
            tree.insert("", "end", values=(r[0], r[1], r[2], r[3], r[4], r[5], added_str))

    def admin_add_book_dialog(self, tree):
        dialog = tk.Toplevel(self)
        dialog.title("Add New Book")
        dialog.geometry("420x340")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()

        card = tk.Frame(dialog, bg="#FFFFFF", padx=25, pady=20)
        card.pack(fill="both", expand=True)

        tk.Label(card, text="Add Book to Inventory", font=("Segoe UI", 12, "bold"), bg="#FFFFFF", fg="#1E293B").grid(row=0, column=0, columnspan=2, pady=(0, 15), sticky="w")

        tk.Label(card, text="Book Title *", font=("Segoe UI", 9, "bold"), bg="#FFFFFF", fg="#334155").grid(row=1, column=0, sticky="w", pady=6)
        title_entry = ttk.Entry(card, width=28, font=("Segoe UI", 10))
        title_entry.grid(row=1, column=1, sticky="w", pady=6)
        title_entry.focus()

        tk.Label(card, text="Author", font=("Segoe UI", 9, "bold"), bg="#FFFFFF", fg="#334155").grid(row=2, column=0, sticky="w", pady=6)
        author_entry = ttk.Entry(card, width=28, font=("Segoe UI", 10))
        author_entry.grid(row=2, column=1, sticky="w", pady=6)
        author_entry.insert(0, "Unknown")

        tk.Label(card, text="Genre / Category", font=("Segoe UI", 9, "bold"), bg="#FFFFFF", fg="#334155").grid(row=3, column=0, sticky="w", pady=6)
        genre_entry = ttk.Entry(card, width=28, font=("Segoe UI", 10))
        genre_entry.grid(row=3, column=1, sticky="w", pady=6)
        genre_entry.insert(0, "General")

        tk.Label(card, text="Total Copies", font=("Segoe UI", 9, "bold"), bg="#FFFFFF", fg="#334155").grid(row=4, column=0, sticky="w", pady=6)
        copies_entry = ttk.Entry(card, width=10, font=("Segoe UI", 10))
        copies_entry.grid(row=4, column=1, sticky="w", pady=6)
        copies_entry.insert(0, "3")

        def save():
            t = title_entry.get().strip()
            a = author_entry.get().strip() or "Unknown"
            g = genre_entry.get().strip() or "General"
            try:
                c = int(copies_entry.get().strip())
                if c <= 0:
                    raise ValueError
            except ValueError:
                messagebox.showerror("Validation Error", "Copies must be a positive integer.", parent=dialog)
                return

            if not t:
                messagebox.showerror("Validation Error", "Book Title cannot be empty.", parent=dialog)
                return

            success, msg = db.add_book(t, a, g, c)
            if success:
                messagebox.showinfo("Success", msg, parent=dialog)
                dialog.destroy()
                self.populate_admin_books_table(tree, db.get_all_books(""))
            else:
                messagebox.showerror("Error", msg, parent=dialog)

        btn_box = tk.Frame(card, bg="#FFFFFF")
        btn_box.grid(row=5, column=0, columnspan=2, pady=(20, 0))

        tk.Button(btn_box, text="Save Book", font=("Segoe UI", 9, "bold"), bg="#16A34A", fg="#FFFFFF", relief="flat", cursor="hand2", padx=14, pady=5, command=save).pack(side="left", padx=5)
        tk.Button(btn_box, text="Cancel", font=("Segoe UI", 9), bg="#E2E8F0", fg="#334155", relief="flat", cursor="hand2", padx=14, pady=5, command=dialog.destroy).pack(side="left", padx=5)

    def admin_edit_book(self, tree):
        selected = tree.selection()
        if not selected:
            messagebox.showwarning("Selection Required", "Please select a book to edit.")
            return

        item = tree.item(selected[0])
        vals = item["values"]
        book_id, old_title, old_author, old_genre, old_avail, old_total = vals[0], vals[1], vals[2], vals[3], vals[4], vals[5]

        dialog = tk.Toplevel(self)
        dialog.title(f"Edit Book #{book_id}")
        dialog.geometry("420x340")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()

        card = tk.Frame(dialog, bg="#FFFFFF", padx=25, pady=20)
        card.pack(fill="both", expand=True)

        tk.Label(card, text=f"Edit Book Details (ID: {book_id})", font=("Segoe UI", 12, "bold"), bg="#FFFFFF", fg="#1E293B").grid(row=0, column=0, columnspan=2, pady=(0, 15), sticky="w")

        tk.Label(card, text="Book Title", font=("Segoe UI", 9, "bold"), bg="#FFFFFF", fg="#334155").grid(row=1, column=0, sticky="w", pady=6)
        title_entry = ttk.Entry(card, width=28, font=("Segoe UI", 10))
        title_entry.grid(row=1, column=1, sticky="w", pady=6)
        title_entry.insert(0, old_title)

        tk.Label(card, text="Author", font=("Segoe UI", 9, "bold"), bg="#FFFFFF", fg="#334155").grid(row=2, column=0, sticky="w", pady=6)
        author_entry = ttk.Entry(card, width=28, font=("Segoe UI", 10))
        author_entry.grid(row=2, column=1, sticky="w", pady=6)
        author_entry.insert(0, old_author)

        tk.Label(card, text="Genre", font=("Segoe UI", 9, "bold"), bg="#FFFFFF", fg="#334155").grid(row=3, column=0, sticky="w", pady=6)
        genre_entry = ttk.Entry(card, width=28, font=("Segoe UI", 10))
        genre_entry.grid(row=3, column=1, sticky="w", pady=6)
        genre_entry.insert(0, old_genre)

        tk.Label(card, text="Total Copies", font=("Segoe UI", 9, "bold"), bg="#FFFFFF", fg="#334155").grid(row=4, column=0, sticky="w", pady=6)
        copies_entry = ttk.Entry(card, width=10, font=("Segoe UI", 10))
        copies_entry.grid(row=4, column=1, sticky="w", pady=6)
        copies_entry.insert(0, str(old_total))

        def update():
            t = title_entry.get().strip()
            a = author_entry.get().strip() or "Unknown"
            g = genre_entry.get().strip() or "General"
            try:
                c = int(copies_entry.get().strip())
                if c <= 0:
                    raise ValueError
            except ValueError:
                messagebox.showerror("Validation Error", "Total copies must be a positive integer.", parent=dialog)
                return

            if not t:
                messagebox.showerror("Validation Error", "Book Title cannot be empty.", parent=dialog)
                return

            success, msg = db.update_book(book_id, t, a, g, c)
            if success:
                messagebox.showinfo("Success", msg, parent=dialog)
                dialog.destroy()
                self.populate_admin_books_table(tree, db.get_all_books(""))
            else:
                messagebox.showerror("Error", msg, parent=dialog)

        btn_box = tk.Frame(card, bg="#FFFFFF")
        btn_box.grid(row=5, column=0, columnspan=2, pady=(20, 0))

        tk.Button(btn_box, text="Update Book", font=("Segoe UI", 9, "bold"), bg="#D97706", fg="#FFFFFF", relief="flat", cursor="hand2", padx=14, pady=5, command=update).pack(side="left", padx=5)
        tk.Button(btn_box, text="Cancel", font=("Segoe UI", 9), bg="#E2E8F0", fg="#334155", relief="flat", cursor="hand2", padx=14, pady=5, command=dialog.destroy).pack(side="left", padx=5)

    def admin_delete_book(self, tree):
        selected = tree.selection()
        if not selected:
            messagebox.showwarning("Selection Required", "Please select a book to delete.")
            return

        item = tree.item(selected[0])
        vals = item["values"]
        book_id, book_title = vals[0], vals[1]

        confirm = messagebox.askyesno(
            "Confirm Deletion",
            f"Are you sure you want to permanently delete the book:\n\n'{book_title}' (ID: {book_id})?",
            icon="warning"
        )
        if confirm:
            success, msg = db.delete_book(book_id)
            if success:
                messagebox.showinfo("Deleted", msg)
                self.populate_admin_books_table(tree, db.get_all_books(""))
            else:
                messagebox.showerror("Error", msg)

    def setup_admin_circulation_tab(self, parent):
        bar = tk.Frame(parent, bg="#FFFFFF", padx=15, pady=12)
        bar.pack(fill="x")

        tk.Label(bar, text="Search Records:", font=("Segoe UI", 10, "bold"), bg="#FFFFFF", fg="#334155").pack(side="left", padx=(0, 8))
        search_entry = ttk.Entry(bar, width=28, font=("Segoe UI", 10))
        search_entry.pack(side="left", padx=(0, 8))

        def perform_search():
            term = search_entry.get().strip()
            rows = db.get_all_borrow_records(term)
            self.populate_admin_circ_table(tree, rows)
            self.set_status(f"Found {len(rows)} circulation record(s).")

        def reset_search():
            search_entry.delete(0, tk.END)
            rows = db.get_all_borrow_records("")
            self.populate_admin_circ_table(tree, rows)
            self.set_status(f"Loaded all {len(rows)} circulation record(s).")

        search_btn = tk.Button(bar, text="🔍 Search", font=("Segoe UI", 9), bg="#2563EB", fg="#FFFFFF", relief="flat", cursor="hand2", padx=10, pady=3, command=perform_search)
        search_btn.pack(side="left", padx=4)

        reset_btn = tk.Button(bar, text="🔄 Reset", font=("Segoe UI", 9), bg="#E2E8F0", fg="#334155", relief="flat", cursor="hand2", padx=10, pady=3, command=reset_search)
        reset_btn.pack(side="left", padx=4)

        search_entry.bind("<Return>", lambda e: perform_search())

        # Return Action Button
        def mark_returned():
            selected = tree.selection()
            if not selected:
                messagebox.showwarning("Selection Required", "Please select a borrow record to mark as returned.")
                return
            item = tree.item(selected[0])
            vals = item["values"]
            record_id, student, title, status = vals[0], vals[1], vals[2], vals[6]

            if status == "Returned":
                messagebox.showinfo("Info", "This record is already marked as Returned.")
                return

            if messagebox.askyesno("Confirm Return", f"Mark book '{title}' returned by '{student}'?"):
                success, msg = db.return_book(record_id)
                if success:
                    messagebox.showinfo("Success", msg)
                    reset_search()
                else:
                    messagebox.showerror("Error", msg)

        return_btn = tk.Button(bar, text="✅ Mark as Returned", font=("Segoe UI", 9, "bold"), bg="#16A34A", fg="#FFFFFF", relief="flat", cursor="hand2", padx=12, pady=4, command=mark_returned)
        return_btn.pack(side="right", padx=4)

        # Table
        table_frame = tk.Frame(parent, bg="#FFFFFF", padx=15, pady=10)
        table_frame.pack(fill="both", expand=True)

        columns = ("id", "student", "book_title", "borrow_date", "due_date", "return_date", "status")
        tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse")

        tree.heading("id", text="Record ID")
        tree.heading("student", text="Student ID")
        tree.heading("book_title", text="Book Title")
        tree.heading("borrow_date", text="Borrow Date")
        tree.heading("due_date", text="Due Date")
        tree.heading("return_date", text="Return Date")
        tree.heading("status", text="Status")

        tree.column("id", width=70, anchor="center")
        tree.column("student", width=140, anchor="w")
        tree.column("book_title", width=250, anchor="w")
        tree.column("borrow_date", width=110, anchor="center")
        tree.column("due_date", width=110, anchor="center")
        tree.column("return_date", width=110, anchor="center")
        tree.column("status", width=100, anchor="center")

        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.enable_treeview_sorting(tree)
        self.enable_treeview_sorting(tree)

        self.populate_admin_circ_table(tree, db.get_all_borrow_records(""))

    def populate_admin_circ_table(self, tree, rows):
        tree.delete(*tree.get_children())
        for r in rows:
            # (id, student_username, book_title, borrow_date, due_date, return_date, status)
            ret_date = r[5] if r[5] else "--"
            status = r[6]
            tree.insert("", "end", values=(r[0], r[1], r[2], r[3], r[4], ret_date, status))

    def setup_admin_users_tab(self, parent):
        bar = tk.Frame(parent, bg="#FFFFFF", padx=15, pady=12)
        bar.pack(fill="x")

        tk.Label(bar, text="Registered System Accounts", font=("Segoe UI", 12, "bold"), bg="#FFFFFF", fg="#1E293B").pack(side="left")

        def refresh():
            rows = db.get_all_users()
            tree.delete(*tree.get_children())
            for r in rows:
                c_date = str(r[3])[:19] if r[3] else "N/A"
                tree.insert("", "end", values=(r[0], r[1], r[2].capitalize(), c_date))
            self.set_status(f"Loaded {len(rows)} registered accounts.")

        refresh_btn = tk.Button(bar, text="🔄 Refresh", font=("Segoe UI", 9), bg="#E2E8F0", fg="#334155", relief="flat", cursor="hand2", padx=10, pady=3, command=refresh)
        refresh_btn.pack(side="right")

        table_frame = tk.Frame(parent, bg="#FFFFFF", padx=15, pady=10)
        table_frame.pack(fill="both", expand=True)

        columns = ("id", "username", "role", "created_at")
        tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse")

        tree.heading("id", text="User ID")
        tree.heading("username", text="Username / School ID")
        tree.heading("role", text="System Role")
        tree.heading("created_at", text="Registration Date")

        tree.column("id", width=80, anchor="center")
        tree.column("username", width=250, anchor="w")
        tree.column("role", width=150, anchor="center")
        tree.column("created_at", width=200, anchor="center")

        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.enable_treeview_sorting(tree)
        self.enable_treeview_sorting(tree)

        refresh()

    # =========================================================================
    #                         STUDENT DASHBOARD
    # =========================================================================

    def show_student_dashboard(self):
        self.clear_container()
        self.set_status(f"Student Dashboard | Active: {self.current_user}")

        top_bar = tk.Frame(self.container, bg="#F1F5F9")
        top_bar.pack(fill="x", padx=25, pady=(15, 10))

        welcome_lbl = tk.Label(
            top_bar,
            text=f"🎓 Student Portal  |  Welcome, {self.current_user}",
            font=("Segoe UI", 14, "bold"),
            bg="#F1F5F9",
            fg="#1E293B"
        )
        welcome_lbl.pack(side="left")

        logout_btn = tk.Button(
            top_bar,
            text="🚪 Logout",
            font=("Segoe UI", 9, "bold"),
            bg="#EF4444",
            fg="#FFFFFF",
            relief="flat",
            cursor="hand2",
            padx=12,
            pady=4,
            command=self.show_welcome_screen
        )
        logout_btn.pack(side="right")

        # Student Notebook
        notebook = ttk.Notebook(self.container)
        notebook.pack(fill="both", expand=True, padx=25, pady=(0, 15))

        # --- Tab 1: Browse & Borrow Books ---
        catalog_tab = tk.Frame(notebook, bg="#FFFFFF")
        notebook.add(catalog_tab, text="  📖 Browse & Borrow Books  ")
        self.setup_student_catalog_tab(catalog_tab)

        # --- Tab 2: My Borrowed Books ---
        my_books_tab = tk.Frame(notebook, bg="#FFFFFF")
        notebook.add(my_books_tab, text="  🔖 My Borrowed Books  ")
        self.setup_student_my_books_tab(my_books_tab)

    def setup_student_catalog_tab(self, parent):
        # Search Bar
        bar = tk.Frame(parent, bg="#FFFFFF", padx=15, pady=12)
        bar.pack(fill="x")

        tk.Label(bar, text="Search Catalog:", font=("Segoe UI", 10, "bold"), bg="#FFFFFF", fg="#334155").pack(side="left", padx=(0, 8))
        search_entry = ttk.Entry(bar, width=32, font=("Segoe UI", 10))
        search_entry.pack(side="left", padx=(0, 8))

        def perform_search():
            term = search_entry.get().strip()
            rows = db.get_all_books(term)
            self.populate_student_catalog(tree, rows)
            self.set_status(f"Found {len(rows)} book(s) matching '{term}'")

        def reset_search():
            search_entry.delete(0, tk.END)
            rows = db.get_all_books("")
            self.populate_student_catalog(tree, rows)
            self.set_status(f"Loaded all {len(rows)} books.")

        search_btn = tk.Button(bar, text="🔍 Search", font=("Segoe UI", 9), bg="#2563EB", fg="#FFFFFF", relief="flat", cursor="hand2", padx=10, pady=3, command=perform_search)
        search_btn.pack(side="left", padx=4)

        reset_btn = tk.Button(bar, text="🔄 Show All", font=("Segoe UI", 9), bg="#E2E8F0", fg="#334155", relief="flat", cursor="hand2", padx=10, pady=3, command=reset_search)
        reset_btn.pack(side="left", padx=4)

        search_entry.bind("<Return>", lambda e: perform_search())

        # Main Split Content: Table on Top/Left, Borrow Panel below
        content_box = tk.Frame(parent, bg="#FFFFFF", padx=15, pady=5)
        content_box.pack(fill="both", expand=True)

        table_frame = tk.Frame(content_box, bg="#FFFFFF")
        table_frame.pack(fill="both", expand=True)

        columns = ("id", "title", "author", "genre", "available", "status")
        tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse")

        tree.heading("id", text="ID")
        tree.heading("title", text="Book Title")
        tree.heading("author", text="Author")
        tree.heading("genre", text="Genre")
        tree.heading("available", text="Available Copies")
        tree.heading("status", text="Availability")

        tree.column("id", width=50, anchor="center")
        tree.column("title", width=280, anchor="w")
        tree.column("author", width=180, anchor="w")
        tree.column("genre", width=140, anchor="w")
        tree.column("available", width=120, anchor="center")
        tree.column("status", width=120, anchor="center")

        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.enable_treeview_sorting(tree)

        # Borrow Action Section at Bottom
        borrow_panel = tk.Frame(content_box, bg="#EFF6FF", padx=20, pady=15, highlightbackground="#BFDBFE", highlightthickness=1)
        borrow_panel.pack(fill="x", pady=(10, 5))

        selected_lbl = tk.Label(borrow_panel, text="No book selected. Select a book from the list above.", font=("Segoe UI", 10, "bold"), bg="#EFF6FF", fg="#1E40AF")
        selected_lbl.grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 10))

        tk.Label(borrow_panel, text="Borrow Date (DD-MM-YYYY):", font=("Segoe UI", 9, "bold"), bg="#EFF6FF", fg="#1E3A8A").grid(row=1, column=0, sticky="w", padx=(0, 6))
        
        today_str = datetime.date.today().strftime("%d-%m-%Y")
        due_str = (datetime.date.today() + datetime.timedelta(days=7)).strftime("%d-%m-%Y")

        date_entry = ttk.Entry(borrow_panel, width=14, font=("Segoe UI", 9))
        date_entry.grid(row=1, column=1, sticky="w")
        date_entry.insert(0, today_str)

        due_date_lbl = tk.Label(borrow_panel, text=f"Due Date: {due_str} (7 days)", font=("Segoe UI", 9, "italic"), bg="#EFF6FF", fg="#059669")
        due_date_lbl.grid(row=1, column=2, sticky="w", padx=15)

        def update_due_date(*args):
            d_val = date_entry.get().strip()
            try:
                dt = datetime.datetime.strptime(d_val, "%d-%m-%Y")
                due = dt + datetime.timedelta(days=7)
                due_date_lbl.config(text=f"Due Date: {due.strftime('%d-%m-%Y')} (7 days)", fg="#059669")
            except ValueError:
                due_date_lbl.config(text="Invalid date format", fg="#DC2626")

        date_entry.bind("<KeyRelease>", update_due_date)

        def on_tree_select(event):
            sel = tree.selection()
            if sel:
                item = tree.item(sel[0])
                vals = item["values"]
                b_id, b_title, b_avail = vals[0], vals[1], vals[4]
                status_txt = "In Stock" if b_avail > 0 else "Out of Stock"
                selected_lbl.config(text=f"Selected: '{b_title}' (ID: {b_id}) — {status_txt} ({b_avail} copies available)")

        tree.bind("<<TreeviewSelect>>", on_tree_select)

        def do_borrow():
            sel = tree.selection()
            if not sel:
                messagebox.showwarning("Select Book", "Please select a book from the table above to borrow.")
                return

            item = tree.item(sel[0])
            vals = item["values"]
            b_id, b_title, b_avail = vals[0], vals[1], vals[4]

            if b_avail <= 0:
                messagebox.showerror("Unavailable", f"Sorry, '{b_title}' has no copies currently available.")
                return

            b_date = date_entry.get().strip()

            confirm = messagebox.askyesno(
                "Confirm Borrowing",
                f"Confirm borrowing book:\n\n'{b_title}'\n\nStudent: {self.current_user}\nBorrow Date: {b_date}"
            )
            if not confirm:
                return

            success, msg = db.borrow_book(self.current_user, b_id, b_date)
            if success:
                messagebox.showinfo("Borrow Successful!", msg)
                # Refresh table
                self.populate_student_catalog(tree, db.get_all_books(""))
                selected_lbl.config(text="No book selected. Select a book from the list above.")
            else:
                messagebox.showerror("Error", msg)

        borrow_btn = tk.Button(
            borrow_panel,
            text="📥 Borrow This Book",
            font=("Segoe UI", 10, "bold"),
            bg="#2563EB",
            fg="#FFFFFF",
            relief="flat",
            cursor="hand2",
            padx=16,
            pady=5,
            command=do_borrow
        )
        borrow_btn.grid(row=1, column=3, sticky="e", padx=20)

        # Initial populate
        self.populate_student_catalog(tree, db.get_all_books(""))

    def populate_student_catalog(self, tree, rows):
        tree.delete(*tree.get_children())
        for r in rows:
            avail = r[4]
            status = "✅ Available" if avail > 0 else "❌ Checked Out"
            tree.insert("", "end", values=(r[0], r[1], r[2], r[3], avail, status))

    def setup_student_my_books_tab(self, parent):
        bar = tk.Frame(parent, bg="#FFFFFF", padx=15, pady=12)
        bar.pack(fill="x")

        tk.Label(bar, text=f"Borrowing History for {self.current_user}", font=("Segoe UI", 12, "bold"), bg="#FFFFFF", fg="#1E293B").pack(side="left")

        def refresh():
            rows = db.get_student_borrow_records(self.current_user)
            tree.delete(*tree.get_children())
            for r in rows:
                ret_d = r[5] if r[5] else "--"
                tree.insert("", "end", values=(r[0], r[1], r[2], r[3], r[4], ret_d))
            self.set_status(f"Found {len(rows)} borrowing record(s).")

        refresh_btn = tk.Button(bar, text="🔄 Refresh", font=("Segoe UI", 9), bg="#E2E8F0", fg="#334155", relief="flat", cursor="hand2", padx=10, pady=3, command=refresh)
        refresh_btn.pack(side="right", padx=5)

        def return_selected():
            sel = tree.selection()
            if not sel:
                messagebox.showwarning("Select Record", "Please select a book record to return.")
                return

            item = tree.item(sel[0])
            vals = item["values"]
            record_id, book_title, status = vals[0], vals[1], vals[4]

            if status == "Returned":
                messagebox.showinfo("Already Returned", f"'{book_title}' has already been returned.")
                return

            if messagebox.askyesno("Confirm Return", f"Are you sure you want to return:\n\n'{book_title}'?"):
                success, msg = db.return_book(record_id)
                if success:
                    messagebox.showinfo("Return Completed", msg)
                    refresh()
                else:
                    messagebox.showerror("Error", msg)

        return_btn = tk.Button(bar, text="📤 Return Selected Book", font=("Segoe UI", 9, "bold"), bg="#16A34A", fg="#FFFFFF", relief="flat", cursor="hand2", padx=12, pady=4, command=return_selected)
        return_btn.pack(side="right", padx=5)

        # Table
        table_frame = tk.Frame(parent, bg="#FFFFFF", padx=15, pady=10)
        table_frame.pack(fill="both", expand=True)

        columns = ("id", "book_title", "borrow_date", "due_date", "status", "return_date")
        tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse")

        tree.heading("id", text="Record ID")
        tree.heading("book_title", text="Book Title")
        tree.heading("borrow_date", text="Borrow Date")
        tree.heading("due_date", text="Due Date (Hand-in by)")
        tree.heading("status", text="Status")
        tree.heading("return_date", text="Date Returned")

        tree.column("id", width=80, anchor="center")
        tree.column("book_title", width=300, anchor="w")
        tree.column("borrow_date", width=130, anchor="center")
        tree.column("due_date", width=160, anchor="center")
        tree.column("status", width=110, anchor="center")
        tree.column("return_date", width=130, anchor="center")

        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.enable_treeview_sorting(tree)
        self.enable_treeview_sorting(tree)

        refresh()

    # =========================================================================
    #                   DATABASE SETTINGS MODAL DIALOG
    # =========================================================================

    def open_db_settings_dialog(self):
        dialog = tk.Toplevel(self)
        dialog.title("Database Connection Settings")
        dialog.geometry("520x480")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()

        card = tk.Frame(dialog, bg="#FFFFFF", padx=25, pady=20)
        card.pack(fill="both", expand=True)

        tk.Label(card, text="⚙️ Database Engine & Configuration", font=("Segoe UI", 13, "bold"), bg="#FFFFFF", fg="#1E293B").pack(anchor="w", pady=(0, 5))
        tk.Label(
            card,
            text="Choose your preferred database. MySQL provides centralized storage,\nwhile SQLite runs locally with zero setup on any computer.",
            font=("Segoe UI", 9),
            bg="#FFFFFF",
            fg="#64748B"
        ).pack(anchor="w", pady=(0, 15))

        # Mode Selection Radio Buttons
        mode_var = tk.StringVar(value=db.db_type)

        radio_box = tk.LabelFrame(card, text=" Select Database Engine ", font=("Segoe UI", 9, "bold"), bg="#FFFFFF", fg="#334155", padx=10, pady=8)
        radio_box.pack(fill="x", pady=(0, 12))

        mysql_rb = tk.Radiobutton(
            radio_box,
            text="MySQL Server (Centralized Database)",
            variable=mode_var,
            value="mysql",
            bg="#FFFFFF",
            font=("Segoe UI", 9, "bold"),
            activebackground="#FFFFFF"
        )
        mysql_rb.pack(anchor="w", pady=2)

        sqlite_rb = tk.Radiobutton(
            radio_box,
            text="Local SQLite Database (Zero Setup - Runs Anywhere Without MySQL)",
            variable=mode_var,
            value="sqlite",
            bg="#FFFFFF",
            font=("Segoe UI", 9, "bold"),
            activebackground="#FFFFFF"
        )
        sqlite_rb.pack(anchor="w", pady=2)

        # MySQL Fields Frame
        mysql_frame = tk.LabelFrame(card, text=" MySQL Connection Parameters ", font=("Segoe UI", 9, "bold"), bg="#FFFFFF", fg="#334155", padx=12, pady=10)
        mysql_frame.pack(fill="x", pady=(0, 12))

        cfg = db.config
        tk.Label(mysql_frame, text="Host:", font=("Segoe UI", 9), bg="#FFFFFF").grid(row=0, column=0, sticky="w", pady=4)
        host_entry = ttk.Entry(mysql_frame, width=22)
        host_entry.grid(row=0, column=1, sticky="w", padx=6, pady=4)
        host_entry.insert(0, cfg.get("host", "localhost"))

        tk.Label(mysql_frame, text="Port:", font=("Segoe UI", 9), bg="#FFFFFF").grid(row=0, column=2, sticky="w", padx=(10, 0), pady=4)
        port_entry = ttk.Entry(mysql_frame, width=8)
        port_entry.grid(row=0, column=3, sticky="w", padx=6, pady=4)
        port_entry.insert(0, str(cfg.get("port", 3306)))

        tk.Label(mysql_frame, text="Username:", font=("Segoe UI", 9), bg="#FFFFFF").grid(row=1, column=0, sticky="w", pady=4)
        user_entry = ttk.Entry(mysql_frame, width=22)
        user_entry.grid(row=1, column=1, sticky="w", padx=6, pady=4)
        user_entry.insert(0, cfg.get("user", "root"))

        tk.Label(mysql_frame, text="Password:", font=("Segoe UI", 9), bg="#FFFFFF").grid(row=2, column=0, sticky="w", pady=4)
        pwd_entry = ttk.Entry(mysql_frame, width=22, show="*")
        pwd_entry.grid(row=2, column=1, sticky="w", padx=6, pady=4)
        pwd_entry.insert(0, cfg.get("password", ""))

        tk.Label(mysql_frame, text="Database:", font=("Segoe UI", 9), bg="#FFFFFF").grid(row=3, column=0, sticky="w", pady=4)
        db_entry = ttk.Entry(mysql_frame, width=22)
        db_entry.grid(row=3, column=1, sticky="w", padx=6, pady=4)
        db_entry.insert(0, cfg.get("database", "library_db"))

        def toggle_fields():
            state = "normal" if mode_var.get() == "mysql" else "disabled"
            for child in mysql_frame.winfo_children():
                if isinstance(child, (ttk.Entry, tk.Button, tk.Label)):
                    try:
                        child.configure(state=state)
                    except Exception:
                        pass

        mysql_rb.config(command=toggle_fields)
        sqlite_rb.config(command=toggle_fields)
        toggle_fields()

        # Feedback Label
        result_lbl = tk.Label(card, text="", font=("Segoe UI", 9), bg="#FFFFFF")
        result_lbl.pack(pady=4)

        # Test Connection Action
        def test_conn():
            if mode_var.get() == "sqlite":
                result_lbl.config(text="SQLite mode is always available (no server needed).", fg="#059669")
                return

            h = host_entry.get().strip()
            p = port_entry.get().strip()
            u = user_entry.get().strip()
            pwd = pwd_entry.get()
            d = db_entry.get().strip()

            result_lbl.config(text="Testing MySQL connection...", fg="#2563EB")
            dialog.update_idletasks()

            if not MYSQL_AVAILABLE:
                result_lbl.config(text="mysql-connector-python not installed. Run: pip install mysql-connector-python", fg="#DC2626")
                return

            try:
                p_int = int(p)
                c = mysql.connector.connect(host=h, port=p_int, user=u, password=pwd, connection_timeout=4)
                c.close()
                result_lbl.config(text="✅ Connection Successful to MySQL Server!", fg="#059669")
            except Exception as e:
                result_lbl.config(text=f"❌ Failed: {str(e)[:60]}...", fg="#DC2626")

        # Save and Apply Action
        def apply_changes():
            chosen_mode = mode_var.get()
            if chosen_mode == "sqlite":
                s_ok, s_msg = db.connect_sqlite()
                if s_ok:
                    messagebox.showinfo("Database Connected", "Switched to Local SQLite Database successfully!", parent=dialog)
                    self.update_header_badge()
                    dialog.destroy()
                    self.refresh_active_view()
                else:
                    messagebox.showerror("Error", s_msg, parent=dialog)
            else:
                h = host_entry.get().strip()
                p = port_entry.get().strip()
                u = user_entry.get().strip()
                pwd = pwd_entry.get()
                d = db_entry.get().strip()

                s_ok, s_msg = db.connect_mysql(h, p, u, pwd, d)
                if s_ok:
                    messagebox.showinfo("Database Connected", f"Successfully connected to MySQL database '{d}'!", parent=dialog)
                    self.update_header_badge()
                    dialog.destroy()
                    self.refresh_active_view()
                else:
                    messagebox.showerror("Connection Failed", f"Could not connect to MySQL:\n{s_msg}\n\nPlease check your credentials or switch to SQLite mode.", parent=dialog)

        btn_bar = tk.Frame(card, bg="#FFFFFF")
        btn_bar.pack(pady=(10, 0))

        tk.Button(btn_bar, text="🔌 Test Connection", font=("Segoe UI", 9), bg="#E2E8F0", fg="#334155", relief="flat", cursor="hand2", padx=10, pady=5, command=test_conn).pack(side="left", padx=5)
        tk.Button(btn_bar, text="💾 Save & Apply", font=("Segoe UI", 9, "bold"), bg="#2563EB", fg="#FFFFFF", relief="flat", cursor="hand2", padx=14, pady=5, command=apply_changes).pack(side="left", padx=5)
        tk.Button(btn_bar, text="Cancel", font=("Segoe UI", 9), bg="#E2E8F0", fg="#334155", relief="flat", cursor="hand2", padx=10, pady=5, command=dialog.destroy).pack(side="left", padx=5)

    def refresh_active_view(self):
        """Refreshes the current view if user or admin is logged in."""
        if self.current_role == "admin":
            self.show_admin_dashboard()
        elif self.current_role == "student":
            self.show_student_dashboard()
        else:
            self.show_welcome_screen()


# =============================================================================
#                               MAIN ENTRY POINT
# =============================================================================

def main():
    app = LibraryApp()
    app.mainloop()

if __name__ == "__main__":
    main()
