import os
import re
import time
import uuid
import json
from pathlib import Path

from dotenv import load_dotenv
from core.state import state as shared_state

_repo_root = Path(__file__).resolve().parents[2]
_env_file = _repo_root / ".env"
if _env_file.is_file():
    load_dotenv(_env_file, override=True)
if os.getenv("AGENTIC_SIM_ONLY", "").strip().lower() in {"1", "true", "yes", "on"}:
    os.environ["TX_REAL_MODE"] = "off"
    os.environ["SETTLEMENT_STRATEGY"] = "off"

ARC_TESTNET_USDC = "0x3600000000000000000000000000000000000000"
TERMINAL_STATES = {"COMPLETE", "FAILED", "CANCELLED", "DENIED"}

_TX_API = None
# address (lowercased) -> last unix time we hit Circle faucet for native gas
_NATIVE_DRIP_LAST = {}


def _simulate(from_wallet, to_wallet, amount):
    return f"tx_{from_wallet}_{to_wallet}_{amount}"


def _settlement_config():
    return {
        # sampled: settle a sampled subset on-chain, immediate: submit every intent, off: no real settlement attempts
        "strategy": os.getenv("SETTLEMENT_STRATEGY", "sampled").lower(),
        "interval_ticks": max(1, int(os.getenv("SETTLEMENT_INTERVAL_TICKS", "4"))),
        "max_real_txs_per_cycle": max(1, int(os.getenv("SETTLEMENT_MAX_REAL_TX_PER_CYCLE", "4"))),
        "sample_amount": max(0.0001, float(os.getenv("SETTLEMENT_SAMPLE_AMOUNT", "0.001"))),
        "max_pending_intents": max(100, int(os.getenv("SETTLEMENT_MAX_PENDING_INTENTS", "2000"))),
        "merge_window": max(10, int(os.getenv("SETTLEMENT_MERGE_WINDOW", "200"))),
    }


def _settlement_state():
    settlement = shared_state.setdefault("settlement", {})
    config = _settlement_config()
    settlement["strategy"] = config["strategy"]
    settlement["interval_ticks"] = config["interval_ticks"]
    settlement["max_real_txs_per_cycle"] = config["max_real_txs_per_cycle"]
    settlement["sample_amount"] = config["sample_amount"]
    settlement["max_pending_intents"] = config["max_pending_intents"]
    settlement["merge_window"] = config["merge_window"]
    settlement.setdefault("pending_intents", [])
    settlement.setdefault("last_cycle_tick", 0)
    settlement.setdefault("last_cycle_summary", {})
    settlement.setdefault("recent_records", [])
    return settlement


def _metrics():
    metrics = shared_state.setdefault("metrics", {})
    metrics.setdefault("total_spent", 0.0)
    metrics.setdefault("successful_tx", 0)
    metrics.setdefault("failed_tx", 0)
    return metrics


def _diagnostics():
    data = shared_state.setdefault("tx_diagnostics", {})
    data.setdefault("last_mode", "simulate")
    data.setdefault("last_status", "init")
    data.setdefault("last_error", None)
    data.setdefault("last_failure_reason", None)
    data.setdefault("last_tx_id", None)
    data.setdefault("last_tx_hash", None)
    data.setdefault("real_tx_count", 0)
    data.setdefault("simulated_tx_count", 0)
    data.setdefault("failed_tx_count", 0)
    data.setdefault("real_disabled_until", 0.0)
    data.setdefault("breaker_reason", None)
    data.setdefault("last_native_drip_at", None)
    data.setdefault("last_native_drip_targets", None)
    data.setdefault("last_native_drip_note", None)
    data.setdefault("last_updated", time.time())
    return data


def _record_success(amount, tx_hash, tx_id=None):
    metrics = _metrics()
    metrics["successful_tx"] += 1
    metrics["total_spent"] += float(amount)
    diag = _diagnostics()
    diag["last_mode"] = "real"
    diag["last_status"] = "success"
    diag["last_error"] = None
    diag["last_failure_reason"] = None
    diag["last_tx_id"] = tx_id
    diag["last_tx_hash"] = tx_hash
    diag["real_tx_count"] += 1
    diag["last_updated"] = time.time()


