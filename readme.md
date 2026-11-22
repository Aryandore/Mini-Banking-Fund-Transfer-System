# Mini Banking & Fund Transfer System

A customer banking application built with Python, Flask, SQLite, and vanilla HTML/CSS/JavaScript. It demonstrates full account CRUD operations, session-based authentication, and all four ACID database properties (Atomicity, Consistency, Isolation, Durability).

## Project Structure

```text
mini_banking_system/
├── static/
│   ├── app.js            # Frontend logic, session state, and API calls
│   └── styles.css        # Dashboard and authentication styling
├── templates/
│   └── index.html        # Login, registration, and personal banking portal
├── app.py                # Flask web server and REST API endpoints
├── crud.py               # Account CRUD and password authentication
├── database.py           # SQLite connection setup and ACID schema
├── transactions.py       # Atomic deposit, withdrawal, and transfer engine
├── test_acid.py          # Automated ACID and concurrency test suite
├── requirements.txt      # Python dependencies
└── .gitignore            # Git ignore rules
```

## Setup & Installation

1. Create and activate a virtual environment:

```bash
python3 -m venv venv
source venv/bin/activate        # macOS / Linux
# venv\Scripts\activate         # Windows CMD
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

## Running the Application

Start the Flask server:

```bash
python app.py
```

Open `http://127.0.0.1:5000` in your browser:
1. Open a new account or sign in with an existing Account Number / Email and password.
2. Deposit funds, withdraw funds, or transfer money to another registered account.
3. View your personal transaction statement or update/close your account in Profile settings.

## Running the ACID Tests

Run the automated test suite to verify rollback atomicity, schema constraints, multi-threaded transfer isolation, and disk durability:

```bash
python test_acid.py
```

## ACID Implementation Summary

- **Atomicity:** Transfers execute inside explicit `BEGIN IMMEDIATE` and `COMMIT` blocks. Any error mid-transfer triggers `ROLLBACK`, reverting all partial balance updates.
- **Consistency:** Enforced at the SQLite schema level via `CHECK` constraints (non-negative balances, positive transaction amounts, valid transfer rules) and `FOREIGN KEY` constraints (`ON DELETE RESTRICT`).
- **Isolation:** Uses `BEGIN IMMEDIATE` write locks so concurrent transfers serialize cleanly without race conditions or double-spending.
- **Durability:** Configured with `PRAGMA journal_mode = WAL` and `PRAGMA synchronous = FULL` so committed transactions persist reliably to disk.