def handle_thief(thief, state):
    """
    Executes thief behavior
    """
    import random

    from actions.steal import steal_from_agent, steal_from_bank
    from agents.cop import trigger_cops

    entities = list(state.setdefault("entities", {}).values())
    candidates = [entity for entity in entities if entity.get("id") != thief.get("id")]
    if not candidates:
        return

    target = random.choice(candidates)

    if target.get("type") == "bank":
        steal_from_bank(thief, target, state)
        trigger_cops(thief["id"], state)
    else:
        steal_from_agent(thief, target, state)
        if random.random() < 0.3:
            trigger_cops(thief["id"], state)