def _record_failure(reason=None, error=None, tx_id=None):
    metrics = _metrics()
    metrics["failed_tx"] += 1
    diag = _diagnostics()
    diag["last_mode"] = "simulate"
    diag["last_status"] = "failure"
    diag["last_error"] = error
    diag["last_failure_reason"] = reason
    diag["last_tx_id"] = tx_id
    diag["failed_tx_count"] += 1
    diag["last_updated"] = time.time()


def _record_simulated():
    diag = _diagnostics()
    diag["simulated_tx_count"] += 1
    diag["last_updated"] = time.time()


def _open_breaker(reason, seconds):
    diag = _diagnostics()
    diag["real_disabled_until"] = time.time() + max(0.0, float(seconds))
    diag["breaker_reason"] = reason
    diag["last_updated"] = time.time()


def _breaker_is_open():
    diag = _diagnostics()
    return time.time() < float(diag.get("real_disabled_until", 0.0))


def _extract_failure_reason(text):
    if not text:
        return "unknown"
    lowered = text.lower()
    if "insufficient token balance" in lowered or "native tokens" in lowered:
        return "insufficient_native_gas"
    if "insufficient_native_token" in lowered or "insufficient native token" in lowered:
        return "insufficient_native_gas"
    if "insufficient" in lowered and "balance" in lowered:
        return "insufficient_balance"
    if "timed out" in lowered or "timeout" in lowered:
        return "timeout"
    if "401" in lowered or "unauthorized" in lowered:
        return "auth_failed"
    if "429" in lowered:
        return "rate_limited"
    if "400" in lowered:
        return "bad_request"
    return "unknown"


def _env_config():
    def _truthy(name, default="0"):
        v = (os.getenv(name, default) or "").strip().lower()
        return v in {"1", "true", "yes", "on"}

    return {
        "api_key": os.getenv("CIRCLE_API_KEY"),
        "entity_secret": os.getenv("CIRCLE_ENTITY_SECRET"),
        "wallet_address": os.getenv("CIRCLE_WALLET_ADDRESS"),
        "destination_address": os.getenv("USDC_DESTINATION_ADDRESS"),
        "host": os.getenv("CIRCLE_W3S_BASE_URL") or os.getenv("CIRCLE_BASE_URL", "https://api.circle.com"),
        "blockchain": os.getenv("CIRCLE_BLOCKCHAIN", "ARC-TESTNET"),
        "token_address": os.getenv("CIRCLE_USDC_TOKEN_ADDRESS", ARC_TESTNET_USDC),
        "fee_level": os.getenv("CIRCLE_FEE_LEVEL", "LOW"),
        # Keep step loop responsive by default; increase only for short proof windows.
        "poll_attempts": max(1, int(os.getenv("CIRCLE_POLL_ATTEMPTS", "1"))),
        "poll_delay_sec": max(0.0, float(os.getenv("CIRCLE_POLL_DELAY_SEC", "0.25"))),
        # auto: try real then simulate fallback, strict: fail hard if real cannot settle, off: simulate only
        "real_mode": os.getenv("TX_REAL_MODE", "auto").lower(),
        # When native gas is low on testnets, ask Circle faucet for native drips (cheap/free vs manual refills).
        "auto_testnet_gas_drip": _truthy("CIRCLE_AUTO_TESTNET_GAS_DRIP", "1"),
        "gas_drip_cooldown_sec": max(60.0, float(os.getenv("CIRCLE_GAS_DRIP_COOLDOWN_SEC", "3600"))),
        "gas_drip_retry_delay_sec": max(0.0, float(os.getenv("CIRCLE_GAS_DRIP_RETRY_DELAY_SEC", "2.0"))),
        # Peer rescue transfer amount (USDC on Arc) before retrying failed tx.
        "peer_rescue_amount": max(0.000001, float(os.getenv("CIRCLE_PEER_RESCUE_AMOUNT", "0.05"))),
        "peer_low_balance_threshold": max(0.0, float(os.getenv("CIRCLE_PEER_LOW_BALANCE_THRESHOLD", "0.10"))),
    }


def _get_tx_api(config):
    global _TX_API
    if _TX_API is not None:
        return _TX_API
    from circle.web3 import developer_controlled_wallets as dcw
    from circle.web3 import utils as circle_utils

    client = circle_utils.init_developer_controlled_wallets_client(
        api_key=config["api_key"],
        entity_secret=config["entity_secret"],
        host=config["host"],
    )
    _TX_API = dcw.TransactionsApi(client)
    return _TX_API


