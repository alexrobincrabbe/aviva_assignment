"""
Deterministic query engine for ThreadTriageResult records.

This module executes "structured queries" (filters/sorts/limits/field selection)
over a list of ThreadTriageResult objects produced by the triage step.

It is intentionally LLM-free and deterministic.
"""

import logging
from typing import Any, Dict, List

from app.domain.models import ThreadTriageResult

logger = logging.getLogger(__name__)

# -----------------------------
# Queryable fields
# -----------------------------

# Top-level fields
TOP_LEVEL_FIELDS = {
    "thread_id",
    "classification",
    "priority",
    "due_by",
    "topic",
    "summary",
    "required_actions",
    "key_entities",
    "evidence_snippets",
    "confidence",
}

# Fields expected inside key_entities
KEY_ENTITY_FIELDS = {
    "claim_ref",
    "invoice_no",
    "broker_name",
    "broker_domain",
    "amount",
    "currency",
    "policy_number",
    "customer_name",
    "loss_location",
    "loss_date",
    "vehicle_reg",
    "third_party_name",
}

# Derived fields
DERIVED_FIELDS = {
    "action_required",  # boolean: classification == "action_required"
    # Optional: uncomment if you add it to your Ask router/query plans
    # "text_blob",  # derived searchable blob across topic/summary/actions/entities
}

QUERYABLE_FIELDS = TOP_LEVEL_FIELDS | KEY_ENTITY_FIELDS | DERIVED_FIELDS

SUPPORTED_OPS = {"equals", "contains", "in", "gte", "lte"}

PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}


def _get_field_value(result: ThreadTriageResult, field: str) -> Any:
    """Extract a field value from ThreadTriageResult (top-level, key_entities, or derived)."""
    if field == "action_required":
        return result.classification == "action_required"

    # Optional derived field for robust text searching. Enable if you want it.
    # if field == "text_blob":
    #     parts = [
    #         result.topic or "",
    #         result.summary or "",
    #         " ".join(result.required_actions or []),
    #     ]
    #     if result.key_entities:
    #         parts.append(str(result.key_entities))
    #     return " ".join(p for p in parts if p).strip()

    if field in TOP_LEVEL_FIELDS:
        return getattr(result, field, None)

    if field in KEY_ENTITY_FIELDS:
        # key_entities is expected to be a dict
        if not result.key_entities:
            return None
        return result.key_entities.get(field)

    raise ValueError(f"Unknown field: {field}")


def _apply_filter(result: ThreadTriageResult, filter_spec: Dict[str, Any]) -> bool:
    """
    Apply a single filter to a ThreadTriageResult.

    filter_spec format:
      {"field": "...", "op": "equals|contains|in|gte|lte", "value": ...}
    """
    field = filter_spec.get("field")
    op = filter_spec.get("op")
    value = filter_spec.get("value")

    if field not in QUERYABLE_FIELDS:
        raise ValueError(f"Unknown field '{field}'. Allowed fields: {sorted(QUERYABLE_FIELDS)}")

    if op not in SUPPORTED_OPS:
        raise ValueError(f"Unknown operator '{op}'. Supported operators: {sorted(SUPPORTED_OPS)}")

    field_value = _get_field_value(result, field)

    # None handling
    if field_value is None:
        return op == "equals" and value is None

    # equals
    if op == "equals":
        return field_value == value

    # contains (case-insensitive)
    if op == "contains":
        if isinstance(field_value, str) and isinstance(value, str):
            return value.lower() in field_value.lower()

        if isinstance(field_value, list) and isinstance(value, str):
            return any(value.lower() in str(item).lower() for item in field_value)

        # Allow contains on dict (stringified)
        if isinstance(field_value, dict) and isinstance(value, str):
            return value.lower() in str(field_value).lower()

        return False

    # in
    if op == "in":
        if not isinstance(value, list):
            raise ValueError(f"Operator 'in' requires value to be a list, got {type(value)}")
        return field_value in value

    # gte / lte
    if op in {"gte", "lte"}:
        # Special-case priority ordering
        if field == "priority" and isinstance(field_value, str) and isinstance(value, str):
            fv = PRIORITY_ORDER.get(field_value, 99)
            vv = PRIORITY_ORDER.get(value, 99)

            # Note: lower number = higher priority
            if op == "gte":
                # "gte P1" means P0 or P1 (higher/equal urgency) => fv <= vv
                return fv <= vv
            else:
                # "lte P1" means P1, P2, P3 (lower/equal urgency) => fv >= vv
                return fv >= vv

        # Numeric compare
        if isinstance(field_value, (int, float)) and isinstance(value, (int, float)):
            return field_value >= value if op == "gte" else field_value <= value

        # String compare (lexicographic) - OK for ISO dates if consistently formatted
        if isinstance(field_value, str) and isinstance(value, str):
            return field_value >= value if op == "gte" else field_value <= value

        raise ValueError(f"Cannot compare {type(field_value)} with {type(value)} using '{op}'")

    # Should be unreachable
    raise ValueError(f"Unsupported operator: {op}")


