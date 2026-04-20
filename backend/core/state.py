state = {
    "entities": {},
    "balances": {},
    "events": [],
}


def load_state():
    """Return shared in-memory state."""
    return state


def save_state(new_state):
    """Update shared in-memory state."""
    state.clear()
    state.update(new_state)
    return state
