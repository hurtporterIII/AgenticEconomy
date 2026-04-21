from fastapi import FastAPI

from api.endpoints import router
from core.loop import run_loop
from core.state import default_behavior_settings, default_economy_state, state


def create_app():
    """Create minimal HTTP app for demo endpoints."""
    app = FastAPI(title="AgenticEconomy Demo API")
    app.include_router(router)
    return app


app = create_app()


def _seed_demo_state():
    state.setdefault("entities", {})
    state.setdefault("balances", {})
    state.setdefault("events", [])
    state.setdefault("behavior_settings", default_behavior_settings())
    state.setdefault("economy", default_economy_state())
    state.setdefault("metrics", {})
    state["metrics"].setdefault("total_spent", 0.0)
    state["metrics"].setdefault("successful_tx", 0)
    state["metrics"].setdefault("failed_tx", 0)

    state["entities"]["worker_1"] = {
        "id": "worker_1",
        "type": "worker",
        "x": 180.0,
        "y": 390.0,
        "target_x": 180.0,
        "target_y": 390.0,
    }
    state["entities"]["thief_1"] = {
        "id": "thief_1",
        "type": "thief",
        "x": 530.0,
        "y": 360.0,
        "target_x": 530.0,
        "target_y": 360.0,
    }
    state["entities"]["cop_1"] = {
        "id": "cop_1",
        "type": "cop",
        "target": None,
        "x": 870.0,
        "y": 330.0,
        "target_x": 870.0,
        "target_y": 330.0,
    }
    state["entities"]["bank_1"] = {
        "id": "bank_1",
        "type": "bank",
        "x": 690.0,
        "y": 220.0,
        "target_x": 690.0,
        "target_y": 220.0,
    }

    state["balances"].setdefault("worker_1", 10.0)
    state["balances"].setdefault("thief_1", 1.0)
    state["balances"].setdefault("cop_1", 1.0)
    state["balances"].setdefault("bank_1", 100.0)


def run():
    from agents.cop import handle_cop

    _seed_demo_state()
    handle_cop(state["entities"]["cop_1"], state)

    for _ in range(10):
        run_loop(state)

    metrics = state.setdefault("metrics", {})
    successful_tx = metrics.get("successful_tx", 0)
    failed_tx = metrics.get("failed_tx", 0)
    total_spent = metrics.get("total_spent", 0.0)
    cost_per_action = total_spent / max(successful_tx, 1)
    success_rate = successful_tx / max(successful_tx + failed_tx, 1)

    summary = {
        "type": "tx_summary",
        "total_spent": total_spent,
        "successful_tx": successful_tx,
        "failed_tx": failed_tx,
        "cost_per_action": cost_per_action,
        "success_rate": success_rate,
    }
    state.setdefault("events", []).append(summary)
    print("TX Summary:", summary)

    print("Events:")
    for event in state["events"]:
        print(event)
    print("Transaction count:", len(state["events"]))
    print(
        "Each action triggers a USDC transaction. At sub-cent pricing, "
        "this would not be economically viable on traditional gas systems."
    )


if __name__ == "__main__":
    run()