def _apply_sort_key(result: ThreadTriageResult, field: str) -> Any:
    """Return a stable sort key for a given field."""
    value = _get_field_value(result, field)

    # None values sort last
    if value is None:
        return (1, "")

    # priority: P0 first
    if field == "priority" and isinstance(value, str):
        return (0, PRIORITY_ORDER.get(value, 99))

    # bool: False then True
    if isinstance(value, bool):
        return (0, 1 if value else 0)

    # list: first element
    if isinstance(value, list):
        return (0, value[0] if value else "")

    return (0, value)


def execute_query(results: List[ThreadTriageResult], query: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Execute a structured query over triage results.

    Query format:
    {
        "filters": [{"field": "...", "op": "...", "value": ...}, ...],
        "sort": [{"field": "...", "direction": "asc"|"desc"}, ...],
        "limit": 20,
        "return_fields": ["thread_id","topic","priority",...]
    }
    """
    logger.info("Executing query over %d results", len(results))

    filtered: List[ThreadTriageResult] = list(results)

    # Filters
    for f in query.get("filters", []) or []:
        if not isinstance(f, dict):
            raise ValueError(f"Filter must be a dict, got {type(f)}")
        if not {"field", "op", "value"} <= set(f.keys()):
            raise ValueError("Each filter must have 'field', 'op', and 'value'")
        filtered = [r for r in filtered if _apply_filter(r, f)]

    # Sorting
    sort_specs = query.get("sort", []) or []
    if sort_specs:
        # Apply in reverse so last key is primary (stable sorts)
        for s in reversed(sort_specs):
            if not isinstance(s, dict):
                raise ValueError(f"Sort spec must be a dict, got {type(s)}")
            field = s.get("field")
            if field not in QUERYABLE_FIELDS:
                raise ValueError(f"Unknown sort field '{field}'. Allowed fields: {sorted(QUERYABLE_FIELDS)}")
            direction = (s.get("direction") or "asc").lower()
            if direction not in {"asc", "desc"}:
                raise ValueError("Sort direction must be 'asc' or 'desc'")
            reverse = direction == "desc"
            filtered.sort(key=lambda r, f=field: _apply_sort_key(r, f), reverse=reverse)

    # Limit
    limit = query.get("limit")
    if limit is not None:
        if not isinstance(limit, int) or limit < 0:
            raise ValueError(f"Limit must be a non-negative integer, got {limit}")
        filtered = filtered[:limit]

    # Field selection
    return_fields = query.get("return_fields")
    if return_fields is None:
        return [r.model_dump() for r in filtered]

    if not isinstance(return_fields, list):
        raise ValueError(f"return_fields must be a list, got {type(return_fields)}")

    for field in return_fields:
        if field not in QUERYABLE_FIELDS:
            raise ValueError(f"Unknown return field '{field}'. Allowed fields: {sorted(QUERYABLE_FIELDS)}")

    output: List[Dict[str, Any]] = []
    for r in filtered:
        item: Dict[str, Any] = {}
        for field in return_fields:
            item[field] = _get_field_value(r, field)
        output.append(item)

    logger.info("Query returned %d results", len(output))
    return output


def pretty_print_results(results: List[Dict[str, Any]], max_width: int = 100) -> str:
    """Pretty-print query results for CLI output."""
    if not results:
        return "No results found."

    lines: List[str] = []
    lines.append(f"Found {len(results)} result(s):")
    lines.append("=" * max_width)

    for i, result in enumerate(results, 1):
        lines.append(f"\n[{i}]")
        for key, value in result.items():
            if value is None:
                display = "null"
            elif isinstance(value, list):
                if not value:
                    display = "[]"
                elif len(value) <= 3:
                    display = ", ".join(str(v) for v in value)
                else:
                    display = f"{', '.join(str(v) for v in value[:3])}, ... ({len(value)} total)"
            elif isinstance(value, dict):
                s = str(value)
                display = (s[:50] + "...") if len(s) > 50 else s
            else:
                display = str(value)

            if len(display) > max_width - len(key) - 3:
                display = display[: max_width - len(key) - 10] + "..."

            lines.append(f"  {key}: {display}")

        if i < len(results):
            lines.append("-" * max_width)

    return "\n".join(lines)
