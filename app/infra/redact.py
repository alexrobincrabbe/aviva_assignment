"""Email redaction utilities with deterministic token mapping."""

import logging
import re
from typing import Dict, List, Tuple, Optional
from collections import OrderedDict

from app.domain.models import EmailMessage

logger = logging.getLogger(__name__)


class RedactionMap:
    """
    Stores mappings between original PII values and redaction tokens.
    
    Ensures deterministic redaction: the same original value always maps
    to the same token within a single run.
    """
    
    def __init__(self):
        """Initialize empty redaction map."""
        # Use OrderedDict to maintain insertion order for deterministic numbering
        self._email_map: Dict[str, str] = OrderedDict()
        self._phone_map: Dict[str, str] = OrderedDict()
        self._postcode_map: Dict[str, str] = OrderedDict()
        
        # Counters for generating token numbers
        self._email_counter = 1
        self._phone_counter = 1
        self._postcode_counter = 1
    
    def get_email_token(self, email: str) -> str:
        """
        Get or create token for an email address.
        
        Args:
            email: Email address to tokenize
            
        Returns:
            Token like <EMAIL_1>, <EMAIL_2>, etc.
        """
        email_lower = email.lower().strip()
        if email_lower not in self._email_map:
            token = f"<EMAIL_{self._email_counter}>"
            self._email_map[email_lower] = token
            self._email_counter += 1
        return self._email_map[email_lower]
    
    def get_phone_token(self, phone: str) -> str:
        """
        Get or create token for a phone number.
        
        Args:
            phone: Phone number to tokenize
            
        Returns:
            Token like <PHONE_1>, <PHONE_2>, etc.
        """
        # Normalize phone number for consistent mapping
        normalized = self._normalize_phone(phone)
        if normalized not in self._phone_map:
            token = f"<PHONE_{self._phone_counter}>"
            self._phone_map[normalized] = token
            self._phone_counter += 1
        return self._phone_map[normalized]
    
    def get_postcode_token(self, postcode: str) -> str:
        """
        Get or create token for a UK postcode.
        
        Args:
            postcode: Postcode to tokenize
            
        Returns:
            Token like <POSTCODE_1>, <POSTCODE_2>, etc.
        """
        # Normalize postcode (uppercase, remove spaces)
        normalized = postcode.upper().replace(' ', '')
        if normalized not in self._postcode_map:
            token = f"<POSTCODE_{self._postcode_counter}>"
            self._postcode_map[normalized] = token
            self._postcode_counter += 1
        return self._postcode_map[normalized]
    
    @staticmethod
    def _normalize_phone(phone: str) -> str:
        """
        Normalize phone number for consistent mapping.
        
        Removes spaces and converts to standard format.
        """
        # Remove all spaces and common separators
        normalized = re.sub(r'[\s\-\(\)]', '', phone)
        # Convert +44 to 0 if present
        if normalized.startswith('+44'):
            normalized = '0' + normalized[3:]
        return normalized
    
    def get_all_mappings(self) -> Dict[str, Dict[str, str]]:
        """
        Get all mappings for inspection/debugging.
        
        Returns:
            Dictionary with 'emails', 'phones', 'postcodes' keys
        """
        return {
            'emails': dict(self._email_map),
            'phones': dict(self._phone_map),
            'postcodes': dict(self._postcode_map)
        }
    
    def reverse_lookup(self, token: str) -> Optional[str]:
        """
        Reverse lookup: get original value from token.
        
        Args:
            token: Redaction token like <EMAIL_1>
            
        Returns:
            Original value if found, None otherwise
        """
        # Search all maps
        for email, tok in self._email_map.items():
            if tok == token:
                return email
        for phone, tok in self._phone_map.items():
            if tok == token:
                return phone
        for postcode, tok in self._postcode_map.items():
            if tok == token:
                return postcode
        return None


# Patterns for detecting PII (excluding operational identifiers)

# Email pattern - standard email format
EMAIL_PATTERN = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'

