"""
Manual probe: call Circle W3S faucet (/v1/faucet/drips) using values from repo .env.

Does not print secrets. Intended for local debugging only.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

from dotenv import dotenv_values


def _pick(vals: dict, *keys: str) -> str | None:
    for k in keys:
        v = vals.get(k) or os.environ.get(k)
        if v:
            return str(v).strip()
    return None


def _try_drip(faucet, addr: str, tb, *, native: bool, usdc: bool, label: str) -> bool:
    from circle.web3 import configurations
    from circle.web3.configurations.models.faucet_request import FaucetRequest

    req = FaucetRequest(address=addr, blockchain=tb, native=native, usdc=usdc, eurc=False)
    try:
        faucet.request_testnet_tokens(x_request_id=uuid.uuid4(), faucet_request=req, _request_timeout=(10, 30))
        print(f"OK {label}")
        return True
    except configurations.ApiException as e:
        body = getattr(e, "body", None)
        s = str(body) if body else ""
        print(f"FAIL {label} status={getattr(e, 'status', None)} reason={getattr(e, 'reason', None)}")
        if s:
            print("body:", s[:800] + ("..." if len(s) > 800 else ""))
        return False
    except Exception as e:
        print(f"FAIL {label} {type(e).__name__}: {e}")
        return False


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    vals = dotenv_values(repo_root / ".env")

    api_key = _pick(vals, "CIRCLE_API_KEY")
    entity_secret = _pick(vals, "CIRCLE_ENTITY_SECRET")
    host = _pick(vals, "CIRCLE_W3S_BASE_URL", "CIRCLE_BASE_URL") or "https://api.circle.com"
    blockchain = _pick(vals, "CIRCLE_BLOCKCHAIN") or "ARC-TESTNET"
    addr = _pick(vals, "CIRCLE_WALLET_ADDRESS")

    missing = [k for k, v in {
        "CIRCLE_API_KEY": api_key,
        "CIRCLE_ENTITY_SECRET": entity_secret,
        "CIRCLE_WALLET_ADDRESS": addr,
    }.items() if not v]
    if missing:
        print("missing:", ", ".join(missing))
        return 2

    from circle.web3 import utils as circle_utils
    from circle.web3.configurations.api.faucet_api import FaucetApi
    from circle.web3.configurations.models.testnet_blockchain import TestnetBlockchain

    circle_utils.init_developer_controlled_wallets_client(
        api_key=api_key,
        entity_secret=entity_secret,
        host=host,
    )

    tb = TestnetBlockchain(blockchain)
    faucet = FaucetApi(api_client=circle_utils.CONF_CLIENT)

    print(f"host={host}")
    print(f"blockchain={blockchain}")
    print(f"address={addr}")

    ok_native = _try_drip(faucet, addr, tb, native=True, usdc=False, label="drip native=True")
    ok_usdc = _try_drip(faucet, addr, tb, native=False, usdc=True, label="drip usdc=True")
    print("summary:", {"native_drip": ok_native, "usdc_drip": ok_usdc})
    return 0 if (ok_native or ok_usdc) else 1


if __name__ == "__main__":
    raise SystemExit(main())
