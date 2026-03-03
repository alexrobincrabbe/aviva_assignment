"""Email data loading utilities."""

import json
import logging
import re
from pathlib import Path
from typing import List, Dict
from datetime import datetime

from app.domain.models import EmailData, EmailThread, Message, Attachment, EmailMessage

logger = logging.getLogger(__name__)


def load_messages(path: str | Path) -> List[EmailMessage]:
    """
    Load and parse email messages from JSON file.
    
    Args:
        path: Path to emails.json file
        
    Returns:
        List of EmailMessage objects with normalized fields
        
    Raises:
        FileNotFoundError: If the file doesn't exist
        json.JSONDecodeError: If the file is not valid JSON
        ValueError: If message data is invalid
    """
    path = Path(path)
    
    if not path.exists():
        raise FileNotFoundError(f"Email file not found: {path}")
    
    logger.info(f"Loading messages from {path}")
    
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    messages = []
    for email_item in data.get('emails', []):
        for msg_data in email_item.get('messages', []):
            try:
                # Parse with Pydantic, using field aliases
                message = EmailMessage.model_validate(msg_data)
                messages.append(message)
            except Exception as e:
                logger.warning(f"Failed to parse message {msg_data.get('message_id', 'unknown')}: {e}")
                continue
    
    logger.info(f"Loaded {len(messages)} messages")
    return messages


def group_by_thread(messages: List[EmailMessage]) -> Dict[str, List[EmailMessage]]:
    """
    Group messages by thread_id, sorted by sent_at within each thread.
    
    Args:
        messages: List of EmailMessage objects
        
    Returns:
        Dictionary mapping thread_id to sorted list of messages
    """
    threads: Dict[str, List[EmailMessage]] = {}
    
    for message in messages:
        thread_id = message.thread_id
        if thread_id not in threads:
            threads[thread_id] = []
        threads[thread_id].append(message)
    
    # Sort messages within each thread by sent_at
    for thread_id in threads:
        threads[thread_id].sort(key=lambda m: m.sent_at)
    
    logger.debug(f"Grouped {len(messages)} messages into {len(threads)} threads")
    return threads


def clean_body(text: str) -> str:
    """
    Strip common quoted reply separators and signatures from email body.
    
    Uses basic heuristics to detect:
    - Quoted reply separators (e.g., "On ... wrote:", "From:", "---")
    - Common signature patterns
    
    Args:
        text: Raw email body text
        
    Returns:
        Cleaned email body text
    """
    if not text:
        return text
    
    lines = text.split('\n')
    cleaned_lines = []
    in_quoted_section = False
    
    # Patterns that indicate start of quoted reply
    quote_patterns = [
        r'^On .+ wrote:',
        r'^From:',
        r'^-----Original Message-----',
        r'^---',
        r'^>+',
        r'^From:.*Sent:',
        r'^Date:.*From:',
    ]
    
    # Patterns that indicate signatures
    signature_patterns = [
        r'^--\s*$',
        r'^Best regards',
        r'^Regards,',
        r'^Thanks,',
        r'^Sincerely,',
        r'^Sent from',
    ]
    
    for i, line in enumerate(lines):
        line_stripped = line.strip()
        
        # Check for quoted reply separators
        if not in_quoted_section:
            for pattern in quote_patterns:
                if re.match(pattern, line_stripped, re.IGNORECASE):
                    in_quoted_section = True
                    break
        
        # Check for signature patterns (stop processing after signature)
        if not in_quoted_section:
            for pattern in signature_patterns:
                if re.match(pattern, line_stripped, re.IGNORECASE):
                    # Include this line but stop after
                    cleaned_lines.append(line)
                    return '\n'.join(cleaned_lines)
        
        # Skip quoted sections
        if in_quoted_section:
            # Check if we're still in quoted section (lines starting with > or empty lines)
            if line_stripped.startswith('>') or not line_stripped:
                continue
            # If we hit non-quoted content, we might have passed the quoted section
            # But be conservative - once we enter quoted section, stay there
            continue
        
        cleaned_lines.append(line)
    
    cleaned = '\n'.join(cleaned_lines)
    
    # Remove trailing whitespace and multiple blank lines
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    cleaned = cleaned.rstrip()
    
    return cleaned


def print_dataset_stats(path: str | Path) -> None:
    """
    Print statistics about the email dataset.
    
    Args:
        path: Path to emails.json file
    """
    try:
        messages = load_messages(path)
        threads = group_by_thread(messages)
        
        if not messages:
            print("No messages found in dataset")
            return
        
        # Find earliest and latest dates
        dates = [msg.sent_at for msg in messages]
        earliest = min(dates)
        latest = max(dates)
        
        print("=" * 60)
        print("Email Dataset Statistics")
        print("=" * 60)
        print(f"Number of threads: {len(threads)}")
        print(f"Number of messages: {len(messages)}")
        print(f"Earliest date: {earliest.isoformat()}")
        print(f"Latest date: {latest.isoformat()}")
        print(f"Date range: {(latest - earliest).days} days")
        print("=" * 60)
        
        # Additional stats
        messages_per_thread = [len(msgs) for msgs in threads.values()]
        if messages_per_thread:
            avg_messages = sum(messages_per_thread) / len(messages_per_thread)
            print(f"Average messages per thread: {avg_messages:.2f}")
            print(f"Max messages in a thread: {max(messages_per_thread)}")
            print(f"Min messages in a thread: {min(messages_per_thread)}")
        
    except Exception as e:
        print(f"Error loading dataset: {e}")
        logger.error(f"Error in print_dataset_stats: {e}", exc_info=True)


def load_emails(file_path: str | Path) -> EmailData:
    """
    Load emails from JSON file (backward compatibility function).
    
    This function maintains compatibility with existing code that expects
    EmailData/EmailThread structure. Internally uses the new Pydantic models.
    
    Args:
        file_path: Path to emails.json file
        
    Returns:
        EmailData object containing parsed email data
        
    Raises:
        FileNotFoundError: If the file doesn't exist
        json.JSONDecodeError: If the file is not valid JSON
    """
    file_path = Path(file_path)
    
    if not file_path.exists():
        raise FileNotFoundError(f"Email file not found: {file_path}")
    
    logger.info(f"Loading emails from {file_path}")
    
    # Use new load_messages function
    email_messages = load_messages(file_path)
    
    # Group by thread
    threads_dict = group_by_thread(email_messages)
    
    # Convert to old schema format for backward compatibility
    email_threads = []
    for thread_id, messages in threads_dict.items():
        # Convert EmailMessage to old Message format
        old_messages = []
        for msg in messages:
            attachments = None
            if msg.attachments:
                attachments = [
                    Attachment(
                        filename=att.filename,
                        filesize=att.filesize,
                        filetype=att.filetype
                    )
                    for att in msg.attachments
                ]
            
            old_message = Message(
                body=msg.body,
                subject=msg.subject,
                sent_from=msg.sender,
                sent_to=msg.to,
                sent_cc=msg.cc,
                date_sent=msg.sent_at.isoformat(),
                attachments=attachments,
                importance_flag=msg.importance_flag,
                message_id=msg.message_id,
                thread_id=msg.thread_id
            )
            old_messages.append(old_message)
        
        email_threads.append(EmailThread(messages=old_messages))
    
    logger.info(f"Loaded {len(email_threads)} email threads")
    
    return EmailData(emails=email_threads)
