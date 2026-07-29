import httpx

base = 'http://127.0.0.1:8000'

r = httpx.get(f'{base}/api/v1/health', timeout=3)
print(f'Server: {r.status_code} {r.json()}')

r = httpx.post(f'{base}/api/v1/auth/login', json={'username': 'admin', 'password': 'Admin123!'}, timeout=5)
if r.status_code == 200:
    token = r.json()['access_token']
    h = {'Authorization': f'Bearer {token}'}

    r = httpx.post(f'{base}/api/v1/warehouses', headers=h, json={
        'code': 'WH-001', 'name': 'Main Warehouse', 'address': 'Addr 1', 'city': 'City', 'country': 'CN', 'is_active': True
    }, timeout=5)
    print(f'Create WH: {r.status_code}')

    r = httpx.get(f'{base}/api/v1/warehouses', headers=h, timeout=5)
    data = r.json()
    items = data.get('data') or data.get('items') or []
    print(f'List WH: {r.status_code} count={len(items)}')
else:
    print(f'Login failed: {r.status_code} {r.text[:200]}')
