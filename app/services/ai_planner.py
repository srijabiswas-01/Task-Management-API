import json
import logging
from datetime import date, timedelta
from collections.abc import Callable

import httpx
from pydantic import ValidationError

from app.core.config import settings
from app.schemas import AIGeneratedPlan

logger = logging.getLogger(__name__)


class AIProvidersUnavailable(RuntimeError):
    def __init__(self, failures: list[str]):
        super().__init__("; ".join(failures))
        self.failures = failures


def _planning_prompt(project_name: str, request: str, maximum_tasks: int, project_start: date, project_end: date) -> str:
    return f"""
You are a project planning assistant. Break the user's request into concrete,
independent tasks for the project "{project_name}".

Return only one valid JSON object with this exact shape:
{{
  "summary": "short plan summary",
  "tasks": [
    {{
      "title": "actionable task title",
      "description": "clear completion details",
      "priority": "low|medium|high|critical",
      "story_points": 1,
      "start_date": "YYYY-MM-DD",
      "end_date": "YYYY-MM-DD",
      "checklist": ["optional concrete verification step"]
    }}
  ]
}}

Rules:
- Return between 1 and {maximum_tasks} tasks, never more.
- Use only low, medium, high, or critical for priority.
- story_points must be an integer from 0 to 100 or null.
- Titles must be distinct and start with an action verb.
- Distribute task dates logically from {project_start.isoformat()} through {project_end.isoformat()}.
- Every task date must remain inside that project range.
- Include a short checklist only when it materially helps verify completion.
- Do not include markdown fences, commentary, IDs, assignees, or unsupported fields.

User request:
{request}
""".strip()


def _extract_json(text: str) -> dict:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end < start:
        raise ValueError("provider did not return a JSON object")
    value = json.loads(cleaned[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("provider response must be a JSON object")
    return value


def _openai_compatible(
    *,
    url: str,
    api_key: str,
    model: str,
    prompt: str,
) -> str:
    with httpx.Client(timeout=settings.ai_request_timeout_seconds) as client:
        response = client.post(
            url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [
                    {
                        "role": "system",
                        "content": "Return valid JSON only. Follow the supplied schema.",
                    },
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.2,
            },
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]


def _gemini(prompt: str) -> tuple[str, str]:
    if not settings.gemini_api_key:
        raise ValueError("API key is not configured")
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{settings.gemini_model}:generateContent"
    )
    with httpx.Client(timeout=settings.ai_request_timeout_seconds) as client:
        response = client.post(
            url,
            headers={
                "x-goog-api-key": settings.gemini_api_key,
                "Content-Type": "application/json",
            },
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 0.2,
                    "responseMimeType": "application/json",
                },
            },
        )
        response.raise_for_status()
        text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
    return settings.gemini_model, text


def _groq(prompt: str) -> tuple[str, str]:
    if not settings.groq_api_key:
        raise ValueError("API key is not configured")
    text = _openai_compatible(
        url="https://api.groq.com/openai/v1/chat/completions",
        api_key=settings.groq_api_key,
        model=settings.groq_model,
        prompt=prompt,
    )
    return settings.groq_model, text


def _openrouter(prompt: str) -> tuple[str, str]:
    if not settings.openrouter_api_key:
        raise ValueError("API key is not configured")
    text = _openai_compatible(
        url="https://openrouter.ai/api/v1/chat/completions",
        api_key=settings.openrouter_api_key,
        model=settings.openrouter_model,
        prompt=prompt,
    )
    return settings.openrouter_model, text


def _huggingface(prompt: str) -> tuple[str, str]:
    if not settings.huggingface_api_key:
        raise ValueError("API key is not configured")
    text = _openai_compatible(
        url="https://router.huggingface.co/v1/chat/completions",
        api_key=settings.huggingface_api_key,
        model=settings.huggingface_model,
        prompt=prompt,
    )
    return settings.huggingface_model, text


PROVIDERS: dict[str, Callable[[str], tuple[str, str]]] = {
    "gemini": _gemini,
    "groq": _groq,
    "openrouter": _openrouter,
    "huggingface": _huggingface,
}


def generate_task_plan(
    project_name: str,
    request: str,
    maximum_tasks: int,
    project_start: date | None = None,
    project_end: date | None = None,
) -> tuple[AIGeneratedPlan, str, str, bool]:
    limit = min(maximum_tasks, settings.ai_max_tasks)
    project_start = project_start or date.today()
    project_end = project_end or project_start
    prompt = _planning_prompt(project_name, request, limit, project_start, project_end)
    failures: list[str] = []

    for index, provider_name in enumerate(settings.ai_provider_order):
        provider = PROVIDERS.get(provider_name)
        if provider is None:
            failures.append(f"{provider_name}: unsupported provider")
            continue
        try:
            model, raw = provider(prompt)
            plan = AIGeneratedPlan.model_validate(_extract_json(raw))
            if len(plan.tasks) > limit:
                plan.tasks = plan.tasks[:limit]
            span = max(0, (project_end - project_start).days)
            count = len(plan.tasks)
            for task_index, task in enumerate(plan.tasks):
                task.start_date = project_start + timedelta(days=(span * task_index) // count)
                task.end_date = project_start + timedelta(days=(span * (task_index + 1)) // count)
            return plan, provider_name, model, index > 0
        except (
            httpx.HTTPError,
            KeyError,
            IndexError,
            TypeError,
            ValueError,
            ValidationError,
        ) as exc:
            logger.warning(
                "AI task provider %s failed: %s",
                provider_name,
                type(exc).__name__,
            )
            failures.append(f"{provider_name}: {type(exc).__name__}")

    raise AIProvidersUnavailable(failures)
