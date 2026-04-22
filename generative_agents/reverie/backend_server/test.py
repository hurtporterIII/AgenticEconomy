"""
Provider smoke test for the backend prompt layer.
Uses the same universal config path as the simulation.
"""

from persona.prompt_template.gpt_structure import ChatGPT_request, PROVIDER, BASE_URL, CHAT_MODEL


if __name__ == "__main__":
    prompt = "Reply with exactly one short sentence confirming the API is reachable."
    print("provider:", PROVIDER)
    print("base_url:", BASE_URL or "(default)")
    print("chat_model:", CHAT_MODEL)
    print("response:", ChatGPT_request(prompt))
