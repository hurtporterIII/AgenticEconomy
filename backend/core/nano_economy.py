"""
Nano-economy hooks: reactive, INFORMATION-DRIVEN fee / theft / recovery
layer that runs AFTER each tick's agent handlers.

Design principle (this refactor):

    NO AGENT ACTS WITHOUT INFORMATION.

    Thieves and cops never scan the world themselves. All non-worker
    economic actions are gated on a single broker — the SPY — who:

        1. Watches workers and emits `worker_stash_intel` when a worker's
           home_storage crosses THEFT_THRESHOLD.
        2. Watches fresh theft events and emits `theft_report_intel`.

    A thief can only steal if it pays the spy for fresh stash intel.
    A cop can only recover if it pays the spy for fresh theft intel.

    The flow each tick:

        worker earns  → (banker fees, as before)
                      → spy scans workers    (creates stash intel)
                      → thief buys stash intel → thief steals
                      → spy scans thefts     (creates theft intel)
                      → cop  buys theft intel → cop  recovers
                      → 50/50 split: bank  +  police_station

    Banker fees still key off `worker_earn` events directly (the bank
    receives the earn transfer as a settlement notification, not a
    scanned balance; it's the same information pattern).

    Constraints honored:
        - Worker FSM is never touched.
        - No balance goes negative (buyers skip when they can't afford
          the intel price; cop recoveries are capped at thief liquidity).
        - Deterministic: FIFO intel queue, round-robin thieves/cops.
        - All monetary actions emit a `tx_hash` via bank.bank.credit/debit.
"""

from core.flags import NANO_ECONOMY_HOOKS
from core.learning import cop_learn_response


# --- Fixed rates (match the "tune_phase" spec exactly) --------------------

BANKER_FEE_RATE = 0.10          # of worker_earn.amount        (spec: 0.10)
THEFT_THRESHOLD = 0.0002        # spy flags any worker above   (spec: 0.0002)
THEFT_RATE = 0.30               # of home_storage              (spec: 0.30)
# Cop recovers a percentage of thief liquid AFTER repeated thefts.
COP_RECOVERY_RATE = 0.45
COP_TRIGGER_THEFTS = 2
COP_BANK_SHARE = 0.50           # of recovered                 (spec: 0.50)
COP_SELF_SHARE = 0.50           # of recovered                 (spec: 0.50)

# Spy intel price defaults to 0.000005 USDC and can be adjusted at runtime.
# Clamp to hackathon-safe range (must stay <= $0.01 per action).
INTEL_PRICE_DEFAULT = 0.000005
INTEL_PRICE_MIN = 0.000001
INTEL_PRICE_MAX = 0.01
# Keep thief active in demo loops: minimal float for paying spy intel when
# repeated penalties/confiscations drive liquid to ~0.
THIEF_MIN_OPERATING_FLOAT = 0.00005

# Worker FSM constants — do NOT edit here. The worker FSM (agents/worker.py)
# is the authority. These mirrors are read-only for the fee-starvation guard
# in apply_banker_fees: "if worker.liquid < DEPOSIT, skip fee" so the FSM
# can always complete its deposit step next tick.
WORKER_DEPOSIT = 0.00001        # must match agents.worker.DEPOSIT
WORKER_HOME = 0.00009           # must match agents.worker.HOME

_ROUND = 10                     # decimal places for nano amounts


def _clamp_intel_price(value):
    try:
        v = float(value)
    except (TypeError, ValueError):
        v = INTEL_PRICE_DEFAULT
    if v < INTEL_PRICE_MIN:
        return INTEL_PRICE_MIN
    if v > INTEL_PRICE_MAX:
        return INTEL_PRICE_MAX
    return round(v, _ROUND)


def _spy_intel_price(state, spy=None):
    if spy is None:
        spy = _first_spy(state)
    fallback = INTEL_PRICE_DEFAULT
    economy = state.setdefault("economy", {})
    if isinstance(economy, dict):
        fallback = economy.get("intel_price", fallback)
    raw = fallback
    if isinstance(spy, dict):
        raw = spy.get("intel_price", fallback)
    price = _clamp_intel_price(raw)
    if isinstance(spy, dict):
        spy["intel_price"] = price
    if isinstance(economy, dict):
        economy["intel_price"] = price
    return price


