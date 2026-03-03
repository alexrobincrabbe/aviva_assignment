"""Ask module for querying triage results."""

import logging
import re
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional

from app.domain.models import ThreadTriageResult, AskRouterDecision, read_jsonl
from app.infra.query_engine import execute_query, QUERYABLE_FIELDS
from app.infra.llm import call_llm_json, call_llm_raw
from app.infra.redact import assert_no_pii
from app.utils import get_prompts_dir

logger = logging.getLogger(__name__)

# Supported operators for router
SUPPORTED_OPS = ["equals", "contains", "in", "gte", "lte"]


def _load_router_prompt() -> str:
    """Load router system prompt."""
    prompts_dir = get_prompts_dir()
    router_path = prompts_dir / "router_system.md"
    
    if router_path.exists():
        return router_path.read_text(encoding='utf-8')
    else:
        logger.warning(f"Router prompt not found at {router_path}")
        return ""


def _load_rag_answer_prompt() -> str:
    """Load RAG answer system prompt."""
    prompts_dir = get_prompts_dir()
    rag_path = prompts_dir / "rag_answer_system.md"
    
    if rag_path.exists():
        return rag_path.read_text(encoding='utf-8')
    else:
        logger.warning(f"RAG answer prompt not found at {rag_path}")
    return ""


def _build_searchable_text(result: ThreadTriageResult) -> str:
    """
    Build searchable text from a ThreadTriageResult for keyword matching.
    
    Args:
        result: ThreadTriageResult to convert
        
    Returns:
        Combined text from topic, summary, required_actions, and key_entities
    """
    parts = []
    
    if result.topic:
        parts.append(f"Topic: {result.topic}")
    
    if result.summary:
        parts.append(f"Summary: {result.summary}")
    
    if result.required_actions:
        actions_text = ", ".join(result.required_actions)
        parts.append(f"Actions: {actions_text}")
    
    if result.key_entities:
        # Format key entities as key: value pairs
        entity_parts = []
        for key, value in result.key_entities.items():
            if not value or value == "unknown":
                continue

            entity_parts.append(f"{key}: {value}")

            # If it's a domain, also add simplified tokens
            if key.endswith("domain") and isinstance(value, str):
                clean = value.lower()
                entity_parts.append(clean)

                # Remove TLD for extra matching power
                if "." in clean:
                    entity_parts.append(clean.split(".", 1)[0])
        if entity_parts:
            parts.append(f"Entities: {', '.join(entity_parts)}")
    
    parts.append(f"Priority: {result.priority}")
    if result.due_by:
        parts.append(f"Due by: {result.due_by}")
    
    return "\n".join(parts)

STOP_TOKENS = {
    "there", "any", "action", "required",
    "thread", "threads", "priority",
    "claim", "claims", "summary",
    "today", "first", "should"
}

def _score_keyword_overlap(text: str, question: str) -> float:
    """
    Score text relevance to question using substring matching
    for meaningful tokens (>=4 characters).
    """
    text_lower = text.lower()
    
    # Extract meaningful question tokens (length >= 4)
    question_tokens = [
        w for w in re.findall(r'\b\w+\b', question.lower())
        if len(w) >= 4 and w not in STOP_TOKENS
    ]
    
    if not question_tokens:
        return 0.0
    
    matches = 0
    for token in set(question_tokens):
        if token in text_lower:
            matches += 1
    
    return matches / len(set(question_tokens))

def _retrieve_top_k_candidates(
    results: List[ThreadTriageResult],
    question: str,
    top_k: int
) -> List[ThreadTriageResult]:
    """
    Retrieve top-k most relevant candidates using keyword overlap.
    
    Args:
        results: All ThreadTriageResult objects
        question: User question
        top_k: Number of candidates to retrieve
        
    Returns:
        List of top-k most relevant ThreadTriageResult objects
    """
    # Score each result
    scored = []
    for result in results:
        searchable_text = _build_searchable_text(result)
        score = _score_keyword_overlap(searchable_text, question)
        scored.append((score, result))
    
    # Sort by score (descending) and take top-k
    scored.sort(key=lambda x: x[0], reverse=True)
    top_results = [result for score, result in scored[:top_k]]
    
    logger.info(f"Retrieved top {len(top_results)} candidates (scores: {[f'{s:.2f}' for s, _ in scored[:top_k]]})")
    
    return top_results


