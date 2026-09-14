"""Provider-neutral text generation for the read-only assistant."""

import logging

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


def _openai_text(url: str, api_key: str, model: str, prompt: str) -> str:
    with httpx.Client(timeout=settings.ai_request_timeout_seconds) as client:
        response = client.post(url, headers={"Authorization": f"Bearer {api_key}"}, json={
            "model": model,
            "messages": [{"role": "system", "content": "Answer only from authorized Orbit context."}, {"role": "user", "content": prompt}],
            "temperature": 0.1,
            "max_tokens": 900,
        })
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"].strip()


def generate_assistant_answer(prompt: str) -> tuple[str, str]:
    """Try configured providers in order and return the first grounded answer."""
    failures: list[str] = []
    for provider in settings.ai_provider_order:
        try:
            if provider == "gemini" and settings.gemini_api_key:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{settings.gemini_model}:generateContent"
                with httpx.Client(timeout=settings.ai_request_timeout_seconds) as client:
                    response = client.post(url, headers={"x-goog-api-key": settings.gemini_api_key}, json={
                        "contents": [{"parts": [{"text": prompt}]}],
                        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 900},
                    })
                    response.raise_for_status()
                    return response.json()["candidates"][0]["content"]["parts"][0]["text"].strip(), settings.gemini_model
            if provider == "groq" and settings.groq_api_key:
                return _openai_text("https://api.groq.com/openai/v1/chat/completions", settings.groq_api_key, settings.groq_model, prompt), settings.groq_model
            if provider == "openrouter" and settings.openrouter_api_key:
                return _openai_text("https://openrouter.ai/api/v1/chat/completions", settings.openrouter_api_key, settings.openrouter_model, prompt), settings.openrouter_model
            if provider == "huggingface" and settings.huggingface_api_key:
                return _openai_text("https://router.huggingface.co/v1/chat/completions", settings.huggingface_api_key, settings.huggingface_model, prompt), settings.huggingface_model
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
            logger.warning("Assistant provider %s failed: %s", provider, type(exc).__name__)
            failures.append(provider)
    raise RuntimeError("No configured AI provider is currently available" + (f" ({', '.join(failures)})" if failures else ""))
