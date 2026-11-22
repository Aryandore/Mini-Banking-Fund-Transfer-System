import os
from functools import wraps
from flask import Flask, jsonify, render_template, request, session
from database import DEFAULT_DB_PATH, init_db
from crud import (
    BankingError,
    authenticate_account,
    create_account,
    delete_account,
    get_account_by_id,
    get_account_transactions,
    get_all_accounts,
    update_account_details,
)
from transactions import deposit_funds, transfer_funds, withdraw_funds


def create_app(db_path: str = DEFAULT_DB_PATH) -> Flask:
    """Application factory creating a configured Flask instance with session authentication."""
    app = Flask(__name__)
    app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-acid-banking-secret-key-2026")
    app.config["DB_PATH"] = db_path

    init_db(db_path)

    def login_required(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            account_id = session.get("account_id")
            if not account_id:
                return jsonify({"error": "Authentication required. Please log in."}), 401
            try:
                current_user = get_account_by_id(account_id, db_path=app.config["DB_PATH"])
            except BankingError:
                session.clear()
                return jsonify({"error": "Session expired or account not found. Please log in again."}), 401
            return fn(current_user, *args, **kwargs)
        return wrapper

    # ==========================================
    # FRONTEND ENTRY POINT
    # ==========================================
    @app.route("/", methods=["GET"])
    def index():
        return render_template("index.html")

    # ==========================================
    # AUTHENTICATION & ACCOUNT REGISTRATION
    # ==========================================
    @app.route("/api/auth/me", methods=["GET"])
    def api_me():
        account_id = session.get("account_id")
        if not account_id:
            return jsonify({"authenticated": False}), 200
        try:
            account = get_account_by_id(account_id, db_path=app.config["DB_PATH"])
            return jsonify({"authenticated": True, "account": account}), 200
        except BankingError:
            session.clear()
            return jsonify({"authenticated": False}), 200

    @app.route("/api/auth/register", methods=["POST"])
    def api_register():
        data = request.get_json(silent=True) or {}
        account_number = str(data.get("account_number", "")).strip()
        owner_name = str(data.get("owner_name", "")).strip()
        email = str(data.get("email", "")).strip()
        password = str(data.get("password", ""))

        if not account_number or not owner_name or not email or not password:
            return jsonify({"error": "Account number, full name, email, and password are required."}), 400

        try:
            initial_balance = float(data.get("initial_balance", 0.0))
        except (TypeError, ValueError):
            return jsonify({"error": "Initial deposit must be a valid number."}), 400

        try:
            account = create_account(
                account_number=account_number,
                owner_name=owner_name,
                email=email,
                password=password,
                initial_balance=initial_balance,
                db_path=app.config["DB_PATH"],
            )
            session["account_id"] = account["id"]
            return jsonify({
                "message": f"Welcome, {account['owner_name']}! Account {account['account_number']} is ready.",
                "account": account,
            }), 201
        except BankingError as e:
            return jsonify({"error": str(e)}), 400

    @app.route("/api/auth/login", methods=["POST"])
    def api_login():
        data = request.get_json(silent=True) or {}
        identifier = str(data.get("identifier", "")).strip()
        password = str(data.get("password", ""))

        try:
            account = authenticate_account(identifier, password, db_path=app.config["DB_PATH"])
            session["account_id"] = account["id"]
            return jsonify({
                "message": f"Signed in as {account['owner_name']} ({account['account_number']}).",
                "account": account,
            }), 200
        except BankingError as e:
            return jsonify({"error": str(e)}), 401

    @app.route("/api/auth/logout", methods=["POST"])
    def api_logout():
        session.clear()
        return jsonify({"message": "You have been signed out securely."}), 200

    # ==========================================
    # LOGGED-IN CUSTOMER OPERATIONS
    # ==========================================
    @app.route("/api/recipients", methods=["GET"])
    @login_required
    def api_recipients(current_user):
        """Lists other accounts as transfer recipients (without exposing their private balances)."""
        all_accs = get_all_accounts(db_path=app.config["DB_PATH"])
        recipients = [
            {
                "id": acc["id"],
                "account_number": acc["account_number"],
                "owner_name": acc["owner_name"],
            }
            for acc in all_accs
            if acc["id"] != current_user["id"]
        ]
        return jsonify({"recipients": recipients}), 200

    @app.route("/api/transactions", methods=["GET"])
    @login_required
    def api_my_transactions(current_user):
        limit = request.args.get("limit", default=50, type=int)
        txs = get_account_transactions(
            account_id=current_user["id"],
            limit=limit,
            db_path=app.config["DB_PATH"],
        )
        return jsonify({"transactions": txs, "count": len(txs)}), 200

    @app.route("/api/deposit", methods=["POST"])
    @login_required
    def api_deposit(current_user):
        data = request.get_json(silent=True) or {}
        try:
            result = deposit_funds(
                account_id=current_user["id"],
                amount=data.get("amount"),
                description=data.get("description", "Deposit"),
                db_path=app.config["DB_PATH"],
            )
            return jsonify({
                "message": f"Deposited ${result['transaction']['amount']:.2f} into your account.",
                **result,
            }), 200
        except BankingError as e:
            return jsonify({"error": str(e)}), 400

    @app.route("/api/withdraw", methods=["POST"])
    @login_required
    def api_withdraw(current_user):
        data = request.get_json(silent=True) or {}
        try:
            result = withdraw_funds(
                account_id=current_user["id"],
                amount=data.get("amount"),
                description=data.get("description", "Withdrawal"),
                db_path=app.config["DB_PATH"],
            )
            return jsonify({
                "message": f"Withdrew ${result['transaction']['amount']:.2f} from your account.",
                **result,
            }), 200
        except BankingError as e:
            return jsonify({"error": str(e)}), 400

    @app.route("/api/transfer", methods=["POST"])
    @login_required
    def api_transfer(current_user):
        data = request.get_json(silent=True) or {}
        try:
            to_id = int(data.get("to_account_id"))
        except (TypeError, ValueError):
            return jsonify({"error": "Please select a valid recipient account."}), 400

        try:
            result = transfer_funds(
                from_account_id=current_user["id"],
                to_account_id=to_id,
                amount=data.get("amount"),
                description=data.get("description", "Fund Transfer"),
                db_path=app.config["DB_PATH"],
            )
            tx = result["transaction"]
            dst_num = result["to_account"]["account_number"]
            dst_name = result["to_account"]["owner_name"]
            return jsonify({
                "message": f"Transferred ${tx['amount']:.2f} to {dst_name} ({dst_num}) — ACID Committed.",
                **result,
            }), 200
        except BankingError as e:
            return jsonify({"error": str(e)}), 400

    @app.route("/api/profile", methods=["PUT"])
    @login_required
    def api_update_profile(current_user):
        data = request.get_json(silent=True) or {}
        owner_name = data.get("owner_name")
        email = data.get("email")

        if owner_name is not None and not str(owner_name).strip():
            return jsonify({"error": "Owner name cannot be blank."}), 400
        if email is not None and not str(email).strip():
            return jsonify({"error": "Email cannot be blank."}), 400

        try:
            updated = update_account_details(
                account_id=current_user["id"],
                owner_name=owner_name,
                email=email,
                db_path=app.config["DB_PATH"],
            )
            return jsonify({
                "message": "Profile details updated successfully.",
                "account": updated,
            }), 200
        except BankingError as e:
            return jsonify({"error": str(e)}), 400

    @app.route("/api/profile", methods=["DELETE"])
    @login_required
    def api_close_account(current_user):
        try:
            delete_account(current_user["id"], db_path=app.config["DB_PATH"])
            session.clear()
            return jsonify({"message": "Your account has been closed."}), 200
        except BankingError as e:
            return jsonify({"error": str(e)}), 400

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5000)