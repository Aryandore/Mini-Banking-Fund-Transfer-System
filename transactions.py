import sqlite3
from typing import Any, Callable, Dict, Optional
from database import DEFAULT_DB_PATH, get_connection
from crud import BankingError


def _validate_positive_amount(amount: float) -> float:
    """Validates and rounds monetary amounts to 2 decimal places."""
    try:
        clean_amount = round(float(amount), 2)
    except (TypeError, ValueError) as e:
        raise BankingError("Amount must be a valid number.") from e

    if clean_amount <= 0.0:
        raise BankingError("Transaction amount must be greater than $0.00.")
    return clean_amount


def deposit_funds(
    account_id: int,
    amount: float,
    description: str = "Cash / Electronic Deposit",
    db_path: str = DEFAULT_DB_PATH,
) -> Dict[str, Any]:
    """
    Atomically credits an account and records a DEPOSIT ledger entry.
    """
    clean_amount = _validate_positive_amount(amount)
    description = (description or "Deposit").strip()

    conn = get_connection(db_path)
    try:
        # Acquire write lock immediately to prevent concurrent race conditions (Isolation)
        conn.execute("BEGIN IMMEDIATE;")

        account = conn.execute("SELECT * FROM accounts WHERE id = ?;", (account_id,)).fetchone()
        if account is None:
            raise BankingError(f"Destination account ID {account_id} does not exist.")

        new_balance = round(account["balance"] + clean_amount, 2)

        conn.execute(
            "UPDATE accounts SET balance = ? WHERE id = ?;",
            (new_balance, account_id),
        )
        cursor = conn.execute(
            """
            INSERT INTO transactions (from_account_id, to_account_id, amount, transaction_type, description)
            VALUES (NULL, ?, ?, 'DEPOSIT', ?);
            """,
            (account_id, clean_amount, description),
        )
        tx_id = cursor.lastrowid

        conn.execute("COMMIT;")

        updated_account = dict(conn.execute("SELECT * FROM accounts WHERE id = ?;", (account_id,)).fetchone())
        tx_record = dict(conn.execute("SELECT * FROM transactions WHERE id = ?;", (tx_id,)).fetchone())
        return {"transaction": tx_record, "account": updated_account}

    except Exception as e:
        if conn.in_transaction:
            conn.execute("ROLLBACK;")
        if isinstance(e, BankingError):
            raise
        if isinstance(e, sqlite3.IntegrityError):
            raise BankingError(f"Deposit rejected by database constraint: {e}") from e
        raise
    finally:
        conn.close()


