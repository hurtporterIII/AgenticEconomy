import random
import threading
from utils.logger import EventBuffer, create_event_buffer

# Serialize access to the in-memory `state` dict (auto-tick thread + HTTP handlers).
# Callers hold this around run_loop() and other mutations; do not acquire inside run_loop.
state_lock = threading.RLock()


def default_behavior_settings():
    return {
        "worker": {"effort": 0.7, "efficiency": 0.7, "reliability": 0.8},
        "thief": {"aggression": 0.6, "bank_bias": 0.5, "stealth": 0.6},
        "cop": {"api_reliance": 0.2, "persistence": 0.7, "decisiveness": 0.7},
        "banker": {"strictness": 0.55, "liquidity_bias": 0.7, "generosity": 0.5},
        "bank": {"security": 0.6, "fee_rate": 0.35, "reserve_bias": 0.65},
    }


def default_economy_state():
    return {
        "tick": 0,
        "regime": "balanced",
        "narration": "Balanced city: production, enforcement, and risk remain in tension.",
        "stability_score": 100.0,
        "population": {"worker": 0, "thief": 0, "cop": 0, "banker": 0, "bank": 0, "total": 0},
        "ratios": {"worker": 0.0, "thief": 0.0, "cop": 0.0, "banker": 0.0, "bank": 0.0},
        "multipliers": {
            "worker_income": 1.0,
            "worker_tax": 0.0,
            "theft_success": 1.0,
            "cop_effectiveness": 1.0,
            "api_cost": 1.0,
            "bank_fee": 1.0,
        },
        "guidance": {
            "target_mix": {"worker": 0.55, "cop": 0.25, "thief": 0.15, "banker": 0.05},
            "recommended_counts": {"worker": 0, "cop": 0, "thief": 0, "banker": 0},
            "adjustments": {"worker": 0, "cop": 0, "thief": 0, "banker": 0},
            "notes": [],
        },
    }


def _clamp01(value):
    return max(0.0, min(1.0, float(value)))


def build_personality(entity_type, behavior_settings=None):
    behavior = behavior_settings or default_behavior_settings()
    base = dict(behavior.get(entity_type, {}))
    personality = {}
    for key, value in base.items():
        # Shared doctrine + per-agent DNA jitter to avoid clone behavior.
        jitter = random.uniform(-0.2, 0.2)
        personality[key] = _clamp01(float(value) + jitter)
    return personality


WORK_TREASURY_ID = "B11_work_treasury"
WORK_TREASURY_START = 1000.0

state = {
    "entities": {},
    # Seed the B11 work treasury so workers have a real source to pull
    # their nano-payments from. Every worker "earn" at B11 is a real
    # transfer: B11_work_treasury -> worker_<n>. Starts with 1000 USDC,
    # at 0.001 USDC per shift that's 1,000,000 shifts of runway — more
    # than enough for the demo.
    "balances": {WORK_TREASURY_ID: WORK_TREASURY_START},
    "events": create_event_buffer(),
    "behavior_settings": default_behavior_settings(),
    "economy": default_economy_state(),
    "metrics": {
        "total_spent": 0.0,
        "successful_tx": 0,
        "failed_tx": 0,
    },
    "settlement": {
        "strategy": "sampled",
        "interval_ticks": 4,
        "max_real_txs_per_cycle": 4,
        "sample_amount": 0.001,
        "pending_intents": [],
        "last_cycle_tick": 0,
        "last_cycle_summary": {},
        "recent_records": [],
    },
}


def load_state():
    """Return shared in-memory state."""
    state.setdefault("behavior_settings", default_behavior_settings())
    state.setdefault("economy", default_economy_state())
    if not isinstance(state.get("events"), EventBuffer):
        state["events"] = create_event_buffer(initial=state.get("events", []))
    state.setdefault("metrics", {})
    state["metrics"].setdefault("total_spent", 0.0)
    state["metrics"].setdefault("successful_tx", 0)
    state["metrics"].setdefault("failed_tx", 0)
    state.setdefault("settlement", {})
    state["settlement"].setdefault("strategy", "sampled")
    state["settlement"].setdefault("interval_ticks", 5)
    state["settlement"].setdefault("max_real_txs_per_cycle", 3)
    state["settlement"].setdefault("sample_amount", 0.001)
    state["settlement"].setdefault("pending_intents", [])
    state["settlement"].setdefault("last_cycle_tick", 0)
    state["settlement"].setdefault("last_cycle_summary", {})
    state["settlement"].setdefault("recent_records", [])
    return state


def save_state(new_state):
    """Update shared in-memory state."""
    state.clear()
    state.update(new_state)
    if not isinstance(state.get("events"), EventBuffer):
        state["events"] = create_event_buffer(initial=state.get("events", []))
    state.setdefault("behavior_settings", default_behavior_settings())
    state.setdefault("economy", default_economy_state())
    state.setdefault("metrics", {})
    state["metrics"].setdefault("total_spent", 0.0)
    state["metrics"].setdefault("successful_tx", 0)
    state["metrics"].setdefault("failed_tx", 0)
    state.setdefault("settlement", {})
    state["settlement"].setdefault("strategy", "sampled")
    state["settlement"].setdefault("interval_ticks", 5)
    state["settlement"].setdefault("max_real_txs_per_cycle", 3)
    state["settlement"].setdefault("sample_amount", 0.001)
    state["settlement"].setdefault("pending_intents", [])
    state["settlement"].setdefault("last_cycle_tick", 0)
    state["settlement"].setdefault("last_cycle_summary", {})
    state["settlement"].setdefault("recent_records", [])
    return state