def _is_probable_evm_address(addr):
    if not addr or not isinstance(addr, str):
        return False
    a = addr.strip()
    return bool(re.match(r"^0x[0-9a-fA-F]{40}$", a))


def _parse_testnet_blockchain(blockchain: str):
    try:
        from circle.web3.configurations.models.testnet_blockchain import TestnetBlockchain

        return TestnetBlockchain(blockchain)
    except Exception:
        return None


def _maybe_drip_native_gas_for_addresses(config, addresses):
    """
    Best-effort Circle /v1/faucet/drips for native testnet tokens.
    Returns (dripped_any: bool, note: str)
    """
    if not config.get("auto_testnet_gas_drip"):
        return False, "auto_drip_disabled"

    chain = (config.get("blockchain") or "").strip().upper()
    if not chain.endswith("TESTNET"):
        return False, "not_testnet_blockchain"

    tb = _parse_testnet_blockchain(chain)
    if tb is None:
        return False, "unsupported_blockchain_for_drip"

    now = time.time()
    cooldown = float(config.get("gas_drip_cooldown_sec") or 3600.0)
    targets = []
    for raw in addresses:
        if not _is_probable_evm_address(raw):
            continue
        addr = raw.strip().lower()
        last = float(_NATIVE_DRIP_LAST.get(addr, 0.0))
        if now - last < cooldown:
            continue
        targets.append((raw, addr))

    if not targets:
        return False, "drip_skipped_cooldown_or_no_targets"

    try:
        from circle.web3 import configurations
        from circle.web3 import utils as circle_utils
        from circle.web3.configurations.api.faucet_api import FaucetApi
        from circle.web3.configurations.models.faucet_request import FaucetRequest

        # Ensure configurations client shares the same API key / entity secret context as tx client.
        circle_utils.init_developer_controlled_wallets_client(
            api_key=config["api_key"],
            entity_secret=config["entity_secret"],
            host=config["host"],
        )
        faucet = FaucetApi(api_client=circle_utils.CONF_CLIENT)
    except Exception as exc:
        return False, f"faucet_client_init_failed:{exc}"

    dripped = False
    notes = []
    diag = _diagnostics()
    for raw, addr in targets:
        try:
            req = FaucetRequest(address=raw, blockchain=tb, native=True, usdc=False, eurc=False)
            faucet.request_testnet_tokens(x_request_id=uuid.uuid4(), faucet_request=req)
            dripped = True
            _NATIVE_DRIP_LAST[addr] = now
            notes.append(addr[:10])
        except configurations.ApiException as exc:
            notes.append(f"{addr[:10]}:http_{getattr(exc, 'status', 'unknown')}")
        except Exception as exc:
            notes.append(f"{addr[:10]}:{type(exc).__name__}")

    diag["last_native_drip_at"] = now
    diag["last_native_drip_targets"] = [t[1] for t in targets]
    diag["last_native_drip_note"] = ",".join(notes) if notes else "no_targets"
    diag["last_updated"] = time.time()

    return dripped, diag["last_native_drip_note"]


def _create_and_poll_transfer(
    tx_api,
    config,
    numeric_amount,
    *,
    wallet_address=None,
    destination_address=None,
    token_address=None,
):
    from circle.web3 import developer_controlled_wallets as dcw

    src = wallet_address or config["wallet_address"]
    dst = destination_address or config["destination_address"]
    tok = config["token_address"] if token_address is None else token_address
    create_req = dcw.CreateTransferTransactionForDeveloperRequest.from_dict(
        {
            "amounts": [str(numeric_amount)],
            "destinationAddress": dst,
            "walletAddress": src,
            "blockchain": config["blockchain"],
            "tokenAddress": tok,
            "feeLevel": config["fee_level"],
        }
    )
    created = tx_api.create_developer_transaction_transfer(create_req)
    tx_id = getattr(getattr(created, "data", None), "id", None)
    if not tx_id:
        raise RuntimeError("no_tx_id_returned")

    last_state = None
    last_error_reason = None
    for _ in range(config["poll_attempts"]):
        tx_detail = tx_api.get_transaction(tx_id)
        tx = getattr(getattr(tx_detail, "data", None), "transaction", None)
        tx_hash = getattr(tx, "tx_hash", None)
        tx_state = getattr(getattr(tx, "state", None), "value", None)
        last_state = tx_state
        last_error_reason = getattr(getattr(tx, "error_reason", None), "value", None) or getattr(tx, "error_reason", None)
        if tx_hash and re.match(r"^0x[0-9a-fA-F]+$", tx_hash):
            return tx_hash, tx_id
        if tx_state in TERMINAL_STATES:
            break
        if config["poll_delay_sec"] > 0:
            time.sleep(config["poll_delay_sec"])

    if last_state in TERMINAL_STATES:
        raise RuntimeError(f"tx_terminal_state:{last_state}:{last_error_reason or 'unknown'}:{tx_id}")
    raise RuntimeError(f"tx_not_settled_fast_enough:{tx_id}")


