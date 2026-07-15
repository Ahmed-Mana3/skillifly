import logging
import time
import hmac
import hashlib
import requests
from django.conf import settings

logger = logging.getLogger('payments')

# Simple in-memory token cache
_token_cache = {'token': None, 'expires_at': 0}

def _get_base_url() -> str:
    return getattr(settings, 'FAWATERK_BASE_URL', 'https://staging.fawaterk.com')

def get_access_token() -> str:
    now = time.time()
    if _token_cache['token'] and now < _token_cache['expires_at'] - 60:
        return _token_cache['token']

    url = f"{_get_base_url()}/oauth/token"
    resp = requests.post(url, json={
        'grant_type': 'client_credentials',
        'client_id': settings.FAWATERK_CLIENT_ID,
        'client_secret': settings.FAWATERK_CLIENT_SECRET,
    }, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    _token_cache['token'] = data['access_token']
    _token_cache['expires_at'] = now + data.get('expires_in', 86400)

    return _token_cache['token']

def create_transaction(cart_total: str, currency: str, customer: dict,
                        cart_items: list, redirection_urls: dict,
                        pay_load: dict = None) -> dict:
    token = get_access_token()
    url = f"{_get_base_url()}/api/v3/createTransaction"

    body = {
        'cartTotal': cart_total,
        'currency': currency,
        'list_style': 'h',
        'customer': customer,
        'cartItems': cart_items,
        'redirectionUrls': redirection_urls,
    }
    if pay_load:
        body['pay_load'] = pay_load

    resp = requests.post(url, json=body, headers={
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json',
    }, timeout=15)
    resp.raise_for_status()
    return resp.json()

def get_transaction_data(intent_key: str) -> dict:
    token = get_access_token()
    url = f"{_get_base_url()}/api/v3/getTransactionData"
    resp = requests.post(url, json={'intent_key': intent_key}, headers={
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json',
    }, timeout=15)
    resp.raise_for_status()
    return resp.json()

def verify_paid_webhook(payload: dict) -> bool:
    received_hash = payload.get('transactionHashKey', '')
    invoice_key   = payload.get('invoice_key', '')
    payment_status = payload.get('payment_status', '')

    vendor_key = getattr(settings, 'FAWATERK_VENDOR_KEY', '')
    if not vendor_key:
        logger.warning('FAWATERK_VENDOR_KEY not set — skipping signature check')
        return False

    string_to_sign = f"invoice_key={invoice_key}&payment_status={payment_status}"
    expected = hmac.new(
        vendor_key.encode('utf-8'),
        string_to_sign.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(expected, received_hash)
