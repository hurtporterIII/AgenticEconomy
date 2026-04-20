import os

import requests


def query_featherless(payload=None):
    """Query Featherless-compatible endpoint once and return normalized output."""
    api_key = os.getenv("FEATHERLESS_API_KEY") or os.getenv("SERVICE_API_KEY")
    base_url = os.getenv("FEATHERLESS_BASE_URL", "https://api.featherless.ai/v1/chat/completions")
    model = os.getenv("FEATHERLESS_MODEL", "gpt-4o-mini")

    if not api_key:
        return {"used": False, "provider": "featherless", "error": "missing_api_key"}

    body = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": str(payload or "Return one thief id only."),
            }
        ],
        "max_tokens": 12,
        "temperature": 0,
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    try:
        response = requests.post(base_url, headers=headers, json=body, timeout=8)
        response.raise_for_status()
        data = response.json()
        text = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )
        return {"used": True, "provider": "featherless", "text": text, "raw": data}
    except Exception as exc:
        return {"used": False, "provider": "featherless", "error": str(exc)}
