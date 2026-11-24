
import os
import logging

import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


async def generate_text(prompt: str) -> str:
    api_key = os.getenv("OPENROUTER_API_KEY")
    model = os.getenv("OPENROUTER_MODEL", "openrouter/free")

    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not configured")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-Title": "AI Research Platform",
    }

    payload = {
        "model": model,
        "max_completion_tokens": 20480,
        "reasoning": {
            "effort": "low",
        },
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a business research assistant. "
                    "Be factual, distinguish verified information "
                    "from assumptions, and never invent sources."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.3,
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            OPENROUTER_URL,
            headers=headers,
            json=payload,
        )
        response.raise_for_status()
        data = response.json()

    try:
        choice = data["choices"][0]
        message = choice.get("message") or {}
        content = message.get("content")
    except (KeyError, IndexError, TypeError) as exc:
        logger.error(
            "OpenRouter returned an unexpected response structure. "
            "Response model: %s",
            data.get("model", "unknown"),
        )
        raise RuntimeError(
            "The LLM API returned an unexpected response"
        ) from exc

    if not isinstance(content, str) or not content.strip():
        logger.error(
            "OpenRouter returned empty content | model=%s | "
            "finish_reason=%s | message_fields=%s | has_reasoning=%s",
            data.get("model", "unknown"),
            choice.get("finish_reason", "unknown"),
            list(message.keys()) if isinstance(message, dict) else [],
            bool(message.get("reasoning")) if isinstance(message, dict) else False,
        )
        raise RuntimeError(
            "The LLM API returned empty or invalid content"
        )

    return content