def _safe_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return float(default)


def _resolve_wallet_balance(config, address):
    """
    Return (wallet_id, balance_float) for configured token on the provided address.
    """
    from circle.web3 import developer_controlled_wallets as dcw

    if not _is_probable_evm_address(address):
        return None, 0.0
    tx_api = _get_tx_api(config)
    wallets_api = dcw.WalletsApi(tx_api.api_client)
    resp = wallets_api.get_wallets_with_balances_with_http_info(
        blockchain=config["blockchain"],
        address=address,
        token_address=config["token_address"],
        _preload_content=False,
    )
    raw = getattr(resp, "raw_data", b"{}")
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", errors="replace")
    payload = json.loads(raw or "{}")
    wallets = list(((payload.get("data") or {}).get("wallets")) or [])
    if not wallets:
        return None, 0.0

    wallet = wallets[0]
    wallet_id = wallet.get("id")
    balances = list(wallet.get("tokenBalances") or [])
    if not balances:
        return wallet_id, 0.0
    wanted = (config.get("token_address") or "").lower()
    amount = None
    for bal in balances:
        token = (bal or {}).get("token") or {}
        token_address = (token.get("tokenAddress") or "").lower()
        if wanted and token_address == wanted:
            amount = (bal or {}).get("amount")
            break
    if amount is None:
        amount = (balances[0] or {}).get("amount", 0.0)
    amount = _safe_float(amount, 0.0)
    return wallet_id, amount


def _determine_peer_rescue_direction(config):
    """
    Decide rescue direction based on current balances of both peer wallets.
    Returns dict with source/destination/amount or skip metadata.
    """
    a_addr = config.get("wallet_address")
    b_addr = config.get("destination_address")
    if not (_is_probable_evm_address(a_addr) and _is_probable_evm_address(b_addr)):
        return None

    a_id, a_bal = _resolve_wallet_balance(config, a_addr)
    b_id, b_bal = _resolve_wallet_balance(config, b_addr)
    threshold = float(config.get("peer_low_balance_threshold") or 0.0)
    rescue_amt = float(config.get("peer_rescue_amount") or 0.05)

    if a_bal <= b_bal:
        low_addr, low_bal = a_addr, a_bal
        high_addr, high_bal = b_addr, b_bal
    else:
        low_addr, low_bal = b_addr, b_bal
        high_addr, high_bal = a_addr, a_bal

    if low_bal >= threshold:
        return {
            "action": "skip",
            "reason": "both_above_threshold",
            "a_balance": round(a_bal, 8),
            "b_balance": round(b_bal, 8),
            "a_wallet_id": a_id,
            "b_wallet_id": b_id,
        }

    max_affordable = max(0.0, high_bal - threshold)
    amount = min(rescue_amt, max_affordable)
    if amount <= 0:
        return {
            "action": "skip",
            "reason": "donor_not_above_threshold",
            "a_balance": round(a_bal, 8),
            "b_balance": round(b_bal, 8),
            "a_wallet_id": a_id,
            "b_wallet_id": b_id,
        }

    return {
        "action": "transfer",
        "source_address": high_addr,
        "destination_address": low_addr,
        "amount": round(amount, 8),
        "a_balance": round(a_bal, 8),
        "b_balance": round(b_bal, 8),
        "a_wallet_id": a_id,
        "b_wallet_id": b_id,
    }


