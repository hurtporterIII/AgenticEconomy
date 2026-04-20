def run_loop(state):
    """
    Main engine loop
    """
    import core.state as state_module
    from agents.cop import handle_cop
    from agents.thief import handle_thief
    from agents.worker import handle_worker

    shared = state_module.state
    if state is not shared:
        shared.clear()
        shared.update(state)

    for entity in list(shared.setdefault("entities", {}).values()):
        entity_type = entity.get("type")
        if entity_type == "worker":
            handle_worker(entity, shared)
        elif entity_type == "thief":
            handle_thief(entity, shared)
        elif entity_type == "cop":
            handle_cop(entity, shared)

    if state is not shared:
        state.clear()
        state.update(shared)