# ---------------------------------------------------------------------------
# Entity lookups
# ---------------------------------------------------------------------------
def _first_of_type(state, entity_type):
    for ent in state.setdefault("entities", {}).values():
        if ent.get("type") == entity_type:
            return ent
    return None


def _all_of_type(state, entity_type):
    return [
        ent
        for ent in state.setdefault("entities", {}).values()
        if ent.get("type") == entity_type
    ]


def _first_spy(state):
    """Spy is modeled as persona_role='spy' on any entity (currently a
    banker-typed entity, per the registry). Fallback: id=='spy_*' for
    robustness against future renames."""
    for ent in state.setdefault("entities", {}).values():
        if str(ent.get("persona_role", "")).lower() == "spy":
            return ent
    for ent in state.setdefault("entities", {}).values():
        if str(ent.get("id", "")).lower().startswith("spy"):
            return ent
    return None


# ---------------------------------------------------------------------------
# Intel queue helpers
# ---------------------------------------------------------------------------
def _intel_queue(state):
    return state.setdefault("spy_intel_queue", [])


def _next_intel_id(state):
    n = int(state.get("_spy_intel_counter", 0) or 0) + 1
    state["_spy_intel_counter"] = n
    return f"intel_{n}"


def _pop_first_intel(queue, kind):
    """FIFO pop of the oldest unconsumed intel of `kind`. Returns (intel, idx)
    or (None, -1)."""
    for idx, intel in enumerate(queue):
        if not isinstance(intel, dict):
            continue
        if intel.get("consumed"):
            continue
        if intel.get("kind") != kind:
            continue
        return intel, idx
    return None, -1


# ---------------------------------------------------------------------------
# 1) BANKER FEES — reacts to fresh worker_earn events (unchanged behavior)
# ---------------------------------------------------------------------------
def apply_banker_fees(state):
    """For every unprocessed worker_earn event, debit a fee from the worker
    and credit the bank. Idempotent via `_nano_fee_applied` on the source
    event."""
    if not NANO_ECONOMY_HOOKS:
        return

    from bank.bank import credit, debit

    events = state.setdefault("events", [])
    balances = state.setdefault("balances", {})
    bank = _first_of_type(state, "bank")
    # Keep redistribution alive even when no dedicated bank entity exists in
    # the demo mix; route the bank share to banker treasury as fallback.
    if bank is None:
        bank = _first_of_type(state, "banker")
    if bank is None:
        return

    bank_id = bank["id"]
    banker = _first_of_type(state, "banker")
    banker_id = banker["id"] if banker else None

    new_events = []
    scan_end = len(events)
    for idx in range(scan_end):
        ev = events[idx]
        if not isinstance(ev, dict):
            continue
        if ev.get("type") != "worker_earn":
            continue
        if ev.get("_nano_fee_applied"):
            continue
        worker_id = ev.get("worker_id")
        earn_amount = float(ev.get("amount", 0.0) or 0.0)
        fee = round(earn_amount * BANKER_FEE_RATE, _ROUND)
        if fee <= 0 or not worker_id:
            ev["_nano_fee_applied"] = True
            continue
        liquid = float(balances.get(worker_id, 0.0) or 0.0)
        # Stability guard: do NOT fee a worker whose liquid is at or below
        # WORKER_DEPOSIT. If we did, the FSM's next `worker_bank_deposit`
        # step would fail, breaking the ≥80% stash-success invariant.
        # Strictly stronger than "liquid < fee".
        if liquid < fee or (liquid - fee) < WORKER_DEPOSIT:
            ev["_nano_fee_applied"] = True
            new_events.append(
                {
                    "type": "bank_fee_skipped",
                    "worker_id": worker_id,
                    "bank_id": bank_id,
                    "reason": "protect_worker_deposit",
                    "requested": fee,
                    "liquid": round(liquid, _ROUND),
                    "min_post_fee_liquid": WORKER_DEPOSIT,
                    "network": "Arc",
                    "asset": "USDC",
                }
            )
            continue
        tx_debit = debit(worker_id, fee, None)
        tx_credit = credit(bank_id, fee, None)
        ev["_nano_fee_applied"] = True
        new_events.append(
            {
                "type": "bank_fee_nano",
                "worker_id": worker_id,
                "bank_id": bank_id,
                "banker_id": banker_id,
                "amount": fee,
                "rate": BANKER_FEE_RATE,
                "source_earn_amount": earn_amount,
                "payer": worker_id,
                "payee": bank_id,
                "tx_hash": tx_credit,
                "tx_steps": [tx_debit, tx_credit],
                "network": "Arc",
                "asset": "USDC",
            }
        )
    events.extend(new_events)