def get_tx_runtime_status():
    config = _env_config()
    diag = dict(_diagnostics())
    settlement = _settlement_state()
    return {
        "config": {
            "has_circle_api_key": bool(config["api_key"]),
            "has_entity_secret": bool(config["entity_secret"]),
            "has_wallet_address": bool(config["wallet_address"]),
            "has_destination_address": bool(config["destination_address"]),
            "wallet_address": config["wallet_address"],
            "destination_address": config["destination_address"],
            "host": config["host"],
            "blockchain": config["blockchain"],
            "token_address": config["token_address"],
            "fee_level": config["fee_level"],
            "poll_attempts": config["poll_attempts"],
            "poll_delay_sec": config["poll_delay_sec"],
            "real_mode": config["real_mode"],
            "auto_testnet_gas_drip": config["auto_testnet_gas_drip"],
            "gas_drip_cooldown_sec": config["gas_drip_cooldown_sec"],
            "peer_rescue_amount": config["peer_rescue_amount"],
            "peer_low_balance_threshold": config["peer_low_balance_threshold"],
        },
        "diagnostics": diag,
        "metrics": dict(_metrics()),
        "settlement": {
            "strategy": settlement.get("strategy"),
            "interval_ticks": settlement.get("interval_ticks"),
            "max_real_txs_per_cycle": settlement.get("max_real_txs_per_cycle"),
            "sample_amount": settlement.get("sample_amount"),
            "pending_intents": len(settlement.get("pending_intents", [])),
            "last_cycle_tick": settlement.get("last_cycle_tick"),
            "last_cycle_summary": settlement.get("last_cycle_summary"),
        },
    }


def inspect_transaction(tx_id):
    config = _env_config()
    if not tx_id:
        raise ValueError("tx_id is required")
    if not config["api_key"] or not config["entity_secret"]:
        raise RuntimeError("missing_circle_env")

    tx_api = _get_tx_api(config)
    tx_detail = tx_api.get_transaction(tx_id)
    tx = getattr(getattr(tx_detail, "data", None), "transaction", None)
    state_value = getattr(getattr(tx, "state", None), "value", None)
    error_reason = getattr(getattr(tx, "error_reason", None), "value", None) or getattr(tx, "error_reason", None)
    tx_hash = getattr(tx, "tx_hash", None)
    return {
        "id": getattr(tx, "id", None),
        "state": state_value,
        "tx_hash": tx_hash,
        "error_reason": str(error_reason) if error_reason is not None else None,
        "is_real_hash": bool(tx_hash and re.match(r"^0x[0-9a-fA-F]+$", str(tx_hash))),
    }


def record_payment_intent(from_wallet, to_wallet, amount, metadata=None):
    """
    Record an in-sim payment intent and return an intent hash.
    Real settlement is handled by execute_settlement_cycle() or immediate mode.
    """
    settlement = _settlement_state()
    try:
        numeric_amount = float(amount)
    except (TypeError, ValueError):
        return _simulate(from_wallet, to_wallet, amount)
    if numeric_amount <= 0:
        return _simulate(from_wallet, to_wallet, amount)

    if settlement.get("strategy") == "immediate":
        return submit_transaction(from_wallet, to_wallet, numeric_amount)

    pending = settlement.setdefault("pending_intents", [])
    merge_window = int(settlement.get("merge_window", 200))
    max_pending = int(settlement.get("max_pending_intents", 2000))
    meta = metadata or {}

    # Coalesce repeated intents to keep queue bounded under load.
    start = max(0, len(pending) - merge_window)
    for idx in range(len(pending) - 1, start - 1, -1):
        intent = pending[idx]
        if (
            intent.get("from_wallet") == str(from_wallet)
            and intent.get("to_wallet") == str(to_wallet)
            and (intent.get("metadata", {}) or {}).get("kind") == meta.get("kind")
        ):
            intent["amount"] = round(float(intent.get("amount", 0.0)) + numeric_amount, 6)
            intent["merged_count"] = int(intent.get("merged_count", 1)) + 1
            return str(intent.get("intent_id"))

    if len(pending) >= max_pending:
        # Backpressure: settle this payment immediately at sampled amount.
        sampled = min(numeric_amount, float(settlement.get("sample_amount", 0.001)))
        return submit_transaction(from_wallet, to_wallet, sampled)

    intent_id = f"intent_{uuid.uuid4().hex[:12]}"
    pending.append(
        {
            "intent_id": intent_id,
            "from_wallet": str(from_wallet),
            "to_wallet": str(to_wallet),
            "amount": numeric_amount,
            "metadata": meta,
            "created_at": time.time(),
            "created_tick": int(shared_state.setdefault("economy", {}).get("tick", 0)),
            "merged_count": 1,
        }
    )
    return intent_id


