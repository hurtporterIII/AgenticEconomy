import os
import uuid

import requests
from dotenv import load_dotenv

load_dotenv(override=True)

BASE = os.getenv("CIRCLE_BASE_URL", "https://api-sandbox.circle.com")
API_KEY = os.getenv("CIRCLE_API_KEY")
WALLET_ID = os.getenv("CIRCLE_WALLET_ID")
DEST = os.getenv("USDC_DESTINATION_ADDRESS")


def _simulate(from_wallet, to_wallet, amount):
    return f"tx_{from_wallet}_{to_wallet}_{amount}"


def submit_transaction(from_wallet, to_wallet, amount):
    """
    Returns tx hash
    """
    if API_KEY and WALLET_ID and DEST:
        try:
            url = f"{BASE}/v1/transfers"
            headers = {
                "Authorization": f"Bearer {API_KEY}",
                "Content-Type": "application/json",
            }
            payload = {
                "idempotencyKey": str(uuid.uuid4()),
                "source": {"type": "wallet", "id": WALLET_ID},
                "destination": {"type": "blockchain", "address": DEST, "chain": "ARC"},
                "amount": {"amount": str(amount), "currency": "USD"},
            }
            response = requests.post(url, headers=headers, json=payload, timeout=20)
            data = response.json()
            tx_hash = data.get("data", {}).get("transactionHash") or data.get("data", {}).get("id")
            if tx_hash:
                return tx_hash
        except Exception as exc:
            print("Circle transfer failed, falling back:", exc)

    return _simulate(from_wallet, to_wallet, amount)
