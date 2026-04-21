import random


WORLD_MIN_X = 50.0
WORLD_MAX_X = 950.0
WORLD_MIN_Y = 50.0
WORLD_MAX_Y = 550.0
MOVE_LERP = 0.18

WORK_ZONE = (200.0, 390.0)
THIEF_ZONE = (530.0, 360.0)
COP_ZONE = (870.0, 330.0)
BANKER_ZONE = (690.0, 140.0)
BANK_ZONE = (690.0, 220.0)


def _clamp_world(x, y):
    return (
        max(WORLD_MIN_X, min(WORLD_MAX_X, float(x))),
        max(WORLD_MIN_Y, min(WORLD_MAX_Y, float(y))),
    )


def _ensure_spatial_fields(entity):
    if "x" not in entity or "y" not in entity:
        x = random.uniform(WORLD_MIN_X, WORLD_MAX_X)
        y = random.uniform(WORLD_MIN_Y, WORLD_MAX_Y)
        entity["x"], entity["y"] = _clamp_world(x, y)
    if "target_x" not in entity or "target_y" not in entity:
        entity["target_x"], entity["target_y"] = _clamp_world(entity["x"], entity["y"])


def _home_zone(entity_type):
    if entity_type == "worker":
        return WORK_ZONE
    if entity_type == "thief":
        return THIEF_ZONE
    if entity_type == "cop":
        return COP_ZONE
    if entity_type == "banker":
        return BANKER_ZONE
    return BANK_ZONE


def _find_target_entity(entities, target_id):
    if not target_id:
        return None
    return entities.get(target_id)


def _choose_entity_by_type(entities, entity_type):
    matches = [e for e in entities.values() if e.get("type") == entity_type]
    if not matches:
        return None
    return random.choice(matches)


def _set_behavior_target(entity, entities):
    entity_type = entity.get("type")
    top_action = str(entity.get("top_action") or "").lower()
    target_id = entity.get("target")

    if entity_type == "worker":
        if "bank" in top_action:
            bank = _choose_entity_by_type(entities, "bank")
            if bank:
                entity["target_x"], entity["target_y"] = _clamp_world(bank["x"], bank["y"])
                return
        if random.random() < 0.25:
            entity["target_x"], entity["target_y"] = _clamp_world(
                WORK_ZONE[0] + random.uniform(-100, 100),
                WORK_ZONE[1] + random.uniform(-70, 70),
            )
            return

    if entity_type == "thief":
        if "bank" in top_action:
            bank = _choose_entity_by_type(entities, "bank")
            if bank:
                entity["target_x"], entity["target_y"] = _clamp_world(bank["x"], bank["y"])
                return
        if "steal" in top_action or random.random() < 0.35:
            candidates = [e for e in entities.values() if e.get("id") != entity.get("id")]
            if candidates:
                target = random.choice(candidates)
                entity["target_x"], entity["target_y"] = _clamp_world(target["x"], target["y"])
                return

    if entity_type == "cop":
        target = _find_target_entity(entities, target_id)
        if target:
            entity["target_x"], entity["target_y"] = _clamp_world(target["x"], target["y"])
            return
        if random.random() < 0.4:
            entity["target_x"], entity["target_y"] = _clamp_world(
                COP_ZONE[0] + random.uniform(-170, 170),
                COP_ZONE[1] + random.uniform(-120, 120),
            )
            return

    if entity_type in {"bank", "banker"}:
        jitter = 18 if entity_type == "banker" else 10
        zone = _home_zone(entity_type)
        entity["target_x"], entity["target_y"] = _clamp_world(
            zone[0] + random.uniform(-jitter, jitter),
            zone[1] + random.uniform(-jitter, jitter),
        )
        return

    zone = _home_zone(entity_type)
    entity["target_x"], entity["target_y"] = _clamp_world(
        zone[0] + random.uniform(-120, 120),
        zone[1] + random.uniform(-90, 90),
    )


def _move_entity(entity):
    _ensure_spatial_fields(entity)
    x = float(entity["x"])
    y = float(entity["y"])
    tx = float(entity["target_x"])
    ty = float(entity["target_y"])
    nx = x + (tx - x) * MOVE_LERP
    ny = y + (ty - y) * MOVE_LERP
    entity["x"], entity["y"] = _clamp_world(nx, ny)


