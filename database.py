import sqlite3

DEFAULT_DB_PATH = "banking.db"


def get_connection(db_path: str = DEFAULT_DB_PATH, timeout: float = 10.0) -> sqlite3.Connection:
    """
    Opens a SQLite connection configured for ACID compliance:
    - timeout: Seconds to wait if another thread holds a write lock (Isolation).
    - isolation_level=None: Enables manual transaction control via explicit BEGIN/COMMIT/ROLLBACK.
    - PRAGMA foreign_keys = ON: Enforces referential integrity per connection.
    - PRAGMA journal_mode = WAL: Enables Write-Ahead Logging for concurrency & Durability.
    - PRAGMA synchronous = FULL: Ensures transactions are flushed to disk on commit (Durability).
    """
    conn = sqlite3.connect(db_path, timeout=timeout, isolation_level=None)
    conn.row_factory = sqlite3.Row  # Allows accessing columns by name (e.g., row["balance"])

    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = FULL;")

    return conn


def init_db(db_path: str = DEFAULT_DB_PATH) -> None:
    """
    Creates the 'accounts' and 'transactions' tables with strict Consistency constraints.
    """
    conn = get_connection(db_path)
    try:
        conn.execute("BEGIN;")

        # 1. Accounts Table
        # - balance >= 0.00 enforces the invariant that no account can ever be overdrawn.
        # - account_number is UNIQUE and non-empty.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_number TEXT NOT NULL UNIQUE CHECK(length(trim(account_number)) > 0),
                owner_name TEXT NOT NULL CHECK(length(trim(owner_name)) > 0),
                email TEXT NOT NULL UNIQUE CHECK(instr(email, '@') > 1),
                balance REAL NOT NULL DEFAULT 0.0 CHECK(round(balance, 2) >= 0.0),
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # 2. Transactions Ledger Table
        # - Records every deposit, withdrawal, and transfer for auditability.
        # - ON DELETE RESTRICT prevents deleting an account that still has ledger history,
        #   preserving financial audit integrity (or we handle safe deletion in CRUD).
        conn.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_account_id INTEGER,
                to_account_id INTEGER,
                amount REAL NOT NULL CHECK(round(amount, 2) > 0.0),
                transaction_type TEXT NOT NULL CHECK(transaction_type IN ('DEPOSIT', 'WITHDRAWAL', 'TRANSFER')),
                description TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (from_account_id) REFERENCES accounts(id) ON DELETE RESTRICT,
                FOREIGN KEY (to_account_id) REFERENCES accounts(id) ON DELETE RESTRICT,
                CHECK (
                    (transaction_type = 'DEPOSIT' AND from_account_id IS NULL AND to_account_id IS NOT NULL) OR
                    (transaction_type = 'WITHDRAWAL' AND from_account_id IS NOT NULL AND to_account_id IS NULL) OR
                    (transaction_type = 'TRANSFER' AND from_account_id IS NOT NULL AND to_account_id IS NOT NULL AND from_account_id != to_account_id)
                )
            );
        """)

        conn.execute("COMMIT;")
    except Exception:
        conn.execute("ROLLBACK;")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    init_db()
    print(f"Database initialized successfully at '{DEFAULT_DB_PATH}'.")