# ---------------------------------------------------------------------------
# 2) SPY WORKER SCAN — creates worker_stash_intel entries
# ---------------------------------------------------------------------------
def apply_spy_worker_scan(state):
    """Spy scans workers; any worker with home_storage above the threshold
    that hasn't already been reported gets an intel entry in the queue."""
    if not NANO_ECONOMY_HOOKS:
        return

    spy = _first_spy(state)
    if spy is None:
        return

    queue = _intel_queue(state)
    events = state.setdefault("events", [])
    current_tick = int(state.setdefault("economy", {}).get("tick", 0) or 0)

    for worker in _all_of_type(state, "worker"):
        home_storage = float(worker.get("home_storage", 0.0) or 0.0)
        if home_storage <= THEFT_THRESHOLD:
            # Drain any stale flag so the next time they cross the line,
            # a fresh intel is created.
            if worker.get("_spy_stash_intel_id"):
                worker.pop("_spy_stash_intel_id", None)
            continue
        if worker.get("_spy_stash_intel_id"):
            # Already has an outstanding, not-yet-consumed report. Don't spam.
            continue
        intel_id = _next_intel_id(state)
        intel = {
            "id": intel_id,
            "kind": "worker_stash",
            "target_worker": worker["id"],
            "estimated_value": round(home_storage, _ROUND),
            "created_tick": current_tick,
            "spy_id": spy["id"],
            "consumed": False,
            "buyer": None,
            "buyer_type": None,
        }
        queue.append(intel)
        worker["_spy_stash_intel_id"] = intel_id
        events.append(
            {
                "type": "spy_intel_created",
                "intel_id": intel_id,
                "intel_kind": "worker_stash",
                "target_worker": worker["id"],
                "estimated_value": intel["estimated_value"],
                "spy_id": spy["id"],
                "network": "Arc",
                "asset": "USDC",
            }
        )


