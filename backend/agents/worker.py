import math


MINE_ZONE = (2704.0, 1712.0)  # B11
MINE_WORK_RADIUS = 180.0
HOME_ZONE = (912.0, 1168.0)   # B08
HOME_STORE_RADIUS = 170.0


def handle_worker(worker, state):
    """
    Deterministic worker loop:
    1) Go to mine
    2) Earn at mine
    3) Return home
    4) Store earnings
    5) Repeat
    """
    from bank.bank import credit, debit

    balances = state.setdefault("balances", {})
    balances.setdefault(worker["id"], 0.0)

    personality = worker.setdefault("personality", {})
    effort = float(personality.get("effort", 0.6))
    efficiency = float(personality.get("efficiency", 0.55))
    reliability = float(personality.get("reliability", 0.7))

    economy = state.setdefault("economy", {})
    multipliers = economy.get("multipliers", {})
    worker_income_multiplier = float(multipliers.get("worker_income", 1.0))
    worker_tax_rate = float(multipliers.get("worker_tax", 0.0))
    regime = economy.get("regime", "balanced")

    cost = round(0.0015 + effort * 0.0025, 6)
    base_reward = round(3.0 + effort * 2.5 + efficiency * 2.5, 6)
    reward = round(base_reward * worker_income_multiplier, 6)
    tax_amount = round(reward * worker_tax_rate, 6)
    carried_cash = float(worker.get("carried_cash", 0.0) or 0.0)
    worker.setdefault("home_storage", 0.0)

    wx = float(worker.get("x", 0.0) or 0.0)
    wy = float(worker.get("y", 0.0) or 0.0)
    mine_distance = math.hypot(wx - MINE_ZONE[0], wy - MINE_ZONE[1])
    home_distance = math.hypot(wx - HOME_ZONE[0], wy - HOME_ZONE[1])
    returning_home = str(worker.get("haul_mode", "")) == "return_home" or str(worker.get("work_route", "")) == "to_home"

    # Return-home leg: store money once home is reached.
    if returning_home:
        if home_distance > HOME_STORE_RADIUS:
            worker["top_action"] = "return_home"
            worker["work_route"] = "to_home"
            worker["haul_mode"] = "return_home"
            state.setdefault("events", []).append(
                {
                    "type": "worker_commute_home",
                    "worker_id": worker["id"],
                    "distance_to_home": round(home_distance, 2),
                    "regime": regime,
                    "network": "Arc",
                    "asset": "USDC",
                }
            )
            return

        stored = round(max(0.0, carried_cash), 6)
        worker["home_storage"] = round(float(worker.get("home_storage", 0.0) or 0.0) + stored, 6)
        worker["carried_cash"] = 0.0
        worker["haul_mode"] = ""
        worker["work_route"] = "to_mine"
        worker["top_action"] = "store_home"
        state.setdefault("events", []).append(
            {
                "type": "worker_store_home",
                "worker_id": worker["id"],
                "amount": stored,
                "home_storage": worker["home_storage"],
                "regime": regime,
                "network": "Arc",
                "asset": "USDC",
            }
        )
        return

    # Outbound leg: commute to mine until in range.
    if mine_distance > MINE_WORK_RADIUS:
        worker["top_action"] = "commute_mine"
        worker["work_route"] = "to_mine"
        state.setdefault("events", []).append(
            {
                "type": "worker_commute_mine",
                "worker_id": worker["id"],
                "distance_to_mine": round(mine_distance, 2),
                "regime": regime,
                "network": "Arc",
                "asset": "USDC",
            }
        )
        return

    # At mine: execute one earn cycle, then force return home.
    fee_tx = debit(worker["id"], cost, None)
    reward_tx = credit(worker["id"], reward, None)
    tax_tx = None
    if tax_amount > 0:
        tax_tx = debit(worker["id"], tax_amount, None)

    net_gain = round(reward - cost - tax_amount, 6)
    worker["carried_cash"] = round(float(worker.get("carried_cash", 0.0) or 0.0) + max(0.0, net_gain), 6)
    worker["haul_mode"] = "return_home"
    worker["work_route"] = "to_home"
    worker["top_action"] = "return_home"

    state.setdefault("events", []).append(
        {
            "type": "worker_earn",
            "worker_id": worker["id"],
            "cost": cost,
            "base_reward": base_reward,
            "reward": reward,
            "worker_tax": tax_amount,
            "net_gain": net_gain,
            "carried_cash": worker["carried_cash"],
            "regime": regime,
            "regime_multipliers": {"worker_income": worker_income_multiplier, "worker_tax": worker_tax_rate},
            "personality": {
                "effort": effort,
                "efficiency": efficiency,
                "reliability": reliability,
            },
            "tx_hash": reward_tx,
            "tx_steps": [fee_tx, reward_tx] + ([tax_tx] if tax_tx else []),
            "network": "Arc",
            "asset": "USDC",
        }
    )
