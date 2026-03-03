"""Email triage module for categorizing and prioritizing emails."""

import logging
from pathlib import Path
from typing import List, Dict, Any, Optional

from app.domain.models import EmailData, EmailThread, Message, ThreadTriageResult
from app.infra.llm import LLMClient, call_llm_json
from app.infra.redact import redact_text, RedactionMap
from app.utils import get_prompts_dir

logger = logging.getLogger(__name__)


def load_triage_prompts() -> tuple[str, str]:
    """
    Load triage system and user prompts from files.
    
    Returns:
        Tuple of (system_prompt, user_prompt_template)
    """
    prompts_dir = get_prompts_dir()
    
    system_prompt_path = prompts_dir / "triage_system.md"
    user_prompt_path = prompts_dir / "triage_user.md"
    
    system_prompt = ""
    user_prompt_template = ""
    
    if system_prompt_path.exists():
        system_prompt = system_prompt_path.read_text(encoding='utf-8')
    else:
        logger.warning(f"Triage system prompt not found at {system_prompt_path}")
    
    if user_prompt_path.exists():
        user_prompt_template = user_prompt_path.read_text(encoding='utf-8')
    else:
        logger.warning(f"Triage user prompt not found at {user_prompt_path}")
    
    return system_prompt, user_prompt_template


def format_message_for_triage(message: Message, redact: bool = False) -> str:
    """
    Format a message for triage processing.

    Redaction (if enabled) is applied to:
      - subject
      - from/to/cc fields
      - body

    Note: this redactor handles emails/phones/postcodes; it does not reliably remove names.
    """
    # Use ONE map per message so the same token is used consistently within that message
    redaction_map = RedactionMap() if redact else None

    def r(text: str | None) -> str:
        if not redact:
            return text or ""
        return redact_text(text or "", redaction_map, redact_postcodes=True)

    subject = r(message.subject)
    sent_from = r(message.sent_from)
    sent_to = [r(x) for x in (message.sent_to or [])]
    sent_cc = [r(x) for x in (getattr(message, "sent_cc", None) or [])]
    body = r(message.body)

    formatted = f"""Subject: {subject}
From: {sent_from}
To: {', '.join(sent_to)}
CC: {', '.join(sent_cc)}
Date: {message.date_sent}
Thread ID: {message.thread_id}
Message ID: {message.message_id}

Body:
{body}
"""

    if message.attachments:
        formatted += f"\nAttachments: {len(message.attachments)} file(s)\n"
        for att in message.attachments:
            formatted += f"  - {att.filename} ({att.filetype}, {att.filesize} bytes)\n"

    return formatted


def triage_email_thread(
    thread: EmailThread,
    redact: bool = False
) -> ThreadTriageResult:
    """
    Triage a single email thread.
    """
    if not thread.messages:
        raise ValueError("Thread has no messages")

    thread_id = thread.messages[0].thread_id
    logger.info(f"Triaging thread {thread_id} with {len(thread.messages)} messages")

    system_prompt, user_prompt_template = load_triage_prompts()

    # Format all messages in the thread
    formatted_messages = [
        format_message_for_triage(msg, redact=redact)
        for msg in thread.messages
    ]

    # Combine messages
    thread_text = "\n\n---\n\n".join(formatted_messages)

    # Format user prompt
    user_prompt = user_prompt_template.format(
        thread_content=thread_text,
        message_count=len(thread.messages)
    )

    # Call LLM for triage with JSON output
    result = call_llm_json(
        model_cls=ThreadTriageResult,
        system=system_prompt,
        user=user_prompt
    )

    # Ensure thread_id matches (in case LLM returned different one)
    result.thread_id = thread_id

    # -----------------------------
    # Deterministic enrichment step
    # -----------------------------
    INTERNAL_DOMAINS = {"pinnacle-insurance.co.uk"}

    def _extract_domain(addr: str) -> Optional[str]:
        if not addr:
            return None
        # Handle possible formats like "Name <email@domain>" or just "email@domain"
        s = addr.strip().lower()
        if "<" in s and ">" in s:
            s = s.split("<", 1)[1].split(">", 1)[0].strip()
        if "@" not in s:
            return None
        return s.split("@", 1)[1].strip()

    # Look at all senders in the thread and take the first external domain
    sender_domains = []
    for msg in thread.messages:
        d = _extract_domain(getattr(msg, "sent_from", None))
        if d:
            sender_domains.append(d)

    broker_domain = next((d for d in sender_domains if d not in INTERNAL_DOMAINS), None)

    if broker_domain:
        if result.key_entities is None:
            result.key_entities = {}

        current = result.key_entities.get("broker_domain")
        if current in (None, "", "unknown"):
            result.key_entities["broker_domain"] = broker_domain

    logger.info(f"Successfully triaged thread {thread_id}")
    return result


def triage_emails(
    email_data: EmailData,
    redact: bool = False,
    max_threads: Optional[int] = None
) -> List[ThreadTriageResult]:
    """
    Triage all email threads.
    
    Args:
        email_data: Email data to triage
        redact: Whether to redact sensitive data
        max_threads: Maximum number of threads to process (None = all)
        
    Returns:
        List of ThreadTriageResult objects
    """
    threads_to_process = email_data.emails
    
    if max_threads is not None and max_threads > 0:
        threads_to_process = threads_to_process[:max_threads]
        logger.info(f"Processing {len(threads_to_process)} of {len(email_data.emails)} threads (max_threads={max_threads})")
    else:
        logger.info(f"Starting triage for {len(threads_to_process)} email threads")
    
    results = []
    for i, thread in enumerate(threads_to_process, 1):
        try:
            result = triage_email_thread(thread, redact=redact)
            results.append(result)
            logger.debug(f"Completed {i}/{len(threads_to_process)}")
        except Exception as e:
            logger.error(f"Failed to triage thread {thread.messages[0].thread_id if thread.messages else 'unknown'}: {e}")
            # Continue with next thread
            continue
    
    logger.info(f"Completed triage for {len(results)} threads")
    return results