# ---------------------------------------------------------------------------
# 3) THIEF STEALS — gated on purchased stash intel (NO direct scanning)
# ---------------------------------------------------------------------------
def apply_thief_steals(state):
    """For every thief this tick, attempt to buy ONE fresh worker_stash
    intel from the spy and act on it. A thief NEVER scans workers or
    reads balances directly: no intel → no theft.

    Round-robin across thieves so a multi-thief scenario consumes queued
    intel fairly."""
    if not NANO_ECONOMY_HOOKS:
        return

    from bank.bank import credit, debit, record_lifetime_lost

    events = state.setdefault("events", [])
    balances = state.setdefault("balances", {})
    queue = _intel_queue(state)
    thieves = _all_of_type(state, "thief")
    if not thieves:
        return
    spy = _first_spy(state)
    if spy is None:
        return
    spy_id = spy["id"]
    intel_price = _spy_intel_price(state, spy)
    banker = _first_of_type(state, "banker")
    bank = _first_of_type(state, "bank")

    current_tick = int(state.setdefault("economy", {}).get("tick", 0) or 0)
    entities = state.setdefault("entities", {})
    rr_idx = int(state.get("_nano_theft_rr", 0) or 0)

    # Each thief gets one attempt per tick, processed in round-robin order.
    for _ in range(len(thieves)):
        intel, intel_idx = _pop_first_intel(queue, "worker_stash")
        if intel is None:
            break  # no information, no action
        thief = thieves[rr_idx % len(thieves)]
        rr_idx += 1
        thief_id = thief["id"]

        # --- Pre-flight validation (before spy is paid) ---
        # If the intel is stale (target gone, stash drained below threshold
        # by a prior tick, or rounding-to-zero), discard it WITHOUT charging
        # the thief. This preserves the hard invariant: every paid intel
        # produces exactly one successful steal.
        target_id = intel.get("target_worker")
        worker = entities.get(target_id) if target_id else None
        if not isinstance(worker, dict):
            intel["consumed"] = True
            intel["buyer"] = None
            intel["buyer_type"] = None
            events.append(
                {
                    "type": "spy_intel_discarded",
                    "reason": "target_missing",
                    "intel_id": intel["id"],
                    "intel_kind": "worker_stash",
                    "target_worker": target_id,
                    "network": "Arc",
                    "asset": "USDC",
                }
            )
            continue
        home_storage = float(worker.get("home_storage", 0.0) or 0.0)
        if home_storage <= 0 or home_storage < THEFT_THRESHOLD:
            intel["consumed"] = True
            intel["buyer"] = None
            intel["buyer_type"] = None
            worker.pop("_spy_stash_intel_id", None)
            events.append(
                {
                    "type": "spy_intel_discarded",
                    "reason": "home_storage_below_threshold",
                    "intel_id": intel["id"],
                    "intel_kind": "worker_stash",
                    "target_worker": target_id,
                    "home_storage": round(home_storage, _ROUND),
                    "threshold": THEFT_THRESHOLD,
                    "network": "Arc",
                    "asset": "USDC",
                }
            )
            continue
        stolen = round(home_storage * THEFT_RATE, _ROUND)
        if stolen > home_storage:
            stolen = round(home_storage, _ROUND)
        if stolen <= 0:
            intel["consumed"] = True
            intel["buyer"] = None
            intel["buyer_type"] = None
            worker.pop("_spy_stash_intel_id", None)
            events.append(
                {
                    "type": "spy_intel_discarded",
                    "reason": "rounded_to_zero",
                    "intel_id": intel["id"],
                    "intel_kind": "worker_stash",
                    "target_worker": target_id,
                    "network": "Arc",
                    "asset": "USDC",
                }
            )
            continue

        # --- Also validate the thief can actually afford the spy ---
        thief_liquid = float(balances.get(thief_id, 0.0) or 0.0)
        # If the thief is under water, normalize to 0 so debt doesn't freeze
        # the behavior loop forever.
        if thief_liquid < 0:
            balances[thief_id] = 0.0
            thief_liquid = 0.0
        if thief_liquid < intel_price:
            # Try to fund a tiny operating float from banker/bank so the thief
            # can keep buying intel and moving in the simulation.
            source_id = None
            if isinstance(banker, dict):
                source_id = banker.get("id")
            elif isinstance(bank, dict):
                source_id = bank.get("id")
            source_liquid = float(balances.get(source_id, 0.0) or 0.0) if source_id else 0.0
            needed = max(0.0, THIEF_MIN_OPERATING_FLOAT - thief_liquid)
            topup = round(min(needed, source_liquid), _ROUND)
            if source_id and topup >= intel_price:
                tx_src = debit(source_id, topup, None)
                tx_dst = credit(thief_id, topup, None)
                thief_liquid = float(balances.get(thief_id, 0.0) or 0.0)
                events.append(
                    {
                        "type": "thief_operating_stipend",
                        "thief_id": thief_id,
                        "source_id": source_id,
                        "amount": topup,
                        "payer": source_id,
                        "payee": thief_id,
                        "tx_hash": tx_dst,
                        "tx_steps": [tx_src, tx_dst],
                        "network": "Arc",
                        "asset": "USDC",
                    }
                )
            if thief_liquid >= intel_price:
                # Re-check this intel now that float is restored.
                pass
            else:
                events.append(
                    {
                        "type": "spy_sell_info_skipped",
                        "intel_id": intel["id"],
                        "intel_kind": "worker_stash",
                        "buyer_id": thief_id,
                        "buyer_type": "thief",
                        "spy_id": spy_id,
                        "reason": "buyer_insufficient_liquid",
                        "price": intel_price,
                        "liquid": round(thief_liquid, _ROUND),
                        "network": "Arc",
                        "asset": "USDC",
                    }
                )
                # Leave intel in place (un-consumed) for a later tick or buyer.
                continue

        # --- Phase A: thief pays spy (intel is now guaranteed to fire) ---
        tx_pay_debit = debit(thief_id, intel_price, None)
        tx_pay_credit = credit(spy_id, intel_price, None)
        events.append(
            {
                "type": "spy_sell_info",
                "intel_id": intel["id"],
                "intel_kind": "worker_stash",
                "target_worker": target_id,
                "buyer_id": thief_id,
                "buyer_type": "thief",
                "spy_id": spy_id,
                "amount": intel_price,
                "payer": thief_id,
                "payee": spy_id,
                "tx_hash": tx_pay_credit,
                "tx_steps": [tx_pay_debit, tx_pay_credit],
                "network": "Arc",
                "asset": "USDC",
            }
        )

        # --- Phase B: thief steals (validated amount, no negative storage) ---
        intel["consumed"] = True
        intel["buyer"] = thief_id
        intel["buyer_type"] = "thief"
        worker.pop("_spy_stash_intel_id", None)
        worker["home_storage"] = round(max(0.0, home_storage - stolen), _ROUND)
        record_lifetime_lost(target_id, float(stolen))
        worker["_nano_theft_last_tick"] = current_tick
        tx_steal_credit = credit(thief_id, stolen, None)
        events.append(
            {
                "type": "steal_agent",
                "thief_id": thief_id,
                "target_id": target_id,       # legacy key used by memory-ingestion
                "worker_id": target_id,       # worker ledger filters on worker_id
                "amount": stolen,
                "rate": THEFT_RATE,
                "intel_id": intel["id"],
                "remaining_home_storage": worker["home_storage"],
                "payer": target_id,
                "payee": thief_id,
                "tx_hash": tx_steal_credit,
                "tx_steps": [tx_steal_credit],
                "network": "Arc",
                "asset": "USDC",
            }
        )

    state["_nano_theft_rr"] = rr_idx