def update_spatial_world(shared):
    entities = shared.setdefault("entities", {})
    for entity in entities.values():
        _ensure_spatial_fields(entity)
    for entity in entities.values():
        _set_behavior_target(entity, entities)
    for entity in entities.values():
        _move_entity(entity)


def _count_population(entities):
    counts = {"worker": 0, "thief": 0, "cop": 0, "banker": 0, "bank": 0}
    for entity in entities.values():
        entity_type = entity.get("type")
        if entity_type in counts:
            counts[entity_type] += 1
    counts["total"] = sum(counts.values())
    return counts


def _ratios(counts):
    total = max(1, counts.get("total", 0))
    return {
        "worker": counts.get("worker", 0) / total,
        "thief": counts.get("thief", 0) / total,
        "cop": counts.get("cop", 0) / total,
        "banker": counts.get("banker", 0) / total,
        "bank": counts.get("bank", 0) / total,
    }


def _regime_from_counts(counts, ratios):
    workers = counts.get("worker", 0)
    thieves = counts.get("thief", 0)
    cops = counts.get("cop", 0)
    total = counts.get("total", 0)

    if total < 4:
        return "bootstrapping"
    if ratios["cop"] >= 0.45 and cops >= max(3, thieves + workers // 2):
        return "police_state"
    if ratios["thief"] >= 0.34 and thieves >= max(2, workers):
        return "decline"
    if ratios["worker"] >= 0.5 and workers > (thieves + cops):
        return "growth"
    return "balanced"


def _regime_profile(regime):
    if regime == "bootstrapping":
        return {
            "narration": "A frontier market is forming; every role still has outsized influence.",
            "multipliers": {
                "worker_income": 1.0,
                "worker_tax": 0.0,
                "theft_success": 1.0,
                "cop_effectiveness": 1.0,
                "api_cost": 1.0,
                "bank_fee": 1.0,
            },
            "ui_phase": "boot",
        }
    if regime == "decline":
        return {
            "narration": "Thief dominance drives decline: workers lose income and theft pressure surges.",
            "multipliers": {
                "worker_income": 0.7,
                "worker_tax": 0.0,
                "theft_success": 1.35,
                "cop_effectiveness": 0.85,
                "api_cost": 1.2,
                "bank_fee": 1.15,
            },
            "ui_phase": "crime",
        }
    if regime == "police_state":
        return {
            "narration": "Police state active: surveillance rises, theft drops, and workers lose 10% to compliance drag.",
            "multipliers": {
                "worker_income": 1.0,
                "worker_tax": 0.10,
                "theft_success": 0.65,
                "cop_effectiveness": 1.4,
                "api_cost": 0.85,
                "bank_fee": 1.2,
            },
            "ui_phase": "stress",
        }
    if regime == "growth":
        return {
            "narration": "Worker-led expansion: production rises, theft edge weakens, and liquidity improves.",
            "multipliers": {
                "worker_income": 1.22,
                "worker_tax": 0.0,
                "theft_success": 0.8,
                "cop_effectiveness": 1.05,
                "api_cost": 0.9,
                "bank_fee": 0.9,
            },
            "ui_phase": "stable",
        }
    return {
        "narration": "Balanced city: production, enforcement, and risk remain in tension.",
        "multipliers": {
            "worker_income": 1.0,
            "worker_tax": 0.0,
            "theft_success": 1.0,
            "cop_effectiveness": 1.0,
            "api_cost": 1.0,
            "bank_fee": 1.0,
        },
        "ui_phase": "flux",
    }


def _compute_stability(ratios):
    target = {"worker": 0.55, "cop": 0.25, "thief": 0.15, "banker": 0.05}
    error = sum(abs(ratios[key] - target[key]) for key in target.keys())
    score = max(0.0, min(100.0, 100.0 - (error * 125.0)))
    return round(score, 2)


def _guidance(counts):
    active_total = max(1, counts["worker"] + counts["cop"] + counts["thief"] + counts["banker"])
    target_mix = {"worker": 0.55, "cop": 0.25, "thief": 0.15, "banker": 0.05}
    recommended = {}
    for role, share in target_mix.items():
        value = int(round(active_total * share))
        recommended[role] = max(1 if active_total > 0 else 0, value)
    adjustments = {role: recommended[role] - counts.get(role, 0) for role in recommended.keys()}
    notes = []
    for role, delta in adjustments.items():
        if delta > 0:
            notes.append(f"Add {delta} {role}(s) for stability.")
        elif delta < 0:
            notes.append(f"Reduce {-delta} {role}(s) to rebalance.")
    if not notes:
        notes.append("Population is near the stable mix.")
    return {
        "target_mix": target_mix,
        "recommended_counts": recommended,
        "adjustments": adjustments,
        "notes": notes[:4],
    }


def update_macro_economy(shared):
    economy = shared.setdefault("economy", {})
    entities = shared.setdefault("entities", {})
    events = shared.setdefault("events", [])

    counts = _count_population(entities)
    ratios = _ratios(counts)
    regime = _regime_from_counts(counts, ratios)
    profile = _regime_profile(regime)
    old_regime = economy.get("regime")

    economy["tick"] = int(economy.get("tick", 0)) + 1
    economy["regime"] = regime
    economy["narration"] = profile["narration"]
    economy["population"] = counts
    economy["ratios"] = ratios
    economy["multipliers"] = profile["multipliers"]
    economy["stability_score"] = _compute_stability(ratios)
    economy["guidance"] = _guidance(counts)
    economy["ui_phase"] = profile["ui_phase"]

    if old_regime != regime:
        events.append(
            {
                "type": "regime_shift",
                "regime": regime,
                "narration": profile["narration"],
                "population": counts,
                "multipliers": profile["multipliers"],
                "stability_score": economy["stability_score"],
                "guidance": economy["guidance"],
                "network": "Arc",
                "asset": "USDC",
            }
        )
    elif economy["tick"] % 10 == 0:
        events.append(
            {
                "type": "economic_guidance",
                "regime": regime,
                "stability_score": economy["stability_score"],
                "guidance": economy["guidance"],
                "network": "Arc",
                "asset": "USDC",
            }
        )


def run_loop(state):
    """
    Main engine loop
    """
    import core.state as state_module
    from agents.banker import handle_bank
    from agents.cop import handle_cop
    from agents.thief import handle_thief
    from agents.worker import handle_worker
    from tx.arc import execute_settlement_cycle
    from utils.helpers import compute_policy_bias, compute_reflection, maybe_reflect

    shared = state_module.state
    if state is not shared:
        shared.clear()
        shared.update(state)

    update_macro_economy(shared)
    tick = int(shared.setdefault("economy", {}).get("tick", 0))
    entities = shared.setdefault("entities", {})
    events = shared.setdefault("events", [])
    pre_event_count = len(events)
    events.append(
        {
            "type": "loop_tick_start",
            "tick": tick,
            "entity_count": len(entities),
            "network": "Arc",
            "asset": "USDC",
        }
    )

    for entity in list(entities.values()):
        entity_type = entity.get("type")
        if entity_type == "worker":
            handle_worker(entity, shared)
        elif entity_type == "thief":
            handle_thief(entity, shared)
        elif entity_type == "cop":
            handle_cop(entity, shared)
        elif entity_type in {"banker", "bank"}:
            handle_bank(entity, shared)

    update_spatial_world(shared)

    economy = shared.setdefault("economy", {})
    settlement_summary = execute_settlement_cycle(shared, economy.get("tick", 0))
    if settlement_summary is not None:
        events.append(
            {
                "type": "settlement_cycle",
                "summary": settlement_summary,
                "network": "Arc",
                "asset": "USDC",
            }
        )

    IMPORTANT_EVENTS = {
        "worker_earn",
        "steal_agent",
        "steal_bank",
        "cop_chase",
        "bank_fee_cycle",
        "credit",
        "debit",
    }

    # Memory ingestion: attach economic deltas to per-agent rolling memory buffers.
    def add_memory(agent_id, event, delta):
        if not agent_id:
            return
        agent = entities.get(agent_id)
        if not isinstance(agent, dict):
            return
        memory = agent.setdefault("memory", [])
        memory.append(
            {
                "type": event.get("type"),
                "delta": float(delta),
                "tick": tick,
            }
        )
        if len(memory) > 15:
            del memory[: len(memory) - 15]

    new_events = list(events[pre_event_count:])
    for event in new_events:
        event_type = str(event.get("type"))
        if event_type not in IMPORTANT_EVENTS:
            continue
        if event_type == "debit":
            add_memory(event.get("agent_id"), event, -float(event.get("amount", 0.0) or 0.0))
        elif event_type == "credit":
            add_memory(event.get("agent_id"), event, float(event.get("amount", 0.0) or 0.0))
        elif event_type == "worker_earn":
            reward = float(event.get("reward", 0.0) or 0.0)
            cost = float(event.get("cost", 0.0) or 0.0)
            tax = float(event.get("worker_tax", 0.0) or 0.0)
            add_memory(event.get("worker_id"), event, reward - cost - tax)
        elif event_type == "worker_support_received":
            add_memory(event.get("worker_id"), event, float(event.get("amount", 0.0) or 0.0))
            add_memory(event.get("bank_id"), event, -float(event.get("amount", 0.0) or 0.0))
        elif event_type == "steal_agent":
            amount = float(event.get("amount", 0.0) or 0.0)
            add_memory(event.get("thief_id"), event, amount)
            add_memory(event.get("target_id"), event, -amount)
        elif event_type == "steal_bank":
            amount = float(event.get("amount", 0.0) or 0.0)
            add_memory(event.get("thief_id"), event, amount)
            add_memory(event.get("bank_id"), event, -amount)
        elif event_type == "thief_deposit":
            amount = float(event.get("amount", 0.0) or 0.0)
            add_memory(event.get("thief_id"), event, -amount)
            add_memory(event.get("bank_id"), event, amount)
        elif event_type == "cop_chase":
            penalty = float(event.get("penalty", 0.0) or 0.0)
            add_memory(event.get("cop_id"), event, 0.3 if event.get("captured") else -0.2)
            if event.get("captured") and penalty > 0:
                add_memory(event.get("target_id"), event, -penalty)
        elif event_type == "api_call":
            add_memory(event.get("agent"), event, -float(event.get("cost", 0.0) or 0.0))
        elif event_type == "bank_fee_cycle":
            add_memory(event.get("bank_id"), event, float(event.get("fee_collected", 0.0) or 0.0))
        elif event_type == "bank_redistribution":
            add_memory(event.get("bank_id"), event, -float(event.get("total_amount", 0.0) or 0.0))
        elif event_type == "bank_anti_hoard_levy":
            add_memory(event.get("bank_id"), event, float(event.get("levy_total", 0.0) or 0.0))

    if tick % 10 == 0:
        for entity in entities.values():
            reflection = compute_reflection(entity)
            entity["reflection"] = reflection
            entity["policy_bias"] = compute_policy_bias(entity)
            maybe_reflect(entity, state=shared, role=entity.get("type"))
            events.append(
                {
                    "type": "agent_reflection",
                    "agent": entity.get("id"),
                    "state": reflection,
                    "network": "Arc",
                    "asset": "USDC",
                }
            )

    metrics = shared.setdefault("metrics", {})
    total_spent = float(metrics.get("total_spent", 0.0))
    successful_tx = int(metrics.get("successful_tx", 0))
    failed_tx = int(metrics.get("failed_tx", 0))
    metrics["cost_per_action"] = total_spent / max(successful_tx, 1)
    metrics["success_rate"] = successful_tx / max(successful_tx + failed_tx, 1)

    if state is not shared:
        state.clear()
        state.update(shared)

    events.append(
        {
            "type": "loop_tick_end",
            "tick": tick,
            "event_count": len(events),
            "successful_tx": int(metrics.get("successful_tx", 0)),
            "failed_tx": int(metrics.get("failed_tx", 0)),
            "network": "Arc",
            "asset": "USDC",
        }
    )
