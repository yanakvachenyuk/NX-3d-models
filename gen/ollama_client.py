"""Вызов LLM с fallback между провайдерами + очистка ответа."""
from __future__ import annotations

import logging
import re

import requests

from . import config

DEFAULT_TIMEOUT = 400  # согласовано с max_attempts в run.py и subprocess timeout в new_ui.py

logger = logging.getLogger(__name__)


def cleanup_response(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```python", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^```", "", text)
    text = re.sub(r"```$", "", text)
    return text.strip()


def _gemini(prompt: str, timeout: int) -> str:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=config.GEMINI_API_KEY)
    response = client.models.generate_content(
        model=config.GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0,
            http_options=types.HttpOptions(timeout=timeout * 1000),
        ),
    )
    if not response.text:
        raise RuntimeError("Gemini returned an empty response.")
    return cleanup_response(response.text)


def _mistral(prompt: str, timeout: int) -> str:
    return _openai_compatible(
        "https://api.mistral.ai/v1", config.MISTRAL_API_KEY, config.MISTRAL_MODEL, prompt, timeout
    )

def _openai_compatible(base_url: str, api_key: str, model: str, prompt: str, timeout: int) -> str:
    resp = requests.post(
        f"{base_url}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    text = data["choices"][0]["message"]["content"]
    if not text:
        raise RuntimeError("Empty response from OpenAI-compatible provider.")
    return cleanup_response(text)


def _ollama(prompt: str, timeout: int) -> str:
    payload = {
        "model": config.OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"num_ctx": 16384},
    }
    response = requests.post(config.OLLAMA_URL, json=payload, timeout=timeout)
    response.raise_for_status()
    data = response.json()
    if "response" not in data:
        raise RuntimeError("Ollama returned an invalid response.")
    return cleanup_response(data["response"])


_PROVIDERS = {
    "gemini": _gemini,
    "mistral": _mistral,
    "ollama": _ollama,
}


def generate(prompt: str, timeout: int = DEFAULT_TIMEOUT) -> str:
    errors = []
    for name in config.LLM_PROVIDERS:
        name = name.strip()
        fn = _PROVIDERS.get(name)
        if fn is None:
            logger.warning("Неизвестный провайдер %r в LLM_PROVIDERS, пропускаю.", name)
            continue
        try:
            logger.info("Пробую провайдера: %s", name)
            return fn(prompt, timeout)
        except Exception as exc:
            logger.warning("Провайдер %s не сработал: %s", name, exc)
            errors.append(f"{name}: {exc}")

    raise RuntimeError("Все провайдеры LLM не сработали:\n" + "\n".join(errors))