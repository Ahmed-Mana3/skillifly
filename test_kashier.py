"""Quick smoke test for Kashier session creation. Delete after use."""
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import requests
import json
from datetime import datetime, timezone, timedelta

SECRET  = "760e1d629d0c1f54f81c8011db251df7$2c6cae8110f74866251c9185c23c5cc395e5922d70c489de41560ecdba558a9932a2620e3b2f435b909673a566d059cb"
API_KEY = "15eba873-8d1f-4b2d-84fb-c27bd2f40ce1"
MID     = "MID-43351-304"

expire_dt = (datetime.now(timezone.utc) + timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M:%S.000Z')

payload = {
    "merchantId": MID,
    "amount": "50.00",
    "currency": "EGP",
    "order": "SKF-TEST-SMOKE-003",
    "type": "one-time",
    "paymentType": "credit",
    "allowedMethods": "card",
    "defaultMethod": "card",
    "display": "en",
    "merchantRedirect": "https://skillifly.com/payment/callback/?order_id=SKF-TEST-SMOKE-003",
    "failureRedirect": True,
    "expireAt": expire_dt,
    "maxFailureAttempts": 3,
    "enable3DS": True,
    "description": "Skillifly Monthly subscription (smoke test)",
    "customer": {"email": "test@skillifly.com", "reference": "1"},
    "metaData": {
        "order_id": "SKF-TEST-SMOKE-003"
    },
    "serverWebhook": "http://127.0.0.1:8000/webhook/kashier/"
}

headers = {
    "Authorization": SECRET,
    "api-key": API_KEY,
    "Content-Type": "application/json",
}

print("Calling Kashier test API...")
r = requests.post(
    "https://api.kashier.io/v3/payment/sessions",
    json=payload,
    headers=headers,
    timeout=15,
)
print(f"HTTP Status: {r.status_code}")
try:
    data = r.json()
    print("Response JSON:")
    print(json.dumps(data, indent=2, ensure_ascii=False))
except Exception as e:
    pass
