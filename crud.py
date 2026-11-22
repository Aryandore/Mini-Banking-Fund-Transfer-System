import sqlite3
from typing import Any, Dict, List, Optional
from database import DEFAULT_DB_PATH, get_connection


class BankingError(Exception):
    """Custom domain exception for business rule and database constraint violations."""
    pass


def _row_to_dict(row: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
    """Converts a sqlite3.Row object into a plain Python dictionary."""
    return dict(row) if row is not None else None


# ==========================================
# CREATE
# ==========================================
def create_account(
    account_number: str,
    owner_name: str,
    email: str,
    initial_balance: float = 0.0,
    db_path: str = DEFAULT_DB_PATH,
) -> Dict[str, Any]:
    """
    Creates a new bank account and logs an initial DEPOSIT transaction if initial_balance > 0.
    """
    account_number = account_number.strip().upper()
    owner_name = owner_name.strip()
    email = email.strip().lower()
    initial_balance = round(float(initial_balance), 2)

    if initial_balance < 0:
        raise BankingError("Initial balance cannot be negative.")

    conn = get_connection(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE;")

        cursor = conn.execute(
            """
            INSERT INTO accounts (account_number, owner_name, email, balance)
            VALUES (?, ?, ?, ?);
            """,
            (account_number, owner_name, email, initial_balance),
        )
        account_id = cursor.lastrowid

        if initial_balance > 0:
            conn.execute(
                """
                INSERT INTO transactions (from_account_id, to_account_id, amount, transaction_type, description)
                VALUES (NULL, ?, ?, 'DEPOSIT', 'Initial account opening deposit');
                """,
                (account_id, initial_balance),
            )

        conn.execute("COMMIT;")

        created = conn.execute("SELECT * FROM accounts WHERE id = ?;", (account_id,)).fetchone()
        return _row_to_dict(created)

    except sqlite3.IntegrityError as e:
        if conn.in_transaction:
            conn.execute("ROLLBACK;")
        err_msg = str(e)
        if "accounts.account_number" in err_msg:
            raise BankingError(f"Account number '{account_number}' already exists.") from e
        if "accounts.email" in err_msg:
            raise BankingError(f"Email '{email}' is already registered to another account.") from e
        raise BankingError(f"Database constraint violation: {err_msg}") from e
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK;")
        raise
    finally:
        conn.close()


# ==========================================
# READ
# ==========================================
def get_all_accounts(db_path: str = DEFAULT_DB_PATH) -> List[Dict[str, Any]]:
    """Returns all accounts ordered by newest first."""
    conn = get_connection(db_path)
    try:
        rows = conn.execute("SELECT * FROM accounts ORDER BY id DESC;").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_account_by_id(account_id: int, db_path: str = DEFAULT_DB_PATH) -> Dict[str, Any]:
    """Fetches a single account by primary key ID or raises BankingError if not found."""
    conn = get_connection(db_path)
    try:
        row = conn.execute("SELECT * FROM accounts WHERE id = ?;", (account_id,)).fetchone()
        if row is None:
            raise BankingError(f"Account with ID {account_id} does not exist.")
        return dict(row)
    finally:
        conn.close()


def get_account_transactions(
    account_id: Optional[int] = None,
    limit: int = 50,
    db_path: str = DEFAULT_DB_PATH,
) -> List[Dict[str, Any]]:
    """
    Fetches transaction history with joined account numbers for readable display.
    If account_id is None, returns recent system-wide transactions.
    """
    conn = get_connection(db_path)
    try:
        base_query = """
            SELECT
                t.id,
                t.from_account_id,
                src.account_number AS from_account_number,
                src.owner_name AS from_owner_name,
                t.to_account_id,
                dst.account_number AS to_account_number,
                dst.owner_name AS to_owner_name,
                t.amount,
                t.transaction_type,
                t.description,
                t.created_at
            FROM transactions t
            LEFT JOIN accounts src ON t.from_account_id = src.id
            LEFT JOIN accounts dst ON t.to_account_id = dst.id
        """
        if account_id is not None:
            # Verify account exists first
            get_account_by_id(account_id, db_path=db_path)
            query = base_query + """
                WHERE t.from_account_id = ? OR t.to_account_id = ?
                ORDER BY t.id DESC
                LIMIT ?;
            """
            rows = conn.execute(query, (account_id, account_id, limit)).fetchall()
        else:
            query = base_query + " ORDER BY t.id DESC LIMIT ?;"
            rows = conn.execute(query, (limit,)).fetchall()

        return [dict(r) for r in rows]
    finally:
        conn.close()


# ==========================================
# UPDATE
# ==========================================
def update_account_details(
    account_id: int,
    owner_name: Optional[str] = None,
    email: Optional[str] = None,
    db_path: str = DEFAULT_DB_PATH,
) -> Dict[str, Any]:
    """
    Updates mutable metadata (owner_name and/or email) for an existing account.
    Note: Balance is intentionally NOT editable here—balances can only change via ACID transactions.
    """
    existing = get_account_by_id(account_id, db_path=db_path)

    new_name = owner_name.strip() if owner_name is not None else existing["owner_name"]
    new_email = email.strip().lower() if email is not None else existing["email"]

    conn = get_connection(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE;")
        conn.execute(
            """
            UPDATE accounts
            SET owner_name = ?, email = ?
            WHERE id = ?;
            """,
            (new_name, new_email, account_id),
        )
        conn.execute("COMMIT;")

        updated = conn.execute("SELECT * FROM accounts WHERE id = ?;", (account_id,)).fetchone()
        return dict(updated)

    except sqlite3.IntegrityError as e:
        if conn.in_transaction:
            conn.execute("ROLLBACK;")
        err_msg = str(e)
        if "accounts.email" in err_msg:
            raise BankingError(f"Email '{new_email}' is already in use.") from e
        raise BankingError(f"Invalid account details: {err_msg}") from e
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK;")
        raise
    finally:
        conn.close()


# ==========================================
# DELETE
# ==========================================
def delete_account(account_id: int, db_path: str = DEFAULT_DB_PATH) -> Dict[str, Any]:
    """
    Deletes an account only if its balance is $0.00 and it has no restricted ledger history.
    """
    account = get_account_by_id(account_id, db_path=db_path)

    if round(account["balance"], 2) != 0.0:
        raise BankingError(
            f"Cannot delete account '{account['account_number']}' with non-zero balance (${account['balance']:.2f}). "
            "Withdraw or transfer funds first."
        )

    conn = get_connection(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE;")
        conn.execute("DELETE FROM accounts WHERE id = ?;", (account_id,))
        conn.execute("COMMIT;")
        return {"deleted": True, "account": account}

    except sqlite3.IntegrityError as e:
        if conn.in_transaction:
            conn.execute("ROLLBACK;")
        raise BankingError(
            f"Cannot delete account '{account['account_number']}' because it has existing transaction ledger records "
            "(FOREIGN KEY ON DELETE RESTRICT)."
        ) from e
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK;")
        raise
    finally:
        conn.close()