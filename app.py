from flask import Flask, jsonify, render_template, request
from database import DEFAULT_DB_PATH, init_db
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


def create_app(db_path: str = DEFAULT_DB_PATH) -> Flask:
    """Application factory creating a configured Flask instance."""
    app = Flask(__name__)
    app.config["DB_PATH"] = db_path

    # Ensure database schema exists at startup
    init_db(db_path)

    # ==========================================
    # FRONTEND ROUTE
    # ==========================================
    @app.route("/", methods=["GET"])
    def index():
        return render_template("index.html")

    # ==========================================
    # ACCOUNT CRUD ENDPOINTS
    # ==========================================
    @app.route("/api/accounts", methods=["GET"])
    def api_list_accounts():
        accounts = get_all_accounts(db_path=app.config["DB_PATH"])
        total_liquidity = round(sum(acc["balance"] for acc in accounts), 2)
        return jsonify({
            "accounts": accounts,
            "total_liquidity": total_liquidity,
            "count": len(accounts),
        }), 200

    @app.route("/api/accounts", methods=["POST"])
    def api_create_account():
        data = request.get_json(silent=True) or {}
        account_number = str(data.get("account_number", "")).strip()
        owner_name = str(data.get("owner_name", "")).strip()
        email = str(data.get("email", "")).strip()

        if not account_number or not owner_name or not email:
            return jsonify({"error": "Account number, owner name, and email are required."}), 400

        try:
            initial_balance = float(data.get("initial_balance", 0.0))
        except (TypeError, ValueError):
            return jsonify({"error": "Initial balance must be a valid number."}), 400

        try:
            account = create_account(
                account_number=account_number,
                owner_name=owner_name,
                email=email,
                initial_balance=initial_balance,
                db_path=app.config["DB_PATH"],
            )
            return jsonify({
                "message": f"Account {account['account_number']} created successfully.",
                "account": account,
            }), 201
        except BankingError as e:
            return jsonify({"error": str(e)}), 400

    @app.route("/api/accounts/<int:account_id>", methods=["GET"])
    def api_get_account(account_id: int):
        try:
            account = get_account_by_id(account_id, db_path=app.config["DB_PATH"])
            history = get_account_transactions(account_id, db_path=app.config["DB_PATH"])
            return jsonify({"account": account, "transactions": history}), 200
        except BankingError as e:
            return jsonify({"error": str(e)}), 404

    @app.route("/api/accounts/<int:account_id>", methods=["PUT"])
    def api_update_account(account_id: int):
        data = request.get_json(silent=True) or {}
        owner_name = data.get("owner_name")
        email = data.get("email")

        if owner_name is not None and not str(owner_name).strip():
            return jsonify({"error": "Owner name cannot be blank."}), 400
        if email is not None and not str(email).strip():
            return jsonify({"error": "Email cannot be blank."}), 400

        try:
            updated = update_account_details(
                account_id=account_id,
                owner_name=owner_name,
                email=email,
                db_path=app.config["DB_PATH"],
            )
            return jsonify({
                "message": f"Account {updated['account_number']} updated successfully.",
                "account": updated,
            }), 200
        except BankingError as e:
            status = 404 if "does not exist" in str(e) else 400
            return jsonify({"error": str(e)}), status

    @app.route("/api/accounts/<int:account_id>", methods=["DELETE"])
    def api_delete_account(account_id: int):
        try:
            result = delete_account(account_id, db_path=app.config["DB_PATH"])
            acc_num = result["account"]["account_number"]
            return jsonify({
                "message": f"Account {acc_num} deleted successfully.",
                "deleted": True,
            }), 200
        except BankingError as e:
            status = 404 if "does not exist" in str(e) else 400
            return jsonify({"error": str(e)}), status

    # ==========================================
    # TRANSACTION & ACID FUND TRANSFER ENDPOINTS
    # ==========================================
    @app.route("/api/transactions", methods=["GET"])
    def api_list_transactions():
        account_id = request.args.get("account_id", type=int)
        limit = request.args.get("limit", default=50, type=int)
        try:
            txs = get_account_transactions(
                account_id=account_id,
                limit=limit,
                db_path=app.config["DB_PATH"],
            )
            return jsonify({"transactions": txs, "count": len(txs)}), 200
        except BankingError as e:
            return jsonify({"error": str(e)}), 404

    @app.route("/api/accounts/<int:account_id>/deposit", methods=["POST"])
    def api_deposit(account_id: int):
        data = request.get_json(silent=True) or {}
        try:
            result = deposit_funds(
                account_id=account_id,
                amount=data.get("amount"),
                description=data.get("description", "Deposit"),
                db_path=app.config["DB_PATH"],
            )
            return jsonify({
                "message": f"Deposited ${result['transaction']['amount']:.2f} into {result['account']['account_number']}.",
                **result,
            }), 200
        except BankingError as e:
            status = 404 if "does not exist" in str(e) else 400
            return jsonify({"error": str(e)}), status

    @app.route("/api/accounts/<int:account_id>/withdraw", methods=["POST"])
    def api_withdraw(account_id: int):
        data = request.get_json(silent=True) or {}
        try:
            result = withdraw_funds(
                account_id=account_id,
                amount=data.get("amount"),
                description=data.get("description", "Withdrawal"),
                db_path=app.config["DB_PATH"],
            )
            return jsonify({
                "message": f"Withdrew ${result['transaction']['amount']:.2f} from {result['account']['account_number']}.",
                **result,
            }), 200
        except BankingError as e:
            status = 404 if "does not exist" in str(e) else 400
            return jsonify({"error": str(e)}), status

    @app.route("/api/transfer", methods=["POST"])
    def api_transfer():
        data = request.get_json(silent=True) or {}
        try:
            from_id = int(data.get("from_account_id"))
            to_id = int(data.get("to_account_id"))
        except (TypeError, ValueError):
            return jsonify({"error": "Valid source and destination accounts must be selected."}), 400

        try:
            result = transfer_funds(
                from_account_id=from_id,
                to_account_id=to_id,
                amount=data.get("amount"),
                description=data.get("description", "Fund Transfer"),
                db_path=app.config["DB_PATH"],
            )
            tx = result["transaction"]
            src_num = result["from_account"]["account_number"]
            dst_num = result["to_account"]["account_number"]
            return jsonify({
                "message": f"Transferred ${tx['amount']:.2f} from {src_num} to {dst_num} (ACID Committed).",
                **result,
            }), 200
        except BankingError as e:
            status = 404 if "does not exist" in str(e) else 400
            return jsonify({"error": str(e)}), status

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5000) 