# ---------------------------------------------------------------------------
# 4) SPY THEFT SCAN — creates theft_report_intel entries
# ---------------------------------------------------------------------------
def apply_spy_theft_scan(state):
    """For each fresh steal_agent event (marked with `_spy_theft_reported`
    for idempotency), enqueue a theft_report intel so a cop can buy it."""
    if not NANO_ECONOMY_HOOKS:
        return

    spy = _first_spy(state)
    if spy is None:
        return

    events = state.setdefault("events", [])
    queue = _intel_queue(state)
    current_tick = int(state.setdefault("economy", {}).get("tick", 0) or 0)
    thief_strikes = state.setdefault("_thief_strike_count", {})

    new_events = []
    scan_end = len(events)
    for idx in range(scan_end):
        ev = events[idx]
        if not isinstance(ev, dict):
            continue
        if ev.get("type") != "steal_agent":
            continue
        if ev.get("_spy_theft_reported"):
            continue
        thief_id = ev.get("thief_id")
        stolen = float(ev.get("amount", 0.0) or 0.0)
        if not thief_id or stolen <= 0:
            ev["_spy_theft_reported"] = True
            continue
        intel_id = _next_intel_id(state)
        intel = {
            "id": intel_id,
            "kind": "theft_report",
            "thief_id": thief_id,
            "target_worker": ev.get("target_id") or ev.get("worker_id"),
            "stolen": round(stolen, _ROUND),
            "source_intel_id": ev.get("intel_id"),
            "created_tick": current_tick,
            "spy_id": spy["id"],
            "consumed": False,
            "buyer": None,
            "buyer_type": None,
        }
        queue.append(intel)
        thief_strikes[thief_id] = int(thief_strikes.get(thief_id, 0) or 0) + 1
        ev["_spy_theft_reported"] = True
        new_events.append(
            {
                "type": "spy_intel_created",
                "intel_id": intel_id,
                "intel_kind": "theft_report",
                "thief_id": thief_id,
                "stolen": intel["stolen"],
                "strike_count": int(thief_strikes.get(thief_id, 0) or 0),
                "spy_id": spy["id"],
                "network": "Arc",
                "asset": "USDC",
            }
        )
    events.extend(new_events)


