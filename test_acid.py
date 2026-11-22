import os
import sqlite3
import tempfile
import threading
import unittest

from database import get_connection, init_db
from crud import (
    BankingError,
    create_account,
    delete_account,
    get_account_by_id,
    get_account_transactions,
    get_all_accounts,
    update_account_details,
)
from transactions import deposit_funds, transfer_funds, withdraw_funds


class TestACIDBankingSystem(unittest.TestCase):
    def setUp(self):
        """Creates a fresh isolated SQLite database file for each test case."""
        fd, self.db_path = tempfile.mkstemp(prefix="acid_bank_", suffix=".db")
        os.close(fd)
        init_db(self.db_path)

    def tearDown(self):
        """Cleans up the SQLite DB and any WAL/SHM sidecar files after each test."""
        for suffix in ("", "-wal", "-shm"):
            path = self.db_path + suffix
            if os.path.exists(path):
                os.remove(path)

    # ==========================================================
    # 1. ATOMICITY: All-or-Nothing Execution & Rollback
    # ==========================================================
    def test_atomicity_rollback_on_mid_transfer_crash(self):
        alice = create_account("ACC-A1", "Alice", "alice@acid.test", 1000.00, db_path=self.db_path)
        bob = create_account("ACC-B1", "Bob", "bob@acid.test", 250.00, db_path=self.db_path)

        initial_tx_count = len(get_account_transactions(db_path=self.db_path))

        def simulate_power_loss():
            raise RuntimeError("Simulated power outage AFTER debiting Alice and BEFORE crediting Bob!")

        with self.assertRaises(RuntimeError):
            transfer_funds(
                from_account_id=alice["id"],
                to_account_id=bob["id"],
                amount=400.00,
                description="Doomed transfer",
                db_path=self.db_path,
                _fault_injection_hook=simulate_power_loss,
            )

        # Verify ROLLBACK completely undid Alice's debit and wrote no partial ledger record
        alice_after = get_account_by_id(alice["id"], db_path=self.db_path)
        bob_after = get_account_by_id(bob["id"], db_path=self.db_path)
        final_tx_count = len(get_account_transactions(db_path=self.db_path))

        self.assertEqual(alice_after["balance"], 1000.00, "Alice's balance must be rolled back to $1000.00")
        self.assertEqual(bob_after["balance"], 250.00, "Bob's balance must remain $250.00")
        self.assertEqual(final_tx_count, initial_tx_count, "No partial transaction row should exist after rollback")

    # ==========================================================
    # 2. CONSISTENCY: Schema CHECK, FOREIGN KEY, & Invariants
    # ==========================================================
    def test_consistency_constraints_and_money_conservation(self):
        alice = create_account("ACC-C1", "Alice", "alice@cons.test", 500.00, db_path=self.db_path)
        bob = create_account("ACC-C2", "Bob", "bob@cons.test", 300.00, db_path=self.db_path)

        # Attempt overdraft transfer ($600 > $500) -> must fail cleanly
        with self.assertRaises(BankingError):
            transfer_funds(alice["id"], bob["id"], 600.00, db_path=self.db_path)

        # Attempt self-transfer -> must fail cleanly
        with self.assertRaises(BankingError):
            transfer_funds(alice["id"], alice["id"], 50.00, db_path=self.db_path)

        # Direct SQL injection bypassing Python logic must STILL be blocked by SQLite CHECK constraint
        conn = get_connection(self.db_path)
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("UPDATE accounts SET balance = -1.00 WHERE id = ?;", (alice["id"],))
        finally:
            conn.close()

        # Execute valid transfer and verify total system liquidity is strictly conserved ($800.00)
        transfer_funds(alice["id"], bob["id"], 175.50, db_path=self.db_path)
        accounts = get_all_accounts(db_path=self.db_path)
        total_money = round(sum(a["balance"] for a in accounts), 2)
        self.assertEqual(total_money, 800.00, "Total system money must remain conserved at $800.00")

        # Drain Alice to $0.00 and verify FOREIGN KEY ON DELETE RESTRICT preserves audit history
        withdraw_funds(alice["id"], 324.50, db_path=self.db_path)
        self.assertEqual(get_account_by_id(alice["id"], db_path=self.db_path)["balance"], 0.00)
        with self.assertRaises(BankingError):
            delete_account(alice["id"], db_path=self.db_path)

    # ==========================================================
    # 3. ISOLATION: Multi-Threaded Concurrent Transfer Stress Test
    # ==========================================================
    def test_isolation_concurrent_transfers_no_overdraft_or_lost_updates(self):
        """
        20 threads simultaneously attempt to transfer $100.00 each from Alice ($500.00) to Bob ($0.00).
        Without proper write-lock isolation, concurrent reads would allow >5 threads to succeed (double-spend).
        With BEGIN IMMEDIATE, strictly 5 succeed and 15 fail with Insufficient Funds.
        """
        alice = create_account("ACC-ISO1", "Alice", "alice@iso.test", 500.00, db_path=self.db_path)
        bob = create_account("ACC-ISO2", "Bob", "bob@iso.test", 0.00, db_path=self.db_path)

        num_threads = 20
        transfer_amount = 100.00
        barrier = threading.Barrier(num_threads)  # Forces all 20 threads to fire at the exact same instant

        results_lock = threading.Lock()
        success_count = 0
        insufficient_count = 0
        unexpected_errors = []

        def worker(worker_idx: int):
            nonlocal success_count, insufficient_count
            barrier.wait()  # Synchronize start for maximum lock contention
            try:
                transfer_funds(
                    from_account_id=alice["id"],
                    to_account_id=bob["id"],
                    amount=transfer_amount,
                    description=f"Concurrent worker #{worker_idx}",
                    db_path=self.db_path,
                )
                with results_lock:
                    success_count += 1
            except BankingError as e:
                if "Insufficient funds" in str(e):
                    with results_lock:
                        insufficient_count += 1
                else:
                    with results_lock:
                        unexpected_errors.append(str(e))
            except Exception as e:
                with results_lock:
                    unexpected_errors.append(repr(e))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(unexpected_errors, [], f"Unexpected errors occurred: {unexpected_errors}")
        self.assertEqual(success_count, 5, "Exactly 5 transfers of $100 should succeed out of $500 balance")
        self.assertEqual(insufficient_count, 15, "Remaining 15 concurrent transfers must fail cleanly")

        alice_final = get_account_by_id(alice["id"], db_path=self.db_path)
        bob_final = get_account_by_id(bob["id"], db_path=self.db_path)

        self.assertEqual(alice_final["balance"], 0.00, "Alice's final balance must be exactly $0.00")
        self.assertEqual(bob_final["balance"], 500.00, "Bob's final balance must be exactly $500.00")

    # ==========================================================
    # 4. DURABILITY: Persistence Across Reconnections
    # ==========================================================
    def test_durability_persists_across_fresh_connections(self):
        alice = create_account("ACC-DUR1", "Alice", "alice@dur.test", 750.00, db_path=self.db_path)
        bob = create_account("ACC-DUR2", "Bob", "bob@dur.test", 100.00, db_path=self.db_path)

        deposit_funds(alice["id"], 250.00, "Bonus deposit", db_path=self.db_path)
        transfer_funds(alice["id"], bob["id"], 400.00, "Durable payment", db_path=self.db_path)
        update_account_details(bob["id"], owner_name="Bob Durable", db_path=self.db_path)

        # Open a completely fresh raw SQLite connection directly to the disk file
        fresh_conn = sqlite3.connect(self.db_path)
        try:
            journal_mode = fresh_conn.execute("PRAGMA journal_mode;").fetchone()[0]
            sync_mode = fresh_conn.execute("PRAGMA synchronous;").fetchone()[0]
            alice_row = fresh_conn.execute("SELECT balance FROM accounts WHERE id = ?;", (alice["id"],)).fetchone()
            bob_row = fresh_conn.execute(
                "SELECT owner_name, balance FROM accounts WHERE id = ?;", (bob["id"],)
            ).fetchone()
            tx_count = fresh_conn.execute("SELECT COUNT(*) FROM transactions;").fetchone()[0]

            self.assertEqual(journal_mode.lower(), "wal")
            self.assertEqual(sync_mode, 2)  # 2 == FULL synchronous durability
            self.assertEqual(alice_row[0], 600.00)
            self.assertEqual(bob_row[0], "Bob Durable")
            self.assertEqual(bob_row[1], 500.00)
            self.assertEqual(tx_count, 4)  # 2 initial deposits + 1 deposit + 1 transfer
        finally:
            fresh_conn.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)