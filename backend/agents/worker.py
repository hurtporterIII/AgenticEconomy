def handle_worker(worker, state):
    """
    Executes worker behavior
    """
    from bank.bank import credit, debit

    balances = state.setdefault("balances", {})
    balances.setdefault(worker["id"], 0.0)

    cost = 0.002
    reward = 5

    fee_tx = debit(worker["id"], cost, None)
    reward_tx = credit(worker["id"], reward, None)
    state.setdefault("events", []).append(
        {
            "type": "worker_earn",
            "worker_id": worker["id"],
            "cost": cost,
            "reward": reward,
            "tx_hash": reward_tx,
            "tx_steps": [fee_tx, reward_tx],
            "network": "Arc",
            "asset": "USDC",
        }
    )
