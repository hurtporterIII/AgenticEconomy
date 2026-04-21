import random


def safe_get(mapping, key, default=None):
    """Safely read a key from a mapping-like object."""
    if not isinstance(mapping, dict):
        return default
    return mapping.get(key, default)


def clamp(value, low, high):
    return max(low, min(high, value))


RISKY_ACTIONS = ["steal_agent", "steal_bank"]
SAFE_ACTIONS = ["work", "deposit_bank", "patrol"]


def _role_goals(role):
    goals = {
        "worker": {"wealth": 0.7, "safety": 0.55, "stability": 0.65},
        "thief": {"wealth": 0.8, "safety": 0.35, "stability": 0.25},
        "cop": {"wealth": 0.45, "safety": 0.7, "stability": 0.85},
        "banker": {"wealth": 0.6, "safety": 0.75, "stability": 0.9},
        "bank": {"wealth": 0.6, "safety": 0.8, "stability": 0.95},
    }
    return dict(goals.get(role or "worker", {"wealth": 0.5, "safety": 0.5, "stability": 0.5}))


def ensure_mind(agent, role=None):
    agent.setdefault("memory", [])
    agent.setdefault("reflection", "neutral")
    agent.setdefault("policy_bias", {})
    mind = agent.setdefault("mind", {})
    mind.setdefault("memory", [])
    mind.setdefault("reflections", [])
    mind.setdefault("intent", "Observe and adapt")
    mind.setdefault("mood", "neutral")
    mind.setdefault("goals", _role_goals(role or agent.get("type")))
    mind.setdefault("last_reflection_tick", -1)
    mind.setdefault("last_action_tick", -1)
    mind.setdefault("confidence", 0.5)
    return mind


def remember(agent, record, max_memory=100):
    mind = ensure_mind(agent)
    memory = mind.setdefault("memory", [])
    memory.append(record)
    if len(memory) > max_memory:
        del memory[: len(memory) - max_memory]


def compute_reflection(agent):
    memory = agent.get("memory", [])[-15:]
    gains = sum(float(m.get("delta", 0.0) or 0.0) for m in memory if float(m.get("delta", 0.0) or 0.0) > 0)
    losses = abs(sum(float(m.get("delta", 0.0) or 0.0) for m in memory if float(m.get("delta", 0.0) or 0.0) < 0))
    if losses > gains * 1.2:
        return "defensive"
    if gains > losses * 1.5:
        return "aggressive"
    return "balanced"


def compute_policy_bias(agent):
    reflection = str(agent.get("reflection", "balanced"))
    if reflection == "defensive":
        return {"idle": 1.3, "risky": 0.7, "safe": 1.05}
    if reflection == "aggressive":
        return {"risky": 1.3, "safe": 0.8, "idle": 0.9}
    return {}


def maybe_reflect(agent, state=None, role=None):
    """
    Periodically synthesize recent memory into a concise reflection.
    Emits a reflection event into shared state at low frequency.
    """
    mind = ensure_mind(agent, role=role)
    if state is None:
        return None
    tick = int(state.setdefault("economy", {}).get("tick", 0))
    last_tick = int(mind.get("last_reflection_tick", -1))
    if tick - last_tick < 5:
        return None

    recent = mind.get("memory", [])[-20:]
    if not recent:
        return None
    avg_reward = sum(float(item.get("reward", item.get("delta", 0.0)) or 0.0) for item in recent) / max(1, len(recent))
    counts = {}
    for item in recent:
        key = item.get("action", "observe")
        counts[key] = counts.get(key, 0) + 1
    dominant = sorted(counts.items(), key=lambda x: x[1], reverse=True)[0][0]
    mood = "confident" if avg_reward > 0.1 else ("stressed" if avg_reward < -0.1 else "adaptive")
    reflection_state = compute_reflection(agent)

    line = (
        f"{agent.get('id')} reflects: state={reflection_state}, dominant={dominant}, "
        f"avg_reward={avg_reward:.2f}, mood={mood}."
    )
    reflection = {
        "tick": tick,
        "line": line,
        "state": reflection_state,
        "dominant_action": dominant,
        "avg_reward": round(avg_reward, 4),
        "mood": mood,
    }
    reflections = mind.setdefault("reflections", [])
    reflections.append(reflection)
    if len(reflections) > 30:
        del reflections[: len(reflections) - 30]
    mind["last_reflection_tick"] = tick
    mind["last_reflection"] = reflection_state
    agent["reflection"] = reflection_state
    agent["policy_bias"] = compute_policy_bias(agent)
    mind["mood"] = mood
    mind["confidence"] = clamp(float(mind.get("confidence", 0.5)) + (avg_reward * 0.08), 0.05, 0.99)
    state.setdefault("events", []).append(
        {
            "type": "agent_reflection",
            "agent_id": agent.get("id"),
            "agent_type": role or agent.get("type"),
            "line": line,
            "state": reflection_state,
            "dominant_action": dominant,
            "avg_reward": round(avg_reward, 4),
            "mood": mood,
            "network": "Arc",
            "asset": "USDC",
        }
    )
    return reflection


def ensure_policy(agent, action_keys):
    """
    Ensure a persistent policy container on the agent.
    Keeps per-action weights that evolve over time.
    """
    policy = agent.setdefault("policy", {})
    weights = policy.setdefault("weights", {})
    for key in action_keys:
        weights.setdefault(key, 1.0)
    return policy