# UK phone number patterns
# Strategy: Match common UK phone formats
# - Mobile: 07783 112909 (0 + 4 digits + space + 6 digits) or 07783112909
# - Landline: 020 1234 5678 (0 + area code + space + digits) or 0113 123 4567
# - International: +44 20 1234 5678 or +447783112909
PHONE_PATTERNS = [
    # UK mobile with space: 07783 112909 (0 + 4 digits + space + 6 digits)
    r'\b07\d{3}\s\d{6}\b',
    # UK mobile without space: 07783112909
    r'\b07\d{9}\b',
    # UK landline with spaces: 020 1234 5678, 0113 123 4567
    r'\b0\d{2,3}\s\d{3,4}\s\d{3,4}\b',
    # UK landline without spaces: 02012345678
    r'\b0\d{9,10}\b',
    # International UK format with spaces: +44 20 1234 5678, +44 7783 112909
    # Note: After +44, mobile numbers have 10 digits, landlines have 9-10 digits
    # Use lookbehind/lookahead instead of \b for + character
    r'(?<!\d)\+44\s+\d{2}\s+\d{4}\s+\d{4}(?!\d)',  # +44 20 1234 5678 (landline format)
    r'(?<!\d)\+44\s+\d{4}\s+\d{6}(?!\d)',  # +44 7783 112909 (mobile format)
    # International UK format without spaces: +442012345678, +447783112909
    r'(?<!\d)\+44\d{9,10}(?!\d)',
]

# UK postcode patterns
# Strategy: Match common UK postcode formats but exclude claim references
# Formats: AB10, AB1 2CD, SW1A 1AA, etc.
# We exclude patterns that look like claim references (e.g., PIN-HOM-533661)
POSTCODE_PATTERNS = [
    # Short format: AB10, YO1, LE2 (area + district, no space)
    r'\b([A-Z]{1,2}\d{1,2})\b',
    # Full format: AB1 2CD, SW1A 1AA (area + district + space + sector + unit)
    r'\b([A-Z]{1,2}\d{1,2}[A-Z]?)\s+(\d[A-Z]{2})\b',
]

# Pattern to exclude claim references (operational identifiers)
# Matches: PIN-HOM-533661, PIN-MTR-552301, HOM-LT-882113, etc.
CLAIM_REF_PATTERN = r'\b(?:PIN|HOM|MTR|MOT|CAR|LT)[-_][A-Z]{2,}[-_]\d+\b'


def _is_claim_reference(text: str, start_pos: int, end_pos: int) -> bool:
    """
    Check if a matched pattern is part of a claim reference.
    
    We need to check the context around the match to avoid redacting
    operational identifiers like PIN-HOM-533661.
    
    Args:
        text: Full text being processed
        start_pos: Start position of match
        end_pos: End position of match
        
    Returns:
        True if this appears to be a claim reference
    """
    # Check a wider context around the match
    context_start = max(0, start_pos - 20)
    context_end = min(len(text), end_pos + 20)
    context = text[context_start:context_end]
    
    # Check if claim reference pattern appears in context
    return bool(re.search(CLAIM_REF_PATTERN, context, re.IGNORECASE))


def redact_text(text: str, m: RedactionMap, redact_postcodes: bool = True) -> str:
    """
    Redact PII from text using deterministic token mapping.
    
    Strategy:
    - Email addresses: Replaced with <EMAIL_N> tokens
    - Phone numbers: Replaced with <PHONE_N> tokens (UK formats)
    - Postcodes: Optionally replaced with <POSTCODE_N> tokens
    - Claim references (PIN-HOM-XXXXXX, etc.) are NOT redacted
    
    Args:
        text: Text to redact
        m: RedactionMap instance for token mapping
        redact_postcodes: Whether to redact UK postcodes (default: True)
        
    Returns:
        Redacted text with PII replaced by tokens
    """
    result = text
    
    # Redact email addresses
    def replace_email(match):
        email = match.group(0)
        # Check if it's part of a claim reference (unlikely but be safe)
        if not _is_claim_reference(text, match.start(), match.end()):
            return m.get_email_token(email)
        return email
    
    result = re.sub(EMAIL_PATTERN, replace_email, result)
    
    # Redact phone numbers
    def replace_phone(match):
        phone = match.group(0)
        if not _is_claim_reference(text, match.start(), match.end()):
            return m.get_phone_token(phone)
        return phone
    
    for pattern in PHONE_PATTERNS:
        result = re.sub(pattern, replace_phone, result, flags=re.IGNORECASE)
    
    # Redact postcodes (optional)
    if redact_postcodes:
        def replace_postcode(match):
            postcode = match.group(0)
            # Check if it's part of a claim reference
            if not _is_claim_reference(text, match.start(), match.end()):
                return m.get_postcode_token(postcode)
            return postcode
        
        for pattern in POSTCODE_PATTERNS:
            result = re.sub(pattern, replace_postcode, result)
    
    return result


