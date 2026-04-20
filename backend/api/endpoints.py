from fastapi import APIRouter

from core.loop import run_loop
from core.state import state

router = APIRouter(prefix="/api", tags=["demo"])


def get_state():
    return state


def get_events():
    return state.setdefault("events", [])


def step():
    run_loop(state)
    return {"status": "step complete", "event_count": len(state.setdefault("events", []))}


def spawn_entity(entity_id, entity_type, balance=0.0):
    entities = state.setdefault("entities", {})
    balances = state.setdefault("balances", {})

    entity = {"id": entity_id, "type": entity_type}
    if entity_type == "cop":
        entity["target"] = None

    entities[entity_id] = entity
    balances.setdefault(entity_id, float(balance))
    return entity


@router.get("/state")
def get_state_endpoint():
    return get_state()


@router.get("/events")
def get_events_endpoint():
    return get_events()


@router.post("/step")
def step_endpoint():
    return step()


@router.post("/spawn")
def spawn_endpoint(entity_id: str, entity_type: str, balance: float = 0.0):
    entity = spawn_entity(entity_id=entity_id, entity_type=entity_type, balance=balance)
    return {"status": "spawned", "entity": entity, "balance": state["balances"][entity_id]}