def choose_action(agent, action_utilities, state=None, role=None):
    """
    Choose an action using policy weights biased by current utility signals.
    Returns (action, adjusted_weights).
    """
    keys = list(action_utilities.keys())
    mind = ensure_mind(agent, role=role)
    policy = ensure_policy(agent, keys)
    base = policy["weights"]
    goals = mind.get("goals", _role_goals(role or agent.get("type")))
    mood = str(mind.get("mood", "neutral"))
    confidence = float(mind.get("confidence", 0.5))
    reflection_state = str(agent.get("reflection") or mind.get("last_reflection", "balanced"))

    adjusted = {}
    for key in keys:
        utility = float(action_utilities.get(key, 0.0))
        if "steal" in key:
            utility += (goals.get("wealth", 0.5) - goals.get("stability", 0.5)) * 0.22
            utility -= goals.get("safety", 0.5) * 0.08
        elif "work" in key or "collect" in key:
            utility += goals.get("wealth", 0.5) * 0.15 + goals.get("stability", 0.5) * 0.1
        elif "redistribute" in key or "support" in key:
            utility += goals.get("stability", 0.5) * 0.25
        elif "chase" in key or "scan" in key or "call_service" in key:
            utility += goals.get("stability", 0.5) * 0.2
        elif "lay_low" in key or "hold" in key or "idle" in key or "patrol" in key:
            utility += goals.get("safety", 0.5) * 0.16

        if mood == "stressed" and ("lay_low" in key or "patrol" in key or "hold" in key):
            utility += 0.12
        if mood == "confident" and ("work" in key or "steal" in key or "chase" in key):
            utility += 0.1
        if reflection_state == "be_cautious":
            if key in {"idle", "lay_low", "hold_reserve", "patrol"}:
                utility += 0.22
            if "steal" in key or key in {"chase", "call_service"}:
                utility -= 0.25
        elif reflection_state == "be_aggressive":
            if "steal" in key or key in {"chase", "work", "collect_fees"}:
                utility += 0.2
            if key in {"idle", "lay_low", "hold_reserve"}:
                utility -= 0.1

        # Lower confidence increases exploration pressure.
        exploration = (1.0 - confidence) * random.uniform(-0.08, 0.08)
        utility += exploration
        utility_factor = clamp(1.0 + utility, 0.05, 3.0)
        adjusted[key] = clamp(float(base.get(key, 1.0)) * utility_factor, 0.01, 25.0)

    bias = agent.get("policy_bias", {}) or {}
    for key in keys:
        if key in RISKY_ACTIONS or key.startswith("steal_"):
            adjusted[key] = clamp(adjusted[key] * float(bias.get("risky", 1.0)), 0.01, 25.0)
        if key in SAFE_ACTIONS:
            adjusted[key] = clamp(adjusted[key] * float(bias.get("safe", 1.0)), 0.01, 25.0)
        if key == "idle":
            adjusted[key] = clamp(adjusted[key] * float(bias.get("idle", 1.0)), 0.01, 25.0)

    total = sum(adjusted.values())
    if total <= 0:
        return random.choice(keys), adjusted

    pick = random.random() * total
    upto = 0.0
    for key, weight in adjusted.items():
        upto += weight
        if upto >= pick:
            policy["last_action"] = key
            policy["last_adjusted_weights"] = adjusted
            agent["top_action"] = key
            mind["intent"] = f"{key} (mood={mood}, confidence={confidence:.2f})"
            remember(
                agent,
                {
                    "kind": "decision",
                    "tick": int(state.setdefault("economy", {}).get("tick", 0)) if state else None,
                    "action": key,
                    "utilities": {k: round(float(action_utilities.get(k, 0.0)), 4) for k in keys},
                    "confidence": round(confidence, 4),
                    "mood": mood,
                },
            )
            maybe_reflect(agent, state=state, role=role)
            return key, adjusted
    fallback = keys[-1]
    policy["last_action"] = fallback
    policy["last_adjusted_weights"] = adjusted
    mind["intent"] = f"{fallback} (fallback)"
    return fallback, adjusted


def reinforce_action(agent, action, reward, learning_rate=0.2, state=None, role=None, context=None):
    """
    Reinforce the selected action weight based on realized reward.
    Positive reward increases propensity; negative reward reduces it.
    """
    policy = agent.setdefault("policy", {})
    mind = ensure_mind(agent, role=role)
    weights = policy.setdefault("weights", {})
    if action not in weights:
        weights[action] = 1.0

    bounded_reward = clamp(float(reward), -1.0, 1.0)
    delta = learning_rate * bounded_reward
    weights[action] = clamp(weights[action] * (1.0 + delta), 0.05, 25.0)

    # Small mean-reversion for other actions to keep exploration alive.
    for key in list(weights.keys()):
        if key == action:
            continue
        drift = (1.0 - weights[key]) * 0.03
        weights[key] = clamp(weights[key] + drift, 0.05, 25.0)

    policy["last_reward"] = bounded_reward
    policy["last_weights"] = dict(weights)
    tick = int(state.setdefault("economy", {}).get("tick", 0)) if state else None
    remember(
        agent,
        {
            "kind": "outcome",
            "tick": tick,
            "action": action,
            "reward": round(bounded_reward, 4),
            "context": context or {},
        },
    )
    mind["confidence"] = clamp(float(mind.get("confidence", 0.5)) + bounded_reward * 0.05, 0.05, 0.99)
    maybe_reflect(agent, state=state, role=role)