def _format_candidate_for_rag(result: ThreadTriageResult) -> str:
    """
    Format a ThreadTriageResult as text for RAG context.
    
    Args:
        result: ThreadTriageResult to format
        
    Returns:
        Formatted text string
    """
    lines = [
        f"Thread ID: {result.thread_id}",
        f"Topic: {result.topic}",
        f"Classification: {result.classification}",
        f"Priority: {result.priority}",
    ]
    
    if result.due_by:
        lines.append(f"Due by: {result.due_by}")
    
    lines.append(f"Summary: {result.summary}")
    
    if result.required_actions:
        lines.append(f"Required actions: {', '.join(result.required_actions)}")
    
    if result.key_entities:
        entity_parts = []
        for key, value in result.key_entities.items():
            if value and value != "unknown":
                entity_parts.append(f"{key}={value}")
        if entity_parts:
            lines.append(f"Key entities: {', '.join(entity_parts)}")
    
    return "\n".join(lines)


def _handle_smalltalk() -> None:
    print("Hi — I can help you query the triage results.")
    print("Try:")
    print('  - "What should I focus on today?"')
    print('  - "Show me P0 priority threads"')
    print('  - "Threads due today"')

def _handle_filter_lookup(
    results: List[ThreadTriageResult],
    decision: AskRouterDecision,
    question: str
) -> None:
    """Handle filter_lookup intent."""
    if not decision.structured_query:
        print("No structured query provided for filter_lookup.")
        return
    
    # Execute query
    matching = execute_query(results, decision.structured_query)
    
    if not matching:
        print("No matching threads found.")
        return
    
    # Print short direct answer
    count = len(matching)
    print(f"Found {count} matching thread(s).")
    print()
    
    # List matching items (compact)
    print("Matching threads:")
    for i, item in enumerate(matching, 1):
        thread_id = item.get('thread_id', 'unknown')
        topic = item.get('topic', 'N/A')
        priority = item.get('priority', 'N/A')
        due_by = item.get('due_by') or 'N/A'
        
        print(f"  {i}. [{thread_id}] {topic} (Priority: {priority}, Due: {due_by})")
        
        # Show required_actions if present
        actions = item.get('required_actions', [])
        if actions:
            print(f"     Actions: {', '.join(actions[:2])}{'...' if len(actions) > 2 else ''}")


def _handle_rag_answer(
    results: List[ThreadTriageResult],
    question: str,
    top_k: int,
    decision: Optional[AskRouterDecision] = None,
) -> None:
    """Handle RAG-based answer (summarize_subset or trend_analysis)."""

    candidates: List[ThreadTriageResult] = []

    # Special-case: trend questions should use a broad, representative subset,
    # not keyword overlap (which biases toward literal token matches).
    if decision and decision.intent == "trend_analysis" and not decision.structured_query:
        actionable = [r for r in results if r.classification == "action_required"]

        priority_order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
        actionable.sort(
            key=lambda r: (
                priority_order.get(r.priority, 99),
                r.due_by or "9999-12-31",
            )
        )

        candidates = actionable[: max(top_k, 20)]

    # 1) Prefer deterministic candidate selection if router provided a structured query
    if decision and decision.structured_query:
        try:
            # Ensure the query returns enough fields to summarise
            q = dict(decision.structured_query)
            q.setdefault("limit", top_k)

            # We need thread_id to map back to full records
            q.setdefault("return_fields", ["thread_id"])

            matches = execute_query(results, q)
            match_ids = {m.get("thread_id") for m in matches if m.get("thread_id")}

            # Preserve order from matches
            id_to_result = {r.thread_id: r for r in results}
            candidates = [id_to_result[tid] for tid in [m["thread_id"] for m in matches if m.get("thread_id")] if tid in id_to_result]

            logger.info(f"Selected {len(candidates)} candidates via structured_query")
        except Exception as e:
            logger.warning(f"Structured candidate selection failed; falling back to keyword retrieval. Error: {e}")
            candidates = []

    # 2) If structured query returned nothing, try keyword overlap
    if not candidates:
        overlap_candidates = _retrieve_top_k_candidates(results, question, top_k)

        # Check if overlap has any signal
        best_score = 0.0
        if overlap_candidates:
            best_text = _build_searchable_text(overlap_candidates[0])
            best_score = _score_keyword_overlap(best_text, question)

        if best_score >= 0.15:
            logger.info(f"Using keyword overlap retrieval (best_score={best_score:.2f})")
            candidates = overlap_candidates
        else:
            logger.info("No strong overlap signal. Falling back to deterministic priority selection.")

            # Deterministic fallback: actionable threads sorted by priority then due_by
            actionable = [r for r in results if r.classification == "action_required"]

            # Sort by priority (P0 first) then due_by (None last)
            priority_order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
            actionable.sort(
                key=lambda r: (
                    priority_order.get(r.priority, 99),
                    r.due_by or "9999-12-31"
                )
            )

            candidates = actionable[:top_k]

    if not candidates:
        print("No relevant threads found to answer this question.")
        return

    # Format candidates for RAG context
    candidate_texts = [_format_candidate_for_rag(c) for c in candidates]
    context = "\n\n---\n\n".join(candidate_texts)

    is_trend = decision and decision.intent == "trend_analysis"

    if is_trend:
        answer_rules = """
    - This is a trend analysis question.
    - Only say something is recurring if you can cite at least 2 different thread IDs.
    - If only 0–1 supporting threads exist, say:
    "No clear recurring pattern in the provided threads."
    """
    else:
        answer_rules = """
    - Answer directly and concisely.
    """

    user_prompt = f"""Question: {question}

    Candidate thread records:

    {context}

    You must answer using ONLY the candidate threads above.

    OUTPUT RULES
    - Output plain text only.
    - No markdown.
    - When referencing a thread, cite it inline like (thr_xxx).
    - Do NOT invent facts.

    {answer_rules}
    """




    system_prompt = _load_rag_answer_prompt()

    logger.info(f"Calling RAG LLM with {len(candidates)} candidates")
    answer = call_llm_raw(system=system_prompt, user=user_prompt)

    try:
        assert_no_pii(answer)
    except ValueError as e:
        logger.warning(f"PII check failed: {e}")

    print(answer.strip())


