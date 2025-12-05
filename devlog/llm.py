import requests
import json

def call_llm(raw_text):
    # Build prompt including raw_text
    if len(raw_text)<80:
        prompt = f"Rewrite the following in 1-2 concise and factual bullet points.\nDo not add any extra information or assumptions.\nOnly include details that appear in the original text.\nUse '-' as the bullet symbol.\n\nText:\n" + raw_text
    elif len(raw_text)>=80:
        prompt = f"Summarize the following text into up to 7–8 bullet points.\nUse '-' as the bullet symbol.\nEach bullet may include enough context for teaching or future explanation.\nDo NOT add any introduction or conclusion.\n\nText:\n" + raw_text
    # Create payload for Ollama
    payload = {
            "prompt": prompt,
            "model": "llama3.2:3b",
            "stream": False
            }

    # Send POST request
    http_resp = requests.post("http://localhost:11434/api/generate", json=payload, timeout=90)

    # Handle network/timeout errors
    if http_resp.status_code != 200:
        return None

    # Parse JSON response safely
    try:
        http_resp_json = http_resp.json()
    except json.JSONDecodeError:
        return None

    # Extract "response" from JSON response
    summary = http_resp_json.get("response")
    # Validate summary
    if summary is None:
        return None
    if summary.strip() == "":
        return None
    if summary.startswith("Error:"):
        return None
    # Return summary or None
    return summary