def withdraw_funds(
    account_id: int,
    amount: float,
    description: str = "Cash / Electronic Withdrawal",
    db_path: str = DEFAULT_DB_PATH,
) -> Dict[str, Any]:
    """
    Atomically debits an account (enforcing sufficient funds) and records a WITHDRAWAL ledger entry.
    """
    clean_amount = _validate_positive_amount(amount)
    description = (description or "Withdrawal").strip()

    conn = get_connection(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE;")

        account = conn.execute("SELECT * FROM accounts WHERE id = ?;", (account_id,)).fetchone()
        if account is None:
            raise BankingError(f"Source account ID {account_id} does not exist.")

        if round(account["balance"], 2) < clean_amount:
            raise BankingError(
                f"Insufficient funds in '{account['account_number']}'. "
                f"Available: ${account['balance']:.2f}, Requested: ${clean_amount:.2f}."
            )

        new_balance = round(account["balance"] - clean_amount, 2)

        conn.execute(
            "UPDATE accounts SET balance = ? WHERE id = ?;",
            (new_balance, account_id),
        )
        cursor = conn.execute(
            """
            INSERT INTO transactions (from_account_id, to_account_id, amount, transaction_type, description)
            VALUES (?, NULL, ?, 'WITHDRAWAL', ?);
            """,
            (account_id, clean_amount, description),
        )
        tx_id = cursor.lastrowid

        conn.execute("COMMIT;")

        updated_account = dict(conn.execute("SELECT * FROM accounts WHERE id = ?;", (account_id,)).fetchone())
        tx_record = dict(conn.execute("SELECT * FROM transactions WHERE id = ?;", (tx_id,)).fetchone())
        return {"transaction": tx_record, "account": updated_account}

    except Exception as e:
        if conn.in_transaction:
            conn.execute("ROLLBACK;")
        if isinstance(e, BankingError):
            raise
        if isinstance(e, sqlite3.IntegrityError):
            raise BankingError(f"Withdrawal rejected by database constraint: {e}") from e
        raise
    finally:
        conn.close()


def transfer_funds(
    from_account_id: int,
    to_account_id: int,
    amount: float,
    description: str = "Fund Transfer",
    db_path: str = DEFAULT_DB_PATH,
    _fault_injection_hook: Optional[Callable[[], None]] = None,
) -> Dict[str, Any]:
    """
    Executes a strictly ACID-compliant peer-to-peer fund transfer:
      1. Atomicity: Debit sender, credit receiver, and log transaction in ONE unit of work.
         Any failure (including _fault_injection_hook) rolls back ALL changes.
      2. Consistency: Enforces non-negative balances, distinct accounts, and total money conservation.
      3. Isolation: BEGIN IMMEDIATE serializes concurrent transfers to prevent lost updates/overdrafts.
      4. Durability: COMMIT flushes WAL frames synchronously to disk.
    """
    clean_amount = _validate_positive_amount(amount)
    description = (description or "Fund Transfer").strip()

    if from_account_id == to_account_id:
        raise BankingError("Source and destination accounts must be different.")

    conn = get_connection(db_path)
    try:
        # 1. ISOLATION: Acquire exclusive write lock BEFORE reading balances
        conn.execute("BEGIN IMMEDIATE;")

        sender = conn.execute("SELECT * FROM accounts WHERE id = ?;", (from_account_id,)).fetchone()
        if sender is None:
            raise BankingError(f"Source account ID {from_account_id} does not exist.")

        receiver = conn.execute("SELECT * FROM accounts WHERE id = ?;", (to_account_id,)).fetchone()
        if receiver is None:
            raise BankingError(f"Destination account ID {to_account_id} does not exist.")

        # 2. CONSISTENCY: Verify sufficient balance before debiting
        if round(sender["balance"], 2) < clean_amount:
            raise BankingError(
                f"Insufficient funds in '{sender['account_number']}'. "
                f"Available: ${sender['balance']:.2f}, Requested: ${clean_amount:.2f}."
            )

        new_sender_balance = round(sender["balance"] - clean_amount, 2)
        new_receiver_balance = round(receiver["balance"] + clean_amount, 2)

        # Step A: Debit Sender
        conn.execute(
            "UPDATE accounts SET balance = ? WHERE id = ?;",
            (new_sender_balance, from_account_id),
        )

        # Optional test hook to simulate mid-transaction crash/failure for Atomicity verification
        if _fault_injection_hook is not None:
            _fault_injection_hook()

        # Step B: Credit Receiver
        conn.execute(
            "UPDATE accounts SET balance = ? WHERE id = ?;",
            (new_receiver_balance, to_account_id),
        )

        # Step C: Append immutable audit record to ledger
        cursor = conn.execute(
            """
            INSERT INTO transactions (from_account_id, to_account_id, amount, transaction_type, description)
            VALUES (?, ?, ?, 'TRANSFER', ?);
            """,
            (from_account_id, to_account_id, clean_amount, description),
        )
        tx_id = cursor.lastrowid

        # 3. ATOMICITY & DURABILITY: Commit all 3 changes permanently
        conn.execute("COMMIT;")

        updated_sender = dict(conn.execute("SELECT * FROM accounts WHERE id = ?;", (from_account_id,)).fetchone())
        updated_receiver = dict(conn.execute("SELECT * FROM accounts WHERE id = ?;", (to_account_id,)).fetchone())
        tx_record = dict(conn.execute("SELECT * FROM transactions WHERE id = ?;", (tx_id,)).fetchone())

        return {
            "transaction": tx_record,
            "from_account": updated_sender,
            "to_account": updated_receiver,
        }

    except Exception as e:
        # 4. ATOMICITY: Undo any partial writes if anything failed
        if conn.in_transaction:
            conn.execute("ROLLBACK;")
        if isinstance(e, BankingError):
            raise
        if isinstance(e, sqlite3.IntegrityError):
            raise BankingError(f"Transfer rejected by database constraint: {e}") from e
        raise
    finally:
        conn.close()