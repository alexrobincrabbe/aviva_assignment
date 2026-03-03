"""LLM integration module using the official OpenAI Python SDK.

This module provides:
- A thin `LLMClient` wrapper used by the rest of the app
- Low-level helpers:
    - `call_llm_raw(system, user, model) -> str`
    - `call_llm_json(model_cls, system, user, model) -> BaseModel`

Behaviour & configuration:
- Reads `OPENAI_API_KEY` from the environment (or optional explicit api_key).
- Model selection:
    - CLI / caller override (model argument or LLMClient.model)
    - `OPENAI_MODEL` env var
    - Fallback default model name
- Retries with exponential backoff on transient errors.
- Logging is intentionally minimal and never includes full prompt/response text.
"""

from __future__ import annotations

import logging
import os
import random
import time
from pathlib import Path
from typing import Any, Callable, Optional, Type, TypeVar

from dotenv import load_dotenv, dotenv_values
from openai import APIError, OpenAI, RateLimitError
from pydantic import BaseModel

from app.utils import get_repo_root

# Load .env file if it exists
env_path = get_repo_root() / ".env"
if env_path.exists():
    # Use utf-8-sig encoding to automatically handle BOM (Byte Order Mark)
    # dotenv_values handles BOM better than load_dotenv with file paths
    env_values = dotenv_values(dotenv_path=str(env_path), encoding='utf-8-sig')
    # Set environment variables from .env file
    for key, value in env_values.items():
        if value is not None:
            os.environ[key] = value
else:
    # Also try loading from current directory
    load_dotenv(override=True)

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


def _resolve_model(model: Optional[str] = None) -> str:
    """Resolve the model name from override, env, or default."""
    if model:
        return model
    env_model = os.getenv("OPENAI_MODEL")
    if env_model:
        return env_model
    # Sensible default; override via OPENAI_MODEL or CLI if needed.
    return "gpt-4o-mini"


def _create_client(api_key: Optional[str] = None) -> OpenAI:
    """Create an OpenAI client using the provided or environment API key."""
    key = api_key or os.getenv("OPENAI_API_KEY")
    if not key:
        raise RuntimeError(
            "OPENAI_API_KEY is not set. Set it in the environment or .env file, "
            "or use --dry-run to test without an API key."
        )
    # Do not log the key; only log that the client was created.
    logger.debug("Creating OpenAI client")
    return OpenAI(api_key=key)


def _is_transient_error(exc: Exception) -> bool:
    """Best-effort check for transient API errors (rate limits, 5xx)."""
    if isinstance(exc, (RateLimitError,)):
        return True
    if isinstance(exc, APIError):
        # APIError typically has status_code for HTTP issues.
        status = getattr(exc, "status_code", None)
        if status in {429, 500, 502, 503, 504}:
            return True
    # Generic heuristic: if it has status_code and it's 5xx/429, treat as transient.
    status = getattr(exc, "status_code", None)
    if isinstance(status, int) and status in {429, 500, 502, 503, 504}:
        return True
    return False


def _with_retries(operation: Callable[[], Any], *, max_retries: int = 3) -> Any:
    """Execute an operation with exponential backoff on transient errors."""
    delay = 1.0
    for attempt in range(max_retries):
        try:
            return operation()
        except Exception as exc:  # noqa: BLE001
            if not _is_transient_error(exc) or attempt == max_retries - 1:
                # Log only high-level info, never prompts/content.
                logger.error(
                    "LLM call failed (attempt %d/%d): %s",
                    attempt + 1,
                    max_retries,
                    exc,
                )
                raise

            logger.warning(
                "Transient LLM error (attempt %d/%d): %s; retrying in %.1fs",
                attempt + 1,
                max_retries,
                exc,
                delay,
            )
            # Jitter to avoid thundering herd.
            time.sleep(delay + random.uniform(0, 0.5))
            delay *= 2


def _call_llm_raw_internal(
    system: str,
    user: str,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
) -> str:
    """Internal raw text call with explicit api_key for LLMClient."""
    resolved_model = _resolve_model(model)

    def _op() -> str:
        client = _create_client(api_key=api_key)
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user})

        # Keep logs short; never log full prompts.
        logger.info(
            "Calling OpenAI chat.completions (model=%s, sys_len=%d, user_len=%d)",
            resolved_model,
            len(system),
            len(user),
        )

        resp = client.chat.completions.create(
            model=resolved_model,
            messages=messages,
            temperature=0.0,
        )
        content = resp.choices[0].message.content or ""
        logger.debug(
            "LLM raw call success (model=%s, out_len=%d)",
            resolved_model,
            len(content),
        )
        return content

    return _with_retries(_op)


def _call_llm_json_internal(
    model_cls: Type[T],
    system: str,
    user: str,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
) -> T:
    """Internal JSON call that returns a Pydantic model instance."""
    resolved_model = _resolve_model(model)

    def _op() -> T:
        client = _create_client(api_key=api_key)
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user})

        logger.info(
            "Calling OpenAI chat.completions JSON (model=%s, sys_len=%d, user_len=%d)",
            resolved_model,
            len(system),
            len(user),
        )

        resp = client.chat.completions.create(
            model=resolved_model,
            messages=messages,
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        content = resp.choices[0].message.content or "{}"
        logger.debug(
            "LLM JSON call success (model=%s, out_len=%d)",
            resolved_model,
            len(content),
        )
        # Validate & parse JSON into the target Pydantic model.
        return model_cls.model_validate_json(content)

    return _with_retries(_op)


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def call_llm_raw(system: str, user: str, model: str | None = None, api_key: str | None = None) -> str:
    """Public raw-text LLM call using env-configured OpenAI client."""
    return _call_llm_raw_internal(system=system, user=user, model=model, api_key=api_key)


def call_llm_json(
    model_cls: Type[T],
    system: str,
    user: str,
    model: str | None = None,
    api_key: str | None = None,
) -> T:
    """Public JSON-structured LLM call returning a Pydantic model instance."""
    return _call_llm_json_internal(
        model_cls=model_cls,
        system=system,
        user=user,
        model=model,
        api_key=api_key,
    )


class LLMClient:
    """Simple wrapper used by the rest of the app."""

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        """Initialize LLM client.

        Args:
            api_key: Optional explicit API key (otherwise uses OPENAI_API_KEY).
            model: Optional model override; otherwise uses OPENAI_MODEL / default.
        """
        self.api_key = api_key
        self.model = model
        logger.info(
            "Initialized LLM client (model=%s, api_key_provided=%s)",
            self.model or os.getenv("OPENAI_MODEL") or "default",
            bool(self.api_key),
        )

    def complete(self, system_prompt: str, user_prompt: str, **_: Any) -> str:
        """Generate a raw text completion from the LLM."""
        return _call_llm_raw_internal(
            system=system_prompt,
            user=user_prompt,
            model=self.model,
            api_key=self.api_key,
        )

    def stream_complete(self, system_prompt: str, user_prompt: str, **_: Any):
        """Streaming completion (not yet implemented)."""
        # For now we don't need streaming in this project. Implement later if required.
        raise NotImplementedError("Streaming completion is not implemented yet.")
