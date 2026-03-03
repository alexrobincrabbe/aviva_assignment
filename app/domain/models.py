"""Data schemas and helper models for email processing and triage."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator


@dataclass
class Attachment:
    """Email attachment schema (legacy dataclass)."""

    filename: str
    filesize: int
    filetype: str


@dataclass
class Message:
    """Raw email message schema (legacy dataclass)."""

    body: str
    subject: str
    sent_from: str
    sent_to: List[str]
    sent_cc: List[str]
    date_sent: str
    attachments: Optional[List[Attachment]]
    importance_flag: Optional[str]
    message_id: str
    thread_id: str


@dataclass
class EmailThread:
    """Email thread schema containing multiple messages (legacy dataclass)."""

    messages: List[Message]


@dataclass
class EmailData:
    """Top-level email data schema (legacy dataclass)."""

    emails: List[EmailThread]


class EmailAttachment(BaseModel):
    """Pydantic model for email attachment."""

    filename: str
    filesize: int
    filetype: str


class EmailMessage(BaseModel):
    """Pydantic model for normalized email message."""

    message_id: str
    thread_id: str
    subject: str
    body: str
    sender: str = Field(alias="sent_from")
    to: List[str] = Field(alias="sent_to")
    cc: List[str] = Field(default_factory=list, alias="sent_cc")
    sent_at: datetime = Field(alias="date_sent")
    attachments: List[EmailAttachment] = Field(default_factory=list)
    importance_flag: Optional[str] = None

    @field_validator("cc", mode="before")
    @classmethod
    def handle_null_cc(cls, v: Any) -> List[str]:
        """Convert null sent_cc to empty list."""
        return v if v is not None else []

    @field_validator("attachments", mode="before")
    @classmethod
    def handle_null_attachments(cls, v: Any) -> List[EmailAttachment]:
        """Convert null attachments to empty list."""
        return v if v is not None else []

    @field_validator("sent_at", mode="before")
    @classmethod
    def parse_datetime(cls, v: Any) -> datetime:
        """Parse ISO datetime string."""
        if isinstance(v, str):
            # Handle ISO format with Z timezone
            if v.endswith("Z"):
                v = v[:-1] + "+00:00"
            return datetime.fromisoformat(v)
        return v

    model_config = ConfigDict(populate_by_name=True)


class ThreadTriageResult(BaseModel):
    """Structured triage result for a single email thread."""

    thread_id: str
    classification: Literal[
        "action_required", "informational_archive", "irrelevant"
    ]
    priority: Literal["P0", "P1", "P2", "P3"]
    # due_by can be an ISO date (YYYY-MM-DD / full ISO) or reserved strings like "today", "COB"
    due_by: Optional[str] = None
    topic: str
    summary: str
    required_actions: List[str]
    key_entities: Dict[str, Any]
    evidence_snippets: List[str]
    confidence: float


class AskRouterDecision(BaseModel):
    """Router decision for 'ask' queries."""

    intent: Literal[
        "filter_lookup", "summarize_subset", "trend_analysis", "unanswerable", "smalltalk"
    ]
    confidence: float
    structured_query: Optional[Dict[str, Any]] = None
    needs_rag: bool


# ---------------------------------------------------------------------------
# JSONL helpers
# ---------------------------------------------------------------------------

def write_jsonl(path: str | Path, models: Sequence[BaseModel]) -> None:
    """Write a sequence of Pydantic models to a JSONL file.

    Each model is serialized as one JSON object per line.
    """
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)

    with file_path.open("w", encoding="utf-8") as f:
        for model in models:
            data = model.model_dump()
            f.write(json.dumps(data, ensure_ascii=False) + "\n")


def read_jsonl(path: str | Path) -> List[ThreadTriageResult]:
    """Read triage results from a JSONL file.

    Returns a list of ThreadTriageResult objects.
    """
    file_path = Path(path)
    results: List[ThreadTriageResult] = []

    if not file_path.exists():
        return results

    with file_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            results.append(ThreadTriageResult.model_validate(obj))

    return results


# ---------------------------------------------------------------------------
# Query schema constants for AskRouterDecision.structured_query
# ---------------------------------------------------------------------------

# Fields that a structured query is allowed to reference when filtering emails / threads.
ALLOWED_QUERY_FIELDS: List[str] = [
    # Core email metadata
    "thread_id",
    "message_id",
    "subject",
    "body",
    "sender",
    "to",
    "cc",
    "date",
    # Domain-specific entities
    "claim_ref",
    "policy_number",
    "invoice_no",
    "broker_name",
    "broker_domain",
    "customer_name",
    "amount",
    "postcode",
]

# Supported comparison / search operators for structured queries.
ALLOWED_QUERY_OPERATORS: List[str] = [
    "eq",          # equals
    "neq",         # not equals
    "contains",    # substring match
    "icontains",   # case-insensitive substring
    "startswith",
    "istartswith",
    "endswith",
    "iendswith",
    "in",          # field value in list
    "nin",         # field value not in list
    "gt",
    "gte",
    "lt",
    "lte",
    "between",     # range queries (e.g. dates, amounts)
]
