# """Вызов Ollama + очистка ответа."""
# from __future__ import annotations

# import re

# import requests

# from .config import MODEL, OLLAMA_URL

# DEFAULT_TIMEOUT = 400  # согласовано с max_attempts в run.py и subprocess timeout в new_ui.py


# def cleanup_response(text: str) -> str:
#     text = text.strip()
#     text = re.sub(r"^```python", "", text, flags=re.IGNORECASE)
#     text = re.sub(r"^```", "", text)
#     text = re.sub(r"```$", "", text)
#     return text.strip()


# def generate(prompt: str, timeout: int = DEFAULT_TIMEOUT) -> str:
#     payload = {
#         "model": MODEL,
#         "prompt": prompt,
#         "stream": False,
#         "options": {
#             "num_ctx": 16384,
#         },
#     }
#     response = requests.post(OLLAMA_URL, json=payload, timeout=timeout)
#     response.raise_for_status()
#     data = response.json()
#     if "response" not in data:
#         raise RuntimeError("Ollama returned an invalid response.")
#     return cleanup_response(data["response"])

"""Вызов Gemini API + очистка ответа."""
from __future__ import annotations

import re

from google import genai
from google.genai import types

from .config import MODEL, GEMINI_API_KEY

DEFAULT_TIMEOUT = 400

_client = genai.Client(api_key=GEMINI_API_KEY)


def cleanup_response(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```python", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^```", "", text)
    text = re.sub(r"```$", "", text)
    return text.strip()


def generate(prompt: str, timeout: int = DEFAULT_TIMEOUT) -> str:
    response = _client.models.generate_content(
        model=MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0,
            http_options=types.HttpOptions(timeout=timeout * 1000),
        ),
    )
    if not response.text:
        raise RuntimeError("Gemini returned an invalid response.")
    return cleanup_response(response.text)