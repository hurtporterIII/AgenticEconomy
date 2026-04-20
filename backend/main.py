from fastapi import FastAPI

from api.endpoints import router
from core.loop import run_loop
from core.state import state


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

    state["entities"]["worker_1"] = {"id": "worker_1", "type": "worker"}
    state["entities"]["thief_1"] = {"id": "thief_1", "type": "thief"}
    state["entities"]["cop_1"] = {"id": "cop_1", "type": "cop", "target": None}
    state["entities"]["bank_1"] = {"id": "bank_1", "type": "bank"}

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