def execute_settlement_cycle(shared, tick):
    """
    Periodically settle sampled intents on-chain to preserve realism and budget.
    Returns cycle summary when a cycle runs, else None.
    """
    settlement = _settlement_state()
    strategy = settlement.get("strategy", "sampled")
    if strategy == "off":
        return None
    if strategy != "immediate" and int(tick) % int(settlement.get("interval_ticks", 5)) != 0:
        return None

    pending = list(settlement.get("pending_intents", []))
    if not pending:
        summary = {
            "tick": int(tick),
            "strategy": strategy,
            "processed_intents": 0,
            "submitted_real_txs": 0,
            "real_hashes": 0,
            "sim_hashes": 0,
            "settled_amount": 0.0,
            "remaining_intents": 0,
        }
        settlement["last_cycle_tick"] = int(tick)
        settlement["last_cycle_summary"] = summary
        return summary

    limit = int(settlement.get("max_real_txs_per_cycle", 3))
    sample_amount = float(settlement.get("sample_amount", 0.001))
    to_process = pending[:limit]
    remaining = pending[limit:]

    real_hashes = 0
    sim_hashes = 0
    settled_amount = 0.0
    settlement_records = []
    for intent in to_process:
        amount = float(intent.get("amount", 0.0))
        amount_to_submit = amount if strategy == "immediate" else min(amount, sample_amount)
        tx_hash = submit_transaction(intent.get("from_wallet"), intent.get("to_wallet"), amount_to_submit)
        is_real = bool(re.match(r"^0x[0-9a-fA-F]+$", str(tx_hash)))
        real_hashes += 1 if is_real else 0
        sim_hashes += 0 if is_real else 1
        settled_amount += amount_to_submit
        settlement_records.append(
            {
                "intent_id": intent.get("intent_id"),
                "from_wallet": intent.get("from_wallet"),
                "to_wallet": intent.get("to_wallet"),
                "tx_hash": tx_hash,
                "amount_submitted": amount_to_submit,
                "is_real": is_real,
            }
        )

    settlement["pending_intents"] = remaining
    history = settlement.setdefault("recent_records", [])
    now = time.time()
    for rec in settlement_records:
        history.append(
            {
                "tick": int(tick),
                "ts_epoch": now,
                "intent_id": rec.get("intent_id"),
                "from_wallet": rec.get("from_wallet"),
                "to_wallet": rec.get("to_wallet"),
                "tx_hash": rec.get("tx_hash"),
                "amount_submitted": rec.get("amount_submitted"),
                "is_real": bool(rec.get("is_real")),
            }
        )
    if len(history) > 1000:
        del history[:-1000]
    summary = {
        "tick": int(tick),
        "strategy": strategy,
        "processed_intents": len(to_process),
        "submitted_real_txs": len(to_process),
        "real_hashes": real_hashes,
        "sim_hashes": sim_hashes,
        "settled_amount": round(settled_amount, 6),
        "remaining_intents": len(remaining),
        "records": settlement_records,
    }
    settlement["last_cycle_tick"] = int(tick)
    settlement["last_cycle_summary"] = summary
    return summary