def _handle_unanswerable(question: str) -> None:
    """Handle unanswerable intent."""
    print("This question cannot be answered from the triage results.")
    print()
    print("The triage results contain:")
    print("  - Thread classifications and priorities")
    print("  - Topics, summaries, and required actions")
    print("  - Key entities (claim references, broker names, etc.)")
    print()
    print("What is missing:")
    print("  - Attachment contents (PDFs, images, etc.)")
    print("  - External system status (payment confirmations, external databases)")
    print("  - Real-time information (current status, live updates)")
    print()
    print("Instead, you can ask:")
    print("  - 'Show me P0 priority threads'")
    print("  - 'What claims are from Bridgegate Brokers?'")
    print("  - 'What needs attention today?'")
    print("  - 'Summarize action_required threads'")


def ask_command(
    triage_results_path: str,
    question: str,
    top_k: int = 5,
) -> None:
    """
    Execute the ask command to answer questions about triage results.
    
    Args:
        triage_results_path: Path to triage_results.jsonl file
        question: Question to answer
        top_k: Number of candidates for RAG retrieval (default: 5)
    """
    logger.info(f"Ask command: {question}")
    
    # Load triage results
    results_path = Path(triage_results_path)
    if not results_path.exists():
        print(f"Error: Triage results file not found: {triage_results_path}")
        return
    
    results = read_jsonl(results_path)
    logger.info(f"Loaded {len(results)} triage results")
    
    if not results:
        print("No triage results found in file.")
        return
    
    # Call router LLM
    router_prompt = _load_router_prompt()
    
    # Build router user prompt with allowed fields and ops
    allowed_fields = sorted(QUERYABLE_FIELDS)
    router_user = f"""Question: {question}

Allowed query fields: {', '.join(allowed_fields)}
Allowed operators: {', '.join(SUPPORTED_OPS)}

Output the routing decision as JSON."""
    
    logger.info("Calling router LLM")
    try:
        decision = call_llm_json(
            model_cls=AskRouterDecision,
            system=router_prompt,
            user=router_user
        )
        logger.info(f"Router decision: intent={decision.intent}, needs_rag={decision.needs_rag}, confidence={decision.confidence}")
        if decision.structured_query:
            logger.info(f"Router structured_query: {decision.structured_query}")
    
    except Exception as e:
        logger.error(f"Router LLM call failed: {e}")
        print(f"Error: Failed to route question: {e}")
        return
    
    # Handle based on intent
    print()
    if decision.intent == "filter_lookup":
        _handle_filter_lookup(results, decision, question)
    
    elif decision.intent in ("summarize_subset", "trend_analysis"):
        if decision.needs_rag:
            _handle_rag_answer(results, question, top_k, decision=decision)
        else:
            # Fallback: if needs_rag is False but intent suggests RAG, use structured query if available
            if decision.structured_query:
                _handle_filter_lookup(results, decision, question)
            else:
                _handle_rag_answer(results, question, top_k, decision=decision)
    

    elif decision.intent == "smalltalk":
        _handle_smalltalk()

    elif decision.intent == "unanswerable":
        # Safety net: router can be wrong. Do a cheap retrieval check before giving up.
        candidates = _retrieve_top_k_candidates(results, question, top_k)

        # Decide if retrieval found anything meaningful
        # (tune threshold; 0.10–0.20 works ok for short questions)
        best_score = 0.0
        if candidates:
            best_text = _build_searchable_text(candidates[0])
            best_score = _score_keyword_overlap(best_text, question)

        if best_score >= 0.15:
            logger.info(f"Router said unanswerable but retrieval found candidates (best_score={best_score:.2f}). Falling back to RAG.")
            _handle_rag_answer(results, question, top_k, decision=decision)
        else:
            _handle_unanswerable(question)

    
    else:
        print(f"Unknown intent: {decision.intent}")
