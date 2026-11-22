import os
from app import create_app

test_db = 'test_api.db'
if os.path.exists(test_db):
    os.remove(test_db)

flask_app = create_app(db_path=test_db)
client = flask_app.test_client()

# 1. Create two accounts via POST /api/accounts
r1 = client.post('/api/accounts', json={'account_number': 'ACC-3001', 'owner_name': 'Maya Lin', 'email': 'maya@bank.com', 'initial_balance': 800})
r2 = client.post('/api/accounts', json={'account_number': 'ACC-3002', 'owner_name': 'Liam Vance', 'email': 'liam@bank.com', 'initial_balance': 100})
assert r1.status_code == 201 and r2.status_code == 201
id1 = r1.get_json()['account']['id']
id2 = r2.get_json()['account']['id']

# 2. Execute ACID transfer via POST /api/transfer
tx_res = client.post('/api/transfer', json={'from_account_id': id1, 'to_account_id': id2, 'amount': 300, 'description': 'Consulting fee'})
print('Transfer HTTP status:', tx_res.status_code, '| Message:', tx_res.get_json()['message'])

# 3. Verify total system liquidity conserved ($800 + $100 = $900)
list_res = client.get('/api/accounts').get_json()
print('Total Liquidity:', list_res['total_liquidity'], '| Accounts:', [(a['account_number'], a['balance']) for a in list_res['accounts']])

# 4. Update account via PUT
upd_res = client.put(f'/api/accounts/{id2}', json={'owner_name': 'Liam R. Vance'})
print('PUT Update status:', upd_res.status_code, '| New Name:', upd_res.get_json()['account']['owner_name'])

os.remove(test_db)