import os
import random
import re
from pathlib import Path

import requests

try:
    from dotenv import load_dotenv
except Exception:
    load_dotenv = None

USE_AI = True
AI_PROVIDER = os.getenv("AI_PROVIDER", "auto").lower()

if load_dotenv:
    root_env = Path(__file__).resolve().parents[2] / ".env"
    load_dotenv(dotenv_path=root_env, override=True)

_gemini_key = os.getenv("GEMINI_API_KEY")
_deepseek_key = os.getenv("DEEPSEEK_API_KEY")


def _extract_valid_id(text, valid_ids):
    token = (text or "").strip()
    if token in valid_ids:
        return token
    match = re.search(r"[A-Za-z0-9_\\-]+", token)
    if match and match.group(0) in valid_ids:
        return match.group(0)
    return None


def gemini_decision(state, thieves):
    """Primary external AI decision using Gemini REST API."""
    if not thieves:
        return None

    valid_ids = [t.get("id") for t in thieves if t.get("id")]
    if not valid_ids:
        return None

    if not _gemini_key:
        raise RuntimeError("GEMINI_API_KEY missing")

    prompt = f"Pick one thief id from: {valid_ids}. Return only the id."
    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
    headers = {"Content-Type": "application/json", "X-goog-api-key": _gemini_key}
    payload = {"contents": [{"parts": [{"text": prompt}]}]}

    response = requests.post(url, headers=headers, json=payload, timeout=15)
    if response.status_code == 429:
        return None
    if response.status_code == 503:
        response = requests.post(url, headers=headers, json=payload, timeout=15)
    if response.status_code == 429:
        return None
    if response.status_code != 200:
        return None

    body = response.json()
    text = (
        body.get("candidates", [{}])[0]
        .get("content", {})
        .get("parts", [{}])[0]
        .get("text", "")
    )
    return _extract_valid_id(text, valid_ids)


def deepseek_decision(thieves):
    """Secondary external AI decision using DeepSeek REST API."""
    if not thieves:
        return None

    valid_ids = [t.get("id") for t in thieves if t.get("id")]
    if not valid_ids:
        return None

    try:
        if not _deepseek_key:
            raise RuntimeError("DEEPSEEK_API_KEY missing")

        prompt = f"Pick one thief id from: {valid_ids}. Return only the id."
        response = requests.post(
            "https://api.deepseek.com/chat/completions",
            headers={
                "Authorization": f"Bearer {_deepseek_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
            },
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
        result = payload.get("choices", [{}])[0].get("message", {}).get("content", "")
        thief_id = _extract_valid_id(result, valid_ids)
        if thief_id:
            return thief_id
    except Exception as exc:
        print("DeepSeek error:", exc)
    return None


def decide_thief(state, thieves):
    """Provider router with fallback chain."""
    if AI_PROVIDER == "gemini":
        try:
            result = gemini_decision(state, thieves)
            if result:
                return result, "gemini", "external"
        except Exception as exc:
            print("Gemini failed:", exc)
        return random.choice(thieves).get("id"), "fallback", "fallback"

    if AI_PROVIDER == "deepseek":
        try:
            result = deepseek_decision(thieves)
            if result:
                return result, "deepseek", "external"
        except Exception as exc:
            print("DeepSeek failed:", exc)
        return random.choice(thieves).get("id"), "fallback", "fallback"

    try:
        result = gemini_decision(state, thieves)
        if result:
            return result, "gemini", "external"
    except Exception as exc:
        print("Gemini failed:", exc)

    try:
        result = deepseek_decision(thieves)
        if result:
            return result, "deepseek", "external"
    except Exception as exc:
        print("DeepSeek failed:", exc)

    return random.choice(thieves).get("id"), "fallback", "fallback"


def locate_thief(state):
    """
    Returns thief id
    """
    thieves = [
        entity
        for entity in state.setdefault("entities", {}).values()
        if entity.get("type") == "thief"
    ]
    if not thieves:
        return None

    if USE_AI:
        thief_id, provider, mode = decide_thief(state, thieves)

        state.setdefault("events", []).append(
            {
                "type": "ai_decision",
                "provider": provider,
                "mode": mode,
                "thief_id": thief_id,
                # AI selection is accounted via the paid API call in actions/service.py.
                "tx_hash": None,
                "network": "Arc",
                "asset": "USDC",
            }
        )
        if thief_id:
            return thief_id

    return random.choice(thieves).get("id")
