"""
Deterministic worker economic loop (finite state machine).

Three states, one active at a time:

    to_mine  → earn
    to_bank  → deposit
    to_home  → stash
    ...repeat

Rules:
  - Fixed amounts: EARN == DEPOSIT + HOME.
  - No personality modifiers, no regime multipliers, no randomness.
  - No timing delays (arrival triggers the action immediately).
  - Arrival check is exact: hypot(dx, dy) <= R (R = 10.0 px).
  - Exactly one ledger event per action (no commute spam).
  - Guard: if B11 work treasury < EARN, skip the earn with a
    worker_earn_skipped event. No negative balances anywhere.
"""

import math

from core import locations as _locations
from core.pois import try_poi


# ---------------------------------------------------------------------------
# STATES
# ---------------------------------------------------------------------------
SHIFT_TO_MINE = "to_mine"
SHIFT_TO_BANK = "to_bank"
SHIFT_TO_HOME = "to_home"
_VALID_STATES = {SHIFT_TO_MINE, SHIFT_TO_BANK, SHIFT_TO_HOME}


# ---------------------------------------------------------------------------
# ECONOMY (fixed values — EARN == DEPOSIT + HOME)
# ---------------------------------------------------------------------------
EARN = 0.0001
DEPOSIT = 0.00001
HOME = 0.00009
assert abs(EARN - (DEPOSIT + HOME)) < 1e-12, "economy invariant broken"

# Exact arrival radius used by all three legs (pixels).
ARRIVAL_R = 10.0


# ---------------------------------------------------------------------------
# TARGETS — single source of truth for BOTH the movement target (loop.py
# _set_behavior_target) and the arrival check in this file. If these two
# ever drift apart, the worker will aim at one point and check arrival
# against another and the FSM stalls.
# ---------------------------------------------------------------------------
def _worker_places() -> tuple[tuple[float, float], tuple[float, float], tuple[float, float]]:
    bank_poi = try_poi("bank_customer_spot")
    bank_pt = bank_poi if bank_poi is not None else _locations.point("worker", "bank")
    home_poi = try_poi("worker_home_inside")
    home_pt = home_poi if home_poi is not None else _locations.point("worker", "home")
    return (
        _locations.point("worker", "work"),
        bank_pt,
        home_pt,
    )


def _arrived(wx: float, wy: float, pt: tuple[float, float]) -> bool:
    """Exact-position arrival: within ARRIVAL_R pixels of the target."""
    return math.hypot(wx - pt[0], wy - pt[1]) <= ARRIVAL_R


def _first_bank_id(state) -> str | None:
    for ent in state.setdefault("entities", {}).values():
        if ent.get("type") == "bank" and ent.get("id"):
            return ent.get("id")
    return None


# ---------------------------------------------------------------------------
# FSM
# ---------------------------------------------------------------------------
def handle_worker(worker, state):
    """Advance one tick of the worker FSM.

    On arrival, do exactly one transfer + one ledger event, then flip the
    state. Otherwise do nothing — movement is the loop's job.
    """
    from bank.bank import credit, debit
    from core.state import WORK_TREASURY_ID

    balances = state.setdefault("balances", {})
    balances.setdefault(worker["id"], 0.0)
    worker.setdefault("home_storage", 0.0)

    # Normalize phase. Unknown phase snaps to to_mine (fresh spawn case).
    phase = str(worker.get("worker_shift_phase") or "").strip()
    if phase not in _VALID_STATES:
        phase = SHIFT_TO_MINE
    worker["worker_shift_phase"] = phase

    wx = float(worker.get("x", 0.0) or 0.0)
    wy = float(worker.get("y", 0.0) or 0.0)
    work_pt, bank_pt, home_pt = _worker_places()

    # ------------------------------------------------------------------
    # STATE: to_mine — arrive at work, earn from B11 treasury
    # ------------------------------------------------------------------
    if phase == SHIFT_TO_MINE:
        if not _arrived(wx, wy, work_pt):
            return

        treasury = float(balances.get(WORK_TREASURY_ID, 0.0) or 0.0)
        if treasury < EARN:
            state.setdefault("events", []).append({
                "type": "worker_earn_skipped",
                "worker_id": worker["id"],
                "reason": "work_treasury_empty",
                "treasury_balance": round(treasury, 8),
                "requested": EARN,
            })
            return

        out_tx = debit(WORK_TREASURY_ID, EARN, None, count_lifetime_lost=False)
        in_tx = credit(worker["id"], EARN, None)
        worker["worker_shift_phase"] = SHIFT_TO_BANK
        worker["top_action"] = "earned"
        state.setdefault("events", []).append({
            "type": "worker_earn",
            "worker_id": worker["id"],
            "amount": EARN,
            "payer": WORK_TREASURY_ID,
            "payee": worker["id"],
            "tx_hash": in_tx,
            "tx_steps": [out_tx, in_tx],
            "network": "Arc",
            "asset": "USDC",
        })
        return

    # ------------------------------------------------------------------
    # STATE: to_bank — arrive at bank, deposit fixed nano-amount
    # ------------------------------------------------------------------
    if phase == SHIFT_TO_BANK:
        if not _arrived(wx, wy, bank_pt):
            return

        bank_id = _first_bank_id(state)
        if bank_id is None:
            # Deposit is mandatory in the worker cycle.
            # If bank is unavailable, wait in bank phase.
            return

        liquid = float(balances.get(worker["id"], 0.0) or 0.0)
        if liquid < DEPOSIT:
            # Deposit is mandatory; do not move to home stash without it.
            return

        out_tx = debit(worker["id"], DEPOSIT, None, count_lifetime_lost=False)
        in_tx = credit(bank_id, DEPOSIT, None)
        worker["worker_shift_phase"] = SHIFT_TO_HOME
        worker["top_action"] = "deposited"
        state.setdefault("events", []).append({
            "type": "worker_bank_deposit",
            "worker_id": worker["id"],
            "bank_id": bank_id,
            "amount": DEPOSIT,
            "payer": worker["id"],
            "payee": bank_id,
            "tx_hash": in_tx,
            "tx_steps": [out_tx, in_tx],
            "network": "Arc",
            "asset": "USDC",
        })
        return

    # ------------------------------------------------------------------
    # STATE: to_home — arrive at home, stash fixed nano-amount
    # ------------------------------------------------------------------
    if phase == SHIFT_TO_HOME:
        if not _arrived(wx, wy, home_pt):
            return

        liquid = float(balances.get(worker["id"], 0.0) or 0.0)
        if liquid < HOME:
            # Guard: skip stash if we somehow don't have the expected
            # 0.00009. Cycle continues without going negative.
            worker["worker_shift_phase"] = SHIFT_TO_MINE
            return

        out_tx = debit(worker["id"], HOME, None, count_lifetime_lost=False)
        worker["home_storage"] = round(
            float(worker.get("home_storage", 0.0) or 0.0) + HOME, 8
        )
        worker["worker_shift_phase"] = SHIFT_TO_MINE
        worker["top_action"] = "stashed"
        state.setdefault("events", []).append({
            "type": "worker_store_home",
            "worker_id": worker["id"],
            "amount": HOME,
            "home_storage": worker["home_storage"],
            "tx_hash": out_tx,
            "tx_steps": [out_tx],
            "network": "Arc",
            "asset": "USDC",
        })
        return

    # Fallback (should never hit — _VALID_STATES guard above catches it).
    worker["worker_shift_phase"] = SHIFT_TO_MINE