def submit_transaction(from_wallet, to_wallet, amount):
    """
    Submit via Circle dev-controlled wallets and return tx hash.
    Falls back to simulated tx hash for local continuity.
    """
    config = _env_config()
    try:
        numeric_amount = float(amount)
    except (TypeError, ValueError):
        _record_failure(reason="invalid_amount", error=f"bad amount: {amount}")
        _record_simulated()
        return _simulate(from_wallet, to_wallet, amount)

    if numeric_amount <= 0:
        # Non-economic events can carry a simulated marker hash, but should not
        # be counted as failed settlement attempts.
        _record_simulated()
        return _simulate(from_wallet, to_wallet, amount)

    if config["real_mode"] == "off":
        _record_failure(reason="real_mode_off")
        _record_simulated()
        return _simulate(from_wallet, to_wallet, amount)

    if _breaker_is_open():
        diag = _diagnostics()
        diag["last_mode"] = "simulate"
        diag["last_status"] = "breaker_open"
        diag["last_error"] = None
        diag["last_failure_reason"] = diag.get("breaker_reason")
        _record_simulated()
        return _simulate(from_wallet, to_wallet, amount)

    if not all([config["api_key"], config["entity_secret"], config["wallet_address"], config["destination_address"]]):
        _record_failure(reason="missing_circle_env")
        _record_simulated()
        return _simulate(from_wallet, to_wallet, amount)

    try:
        tx_api = _get_tx_api(config)
        tx_hash, tx_id = _create_and_poll_transfer(tx_api, config, numeric_amount)
        _record_success(numeric_amount, tx_hash, tx_id=tx_id)
        return tx_hash
    except Exception as exc:
        text = str(exc)
        reason = _extract_failure_reason(text)

        # First recovery attempt: bidirectional peer rescue based on lower-balance wallet.
        if reason == "insufficient_native_gas":
            try:
                plan = _determine_peer_rescue_direction(config)
                if plan and plan.get("action") == "transfer":
                    tx_api = _get_tx_api(config)
                    rescue_amount = _safe_float(plan.get("amount"), float(config.get("peer_rescue_amount") or 0.05))
                    rescue_hash, rescue_tx_id = _create_and_poll_transfer(
                        tx_api,
                        config,
                        rescue_amount,
                        wallet_address=plan.get("source_address"),
                        destination_address=plan.get("destination_address"),
                    )
                    diag = _diagnostics()
                    diag["last_native_drip_note"] = (
                        f"peer_rescue_ok:{rescue_tx_id}:{rescue_hash}:"
                        f"{plan.get('source_address')}->{plan.get('destination_address')}"
                    )
                    diag["last_updated"] = time.time()
                    if float(config.get("gas_drip_retry_delay_sec") or 0.0) > 0:
                        time.sleep(float(config["gas_drip_retry_delay_sec"]))
                    tx_hash, tx_id = _create_and_poll_transfer(tx_api, config, numeric_amount)
                    _record_success(numeric_amount, tx_hash, tx_id=tx_id)
                    return tx_hash
                elif plan:
                    text = (
                        f"{text} | peer_rescue_skip:{plan.get('reason')}:"
                        f"a={plan.get('a_balance')} b={plan.get('b_balance')}"
                    )
            except Exception as peer_exc:
                text = f"{text} | peer_rescue_failed:{peer_exc}"
                reason = _extract_failure_reason(text)

        # Fallback recovery attempt: Circle faucet native drips for BOTH sides of the flow.
        if reason == "insufficient_native_gas":
            addrs = [config.get("wallet_address"), config.get("destination_address")]
            dripped, drip_note = _maybe_drip_native_gas_for_addresses(config, addrs)
            if dripped and float(config.get("gas_drip_retry_delay_sec") or 0.0) > 0:
                time.sleep(float(config["gas_drip_retry_delay_sec"]))
            if dripped:
                try:
                    tx_api = _get_tx_api(config)
                    tx_hash, tx_id = _create_and_poll_transfer(tx_api, config, numeric_amount)
                    _record_success(numeric_amount, tx_hash, tx_id=tx_id)
                    return tx_hash
                except Exception as exc2:
                    text = f"{exc2} | post_drip:{drip_note}"
                    reason = _extract_failure_reason(text)
                    exc = exc2
            elif drip_note:
                text = f"{text} | drip:{drip_note}"

        print("Dev wallet tx failed:", exc)
        failed_tx_id = None
        if ":" in text:
            failed_tx_id = text.split(":")[-1].strip()
        _record_failure(reason=reason, error=text, tx_id=failed_tx_id)
        if reason == "insufficient_native_gas":
            _open_breaker(reason, seconds=180)
        elif reason == "rate_limited":
            _open_breaker(reason, seconds=30)
        if config["real_mode"] == "strict":
            raise
        _record_simulated()
        return _simulate(from_wallet, to_wallet, amount)


def probe_real_transaction(amount=0.001):
    tx_hash = submit_transaction("PROBE", "PROBE_DEST", amount)
    return {
        "requested_amount": float(amount),
        "tx_hash": tx_hash,
        "is_real_hash": bool(re.match(r"^0x[0-9a-fA-F]+$", str(tx_hash))),
        "status": get_tx_runtime_status(),
    }
