"""Email digest generation module."""

import logging
from typing import List, Optional
from collections import Counter

from app.domain.models import ThreadTriageResult
from app.infra.llm import call_llm_raw
from app.utils import get_prompts_dir

logger = logging.getLogger(__name__)


def load_digest_prompts() -> str:
    """
    Load digest system prompt from file.

    Returns:
        System prompt string
    """
    prompts_dir = get_prompts_dir()
    system_prompt_path = prompts_dir / "digest_system.md"

    if system_prompt_path.exists():
        return system_prompt_path.read_text(encoding="utf-8")

    logger.warning(f"Digest prompt not found at {system_prompt_path}")
    return ""


def generate_digest(
    triage_results: List[ThreadTriageResult],
    model: Optional[str] = None,
    api_key: Optional[str] = None
) -> str:
    """
    Generate a digest summary from triage results.

    Args:
        triage_results: List of ThreadTriageResult objects
        model: LLM model name (optional)
        api_key: LLM API key (optional)

    Returns:
        Digest text as string
    """
    logger.info(f"Generating digest for {len(triage_results)} triage results")

    system_prompt = load_digest_prompts()

    # ─────────────────────────────────────────────
    # Deterministic statistics (NO LLM counting)
    # ─────────────────────────────────────────────
    priority_counts = Counter(r.priority for r in triage_results)
    classification_counts = Counter(r.classification for r in triage_results)

    due_today_threads = [
        r.thread_id
        for r in triage_results
        if r.priority in {"P0", "P1"} and r.due_by in {"today", "COB"}
    ]

    # Sort threads so high priority appears first
    priority_order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    sorted_results = sorted(
        triage_results,
        key=lambda r: (
            priority_order.get(r.priority, 99),
            r.due_by or ""
        )
    )

    # ─────────────────────────────────────────────
    # Build structured input for LLM
    # ─────────────────────────────────────────────
    digest_content = f"""
Total threads: {len(triage_results)}

Priority counts:
P0: {priority_counts.get("P0", 0)}
P1: {priority_counts.get("P1", 0)}
P2: {priority_counts.get("P2", 0)}
P3: {priority_counts.get("P3", 0)}

Classification counts:
action_required: {classification_counts.get("action_required", 0)}
informational_archive: {classification_counts.get("informational_archive", 0)}
irrelevant: {classification_counts.get("irrelevant", 0)}

P0/P1 due today or COB:
{", ".join(due_today_threads) if due_today_threads else "None"}

Threads:
"""

    for result in sorted_results:
        digest_content += f"""
Thread: {result.thread_id}
  Topic: {result.topic}
  Classification: {result.classification}
  Priority: {result.priority}
"""
        if result.due_by:
            digest_content += f"  Due by: {result.due_by}\n"

        digest_content += f"  Summary: {result.summary}\n"

        if result.required_actions:
            digest_content += (
                f"  Actions: {', '.join(result.required_actions[:3])}\n"
            )

    # ─────────────────────────────────────────────
    # User prompt
    # ─────────────────────────────────────────────
    user_prompt = f"""Generate the daily operational digest in Markdown using the required structure in the system prompt.

Use the statistics exactly as provided above.
Do not recalculate counts.
Do not invent threads.
Do not introduce data not present.

Structured triage input:
{digest_content}
"""

    # Call LLM
    response = call_llm_raw(
        system=system_prompt,
        user=user_prompt,
        model=model,
        api_key=api_key
    )

    logger.info("Successfully generated digest")
    return response