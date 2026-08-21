"""Вызов Ollama + очистка ответа."""
from __future__ import annotations

import re

import requests

from .config import MODEL, OLLAMA_URL


def cleanup_response(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```python", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^```", "", text)
    text = re.sub(r"```$", "", text)
    return text.strip()


def generate(prompt: str) -> str:
    payload = {
        "model": MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {
            "num_ctx": 16384,
        },
    }
    response = requests.post(OLLAMA_URL, json=payload, timeout=600)
    response.raise_for_status()
    data = response.json()
    if "response" not in data:
        raise RuntimeError("Ollama returned an invalid response.")
    return cleanup_response(data["response"])