# ---------------------------------------------------------------------------
# 5) COP RECOVERY — gated on purchased theft intel (NO direct scanning)
# ---------------------------------------------------------------------------
def apply_cop_recovery(state):
    """For every cop this tick, attempt to buy ONE fresh theft_report
    intel from the spy and act on it. A cop NEVER scans thieves or
    events directly: no intel → no recovery.

    50% of recovered funds go to the bank (redistribution), 50% go to
    the cop's own balance (the 'police_station' treasury)."""
    if not NANO_ECONOMY_HOOKS:
        return

    from bank.bank import credit, debit

    events = state.setdefault("events", [])
    balances = state.setdefault("balances", {})
    queue = _intel_queue(state)
    cops = _all_of_type(state, "cop")
    if not cops:
        return
    bank = _first_of_type(state, "bank")
    if bank is None:
        bank = _first_of_type(state, "banker")
    if bank is None:
        return
    spy = _first_spy(state)
    if spy is None:
        return
    spy_id = spy["id"]
    intel_price = _spy_intel_price(state, spy)
    bank_id = bank["id"]
    rr_idx = int(state.get("_nano_recovery_rr", 0) or 0)
    thief_strikes = state.setdefault("_thief_strike_count", {})

    for _ in range(len(cops)):
        intel, intel_idx = _pop_first_intel(queue, "theft_report")
        if intel is None:
            break
        cop = cops[rr_idx % len(cops)]
        rr_idx += 1
        cop_id = cop["id"]

        # --- Pre-flight validation (before cop pays spy) ---
        # Discard stale intel WITHOUT charging so the invariant
        # spy_sell_info == cop_recover holds exactly.
        thief_id = intel.get("thief_id")
        stolen = float(intel.get("stolen", 0.0) or 0.0)
        thief_liquid = float(balances.get(thief_id, 0.0) or 0.0)
        strike_count = int(thief_strikes.get(thief_id, 0) or 0)
        if strike_count < COP_TRIGGER_THEFTS:
            events.append(
                {
                    "type": "cop_waiting_threshold",
                    "cop_id": cop_id,
                    "thief_id": thief_id,
                    "intel_id": intel["id"],
                    "strike_count": strike_count,
                    "required_strikes": COP_TRIGGER_THEFTS,
                    "network": "Arc",
                    "asset": "USDC",
                }
            )
            # Keep intel unconsumed until threshold is reached.
            continue

        target = round(thief_liquid * COP_RECOVERY_RATE, _ROUND)
        if target <= 0 or thief_liquid <= 0:
            intel["consumed"] = True
            intel["buyer"] = None
            intel["buyer_type"] = None
            cop_learning = cop_learn_response(state, cop_id, reward=-0.2, mode="intel_empty_target")
            events.append(
                {
                    "type": "spy_intel_discarded",
                    "reason": "thief_empty",
                    "intel_id": intel["id"],
                    "intel_kind": "theft_report",
                    "thief_id": thief_id,
                    "learning": {"cop": cop_learning},
                    "network": "Arc",
                    "asset": "USDC",
                }
            )
            continue

        # Cap at available thief liquid (no negative balance).
        recovered = target if thief_liquid >= target else round(thief_liquid, _ROUND)
        if recovered <= 0:
            intel["consumed"] = True
            intel["buyer"] = None
            intel["buyer_type"] = None
            events.append(
                {
                    "type": "spy_intel_discarded",
                    "reason": "rounded_to_zero",
                    "intel_id": intel["id"],
                    "intel_kind": "theft_report",
                    "thief_id": thief_id,
                    "network": "Arc",
                    "asset": "USDC",
                }
            )
            continue

        cop_liquid = float(balances.get(cop_id, 0.0) or 0.0)
        if cop_liquid < intel_price:
            events.append(
                {
                    "type": "spy_sell_info_skipped",
                    "intel_id": intel["id"],
                    "intel_kind": "theft_report",
                    "buyer_id": cop_id,
                    "buyer_type": "cop",
                    "spy_id": spy_id,
                    "reason": "buyer_insufficient_liquid",
                    "price": intel_price,
                    "liquid": round(cop_liquid, _ROUND),
                    "network": "Arc",
                    "asset": "USDC",
                }
            )
            # Leave intel in queue for a later tick.
            continue

        # --- Phase A: cop pays spy (intel is now guaranteed to fire) ---
        tx_pay_debit = debit(cop_id, intel_price, None)
        tx_pay_credit = credit(spy_id, intel_price, None)
        events.append(
            {
                "type": "spy_sell_info",
                "intel_id": intel["id"],
                "intel_kind": "theft_report",
                "thief_id": thief_id,
                "buyer_id": cop_id,
                "buyer_type": "cop",
                "spy_id": spy_id,
                "amount": intel_price,
                "payer": cop_id,
                "payee": spy_id,
                "tx_hash": tx_pay_credit,
                "tx_steps": [tx_pay_debit, tx_pay_credit],
                "network": "Arc",
                "asset": "USDC",
            }
        )

        # --- Phase B: cop recovers + redistributes 50/50 ---
        intel["consumed"] = True
        intel["buyer"] = cop_id
        intel["buyer_type"] = "cop"
        bank_share = round(recovered * COP_BANK_SHARE, _ROUND)
        cop_share = round(recovered - bank_share, _ROUND)

        tx_recover_debit = debit(thief_id, recovered, None)
        tx_bank_credit = credit(bank_id, bank_share, None) if bank_share > 0 else None
        tx_cop_credit = credit(cop_id, cop_share, None) if cop_share > 0 else None
        steps = [s for s in (tx_recover_debit, tx_bank_credit, tx_cop_credit) if s]

        events.append(
            {
                "type": "cop_recover",
                "cop_id": cop_id,
                "thief_id": thief_id,
                "bank_id": bank_id,
                "intel_id": intel["id"],
                "recovered": recovered,
                "target_recovery": target,
                "source_steal_amount": stolen,
                "strike_count_before_recovery": strike_count,
                "rate": COP_RECOVERY_RATE,
                "payer": thief_id,
                "payee": bank_id,
                "tx_hash": tx_recover_debit,
                "tx_steps": steps,
                "network": "Arc",
                "asset": "USDC",
            }
        )
        thief_strikes[thief_id] = max(0, strike_count - COP_TRIGGER_THEFTS)
        cop_learning = cop_learn_response(state, cop_id, reward=0.3, mode="intel_recovery")
        events[-1]["learning"] = {"cop": cop_learning}
        # Explicit redistribution tx so the 50/50 split is legible in
        # the event stream (primary cop_recover event carries its own
        # tx_hash; this one records the downstream split structure).
        events.append(
            {
                "type": "redistribution",
                "cop_id": cop_id,
                "bank_id": bank_id,
                "police_station_id": cop_id,
                "source_intel_id": intel["id"],
                "recovered": recovered,
                "bank_share": bank_share,
                "cop_share": cop_share,
                "bank_share_rate": COP_BANK_SHARE,
                "cop_share_rate": COP_SELF_SHARE,
                "tx_hash": tx_bank_credit or tx_cop_credit,
                "tx_steps": [tx_bank_credit, tx_cop_credit],
                "network": "Arc",
                "asset": "USDC",
            }
        )

    state["_nano_recovery_rr"] = rr_idx


# ---------------------------------------------------------------------------
# Driver — call this once per tick, AFTER worker/banker/thief/cop handlers.
# ---------------------------------------------------------------------------
def apply_nano_economy(state):
    """Run all hooks in the spec's order:

        earn → banker_fee → (spy sees workers)
             → (thief pays spy) → steal_agent
             → (spy sees theft) → (cop pays spy) → cop_recover → redistribution

    Safe to call every tick. No-op when NANO_ECONOMY_HOOKS is off."""
    if not NANO_ECONOMY_HOOKS:
        return
    apply_banker_fees(state)
    apply_spy_worker_scan(state)
    apply_thief_steals(state)
    apply_spy_theft_scan(state)
    apply_cop_recovery(state)
