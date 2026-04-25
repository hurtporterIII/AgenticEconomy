from __future__ import annotations
import os

LEARNING_ENABLED = os.getenv("AGENTIC_LEARNING_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


def _append_bounded(bucket: list, row: dict, max_len: int = 60) -> None:
    bucket.append(row)
    if len(bucket) > max_len:
        del bucket[: len(bucket) - max_len]


def thief_learn_bank_penalty(state: dict, thief_id: str, amount: float) -> dict:
    if not LEARNING_ENABLED:
        return {}
    entities = state.setdefault("entities", {})
    thief = entities.get(thief_id)
    if not isinstance(thief, dict):
        return {}

    mind = thief.setdefault("mind", {})
    memory = mind.setdefault("memory", [])
    learning = thief.setdefault("learning", {})
    zone = learning.setdefault("zone_risk", {})
    bank_zone = zone.setdefault("bank_zone", {"attempts": 0, "penalties": 0, "risk_score": 0.0})

    bank_zone["attempts"] = int(bank_zone.get("attempts", 0)) + 1
    bank_zone["penalties"] = int(bank_zone.get("penalties", 0)) + 1
    bank_zone["risk_score"] = round(_clamp(float(bank_zone.get("risk_score", 0.0)) + 0.3, 0.0, 1.0), 4)

    personality = thief.setdefault("personality", {})
    personality["bank_bias"] = round(_clamp(float(personality.get("bank_bias", 0.45)) - 0.08, 0.1, 0.9), 4)
    personality["stealth"] = round(_clamp(float(personality.get("stealth", 0.4)) + 0.03, 0.1, 0.95), 4)
    personality["aggression"] = round(_clamp(float(personality.get("aggression", 0.6)) - 0.02, 0.1, 0.95), 4)

    _append_bounded(
        memory,
        {
            "kind": "learning",
            "topic": "bank_zone_penalty",
            "delta": -abs(float(amount)),
            "risk_score": bank_zone["risk_score"],
            "bank_bias": personality["bank_bias"],
        },
        max_len=100,
    )
    return {
        "risk_score": bank_zone["risk_score"],
        "bank_bias": personality["bank_bias"],
        "stealth": personality["stealth"],
        "aggression": personality["aggression"],
    }


def cop_learn_response(state: dict, cop_id: str, reward: float, mode: str) -> dict:
    if not LEARNING_ENABLED:
        return {}
    entities = state.setdefault("entities", {})
    cop = entities.get(cop_id)
    if not isinstance(cop, dict):
        return {}

    mind = cop.setdefault("mind", {})
    memory = mind.setdefault("memory", [])
    learning = cop.setdefault("learning", {})
    response = learning.setdefault("response", {"score": 0.5, "samples": 0})
    response["samples"] = int(response.get("samples", 0)) + 1
    response["score"] = round(_clamp(float(response.get("score", 0.5)) + float(reward) * 0.08, 0.05, 0.99), 4)

    personality = cop.setdefault("personality", {})
    personality["persistence"] = round(_clamp(float(personality.get("persistence", 0.6)) + float(reward) * 0.05, 0.2, 0.98), 4)
    personality["decisiveness"] = round(_clamp(float(personality.get("decisiveness", 0.55)) + float(reward) * 0.05, 0.2, 0.98), 4)

    _append_bounded(
        memory,
        {
            "kind": "learning",
            "topic": "cop_response",
            "mode": str(mode),
            "reward": round(float(reward), 4),
            "response_score": response["score"],
        },
        max_len=100,
    )
    return {
        "response_score": response["score"],
        "persistence": personality["persistence"],
        "decisiveness": personality["decisiveness"],
    }
