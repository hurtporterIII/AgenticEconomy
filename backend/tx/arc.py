import os
import re
import time
import uuid

from dotenv import load_dotenv
from core.state import state as shared_state

load_dotenv(override=True)

ARC_TESTNET_USDC = "0x3600000000000000000000000000000000000000"
TERMINAL_STATES = {"COMPLETE", "FAILED", "CANCELLED", "DENIED"}

_TX_API = None


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
    return {
        "api_key": os.getenv("CIRCLE_API_KEY"),
        "entity_secret": os.getenv("CIRCLE_ENTITY_SECRET"),
        "wallet_address": os.getenv("CIRCLE_WALLET_ADDRESS"),
        "destination_address": os.getenv("USDC_DESTINATION_ADDRESS"),
        "host": os.getenv("CIRCLE_W3S_BASE_URL", "https://api.circle.com"),
        "blockchain": os.getenv("CIRCLE_BLOCKCHAIN", "ARC-TESTNET"),
        "token_address": os.getenv("CIRCLE_USDC_TOKEN_ADDRESS", ARC_TESTNET_USDC),
        "fee_level": os.getenv("CIRCLE_FEE_LEVEL", "LOW"),
        # Keep step loop responsive by default; increase only for short proof windows.
        "poll_attempts": max(1, int(os.getenv("CIRCLE_POLL_ATTEMPTS", "1"))),
        "poll_delay_sec": max(0.0, float(os.getenv("CIRCLE_POLL_DELAY_SEC", "0.25"))),
        # auto: try real then simulate fallback, strict: fail hard if real cannot settle, off: simulate only
        "real_mode": os.getenv("TX_REAL_MODE", "auto").lower(),
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
            "host": config["host"],
            "blockchain": config["blockchain"],
            "token_address": config["token_address"],
            "fee_level": config["fee_level"],
            "poll_attempts": config["poll_attempts"],
            "poll_delay_sec": config["poll_delay_sec"],
            "real_mode": config["real_mode"],
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
                "tx_hash": tx_hash,
                "amount_submitted": amount_to_submit,
                "is_real": is_real,
            }
        )

    settlement["pending_intents"] = remaining
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
        from circle.web3 import developer_controlled_wallets as dcw

        tx_api = _get_tx_api(config)

        create_req = dcw.CreateTransferTransactionForDeveloperRequest.from_dict(
            {
                "amounts": [str(numeric_amount)],
                "destinationAddress": config["destination_address"],
                "walletAddress": config["wallet_address"],
                "blockchain": config["blockchain"],
                "tokenAddress": config["token_address"],
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
                _record_success(numeric_amount, tx_hash, tx_id=tx_id)
                return tx_hash
            if tx_state in TERMINAL_STATES:
                break
            if config["poll_delay_sec"] > 0:
                time.sleep(config["poll_delay_sec"])

        if last_state in TERMINAL_STATES:
            raise RuntimeError(f"tx_terminal_state:{last_state}:{last_error_reason or 'unknown'}:{tx_id}")
        raise RuntimeError(f"tx_not_settled_fast_enough:{tx_id}")
    except Exception as exc:
        text = str(exc)
        reason = _extract_failure_reason(text)
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