def redact_message(msg: EmailMessage, m: RedactionMap, redact_postcodes: bool = True) -> EmailMessage:
    """
    Redact PII from an EmailMessage object.
    
    Redacts: body, subject, sender, to, cc fields.
    Preserves: message_id, thread_id, sent_at, attachments, importance_flag.
    
    Args:
        msg: EmailMessage to redact
        m: RedactionMap instance for token mapping
        redact_postcodes: Whether to redact UK postcodes (default: True)
        
    Returns:
        New EmailMessage with redacted fields
    """
    # Redact text fields
    redacted_body = redact_text(msg.body, m, redact_postcodes=redact_postcodes)
    redacted_subject = redact_text(msg.subject, m, redact_postcodes=redact_postcodes)
    
    # Redact sender (email address)
    redacted_sender = redact_text(msg.sender, m, redact_postcodes=False)
    
    # Redact to and cc lists (each is a list of email addresses)
    redacted_to = [redact_text(addr, m, redact_postcodes=False) for addr in msg.to]
    redacted_cc = [redact_text(addr, m, redact_postcodes=False) for addr in msg.cc]
    
    # Create new message with redacted fields
    return EmailMessage(
        message_id=msg.message_id,
        thread_id=msg.thread_id,
        subject=redacted_subject,
        body=redacted_body,
        sender=redacted_sender,
        to=redacted_to,
        cc=redacted_cc,
        sent_at=msg.sent_at,
        attachments=msg.attachments,
        importance_flag=msg.importance_flag
    )


def redact_thread(thread: List[EmailMessage], redact_postcodes: bool = True) -> Tuple[str, RedactionMap]:
    """
    Redact a thread of messages and return concatenated text plus mapping.
    
    Strategy:
    - Creates a single RedactionMap for the entire thread
    - Redacts all messages in the thread
    - Concatenates redacted messages with clear separators
    - Returns the concatenated text and the mapping for potential reversal
    
    Args:
        thread: List of EmailMessage objects in the thread
        redact_postcodes: Whether to redact UK postcodes (default: True)
        
    Returns:
        Tuple of (concatenated redacted text, RedactionMap)
    """
    m = RedactionMap()
    
    # Redact all messages
    redacted_messages = [
        redact_message(msg, m, redact_postcodes=redact_postcodes)
        for msg in thread
    ]
    
    # Concatenate with clear separators
    parts = []
    for i, msg in enumerate(redacted_messages):
        parts.append(f"=== Message {i+1} ===")
        parts.append(f"Subject: {msg.subject}")
        parts.append(f"From: {msg.sender}")
        parts.append(f"To: {', '.join(msg.to)}")
        if msg.cc:
            parts.append(f"CC: {', '.join(msg.cc)}")
        parts.append(f"Date: {msg.sent_at.isoformat()}")
        parts.append(f"Thread ID: {msg.thread_id}")
        parts.append(f"Message ID: {msg.message_id}")
        parts.append("")
        parts.append(msg.body)
        parts.append("")
    
    concatenated = "\n".join(parts)
    
    return concatenated, m


def assert_no_pii(text: str) -> None:
    """
    Assert that text contains no raw email addresses or phone numbers.
    
    Raises ValueError if PII is detected. Used for validation after redaction.
    
    Args:
        text: Text to check
        
    Raises:
        ValueError: If email addresses or phone numbers are detected
    """
    errors = []
    
    # Check for email addresses
    email_matches = re.findall(EMAIL_PATTERN, text)
    if email_matches:
        errors.append(f"Found {len(email_matches)} email address(es): {email_matches[:3]}")
    
    # Check for phone numbers
    phone_matches = []
    for pattern in PHONE_PATTERNS:
        phone_matches.extend(re.findall(pattern, text, re.IGNORECASE))
    if phone_matches:
        errors.append(f"Found {len(phone_matches)} phone number(s): {phone_matches[:3]}")
    
    if errors:
        error_msg = "PII detected in text:\n" + "\n".join(errors)
        raise ValueError(error_msg)
