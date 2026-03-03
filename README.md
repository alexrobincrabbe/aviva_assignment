# Email Triage & Workload Prioritisation CLI

A Python CLI application that helps insurance operations handlers triage high-volume email threads, prioritise required actions, and interact with their workload using free-text questions.

The system combines LLM-based reasoning with deterministic filtering and structured queries to balance intelligence, reliability, and auditability.

---

## 🎯 Problem Addressed

Insurance operations handlers receive a large number of daily emails from brokers, customers, internal teams, and automated systems. These emails vary in:

- Relevance
- Required action
- Urgency
- Operational impact

This tool:

- Classifies email threads into actionable / informational / irrelevant
- Assigns operational priority (P0–P3)
- Extracts required actions
- Generates a daily workload digest
- Produces an auditable record of system decisions
- Allows interactive free-text queries over triage results

---

# Features

## 1️⃣ LLM-Based Triage

Each email thread is analysed and structured into:

- `classification`: action_required / informational_archive / irrelevant  
- `priority`: P0–P3  
- `due_by`
- `required_actions`
- `topic`
- `summary`
- `key_entities`
- `evidence_snippets`
- `confidence`

Output: `triage_results.jsonl`

---

## 2️⃣ Daily Workload Digest

Generates a single-view summary of:

- High-priority actionable items
- Upcoming deadlines
- Informational threads
- Irrelevant items

Output: `digest.txt`

---

## 3️⃣ Actions Log (Audit Trail)

Produces a deterministic log describing what the system decided for each thread.

Output: `actions_log.jsonl`

Example:

```json
{
  "thread_id": "thr_hom_533661_ab10_17",
  "system_action": "queue_for_handler",
  "classification": "action_required",
  "priority": "P1",
  "due_by": null,
  "reason": "action_required P1",
  "timestamp_utc": "2026-03-03T12:15:00Z"
}
```

This satisfies the requirement to output the actions taken per email.

---

## 4️⃣ Free-Text Q&A (Router + RAG)

Handlers can ask:

- “Show me P0 threads”
- “Was there any action required for Bridgegate Brokers?”
- “What should I focus on today?”
- “Are there recurring broker escalations?”

The system:

1. Uses an LLM router to determine intent
2. Executes structured queries where possible
3. Falls back to Retrieval-Augmented Generation (RAG) for summaries/trend analysis

---

## 5️⃣ Evaluation Framework

Includes evaluation tools for:

- Classification accuracy
- Priority accuracy
- Confusion matrices
- Optional PII detection check

---

# Installation

## Requirements

- Python 3.11+
- See `requirements.txt`
- OpenAI API key (unless using `--dry-run`)

---

## Setup

From the project root:

```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Set environment variables:

```bash
export OPENAI_API_KEY=your_api_key_here
export OPENAI_MODEL=gpt-4o-mini
```

Windows PowerShell:

```powershell
setx OPENAI_API_KEY "your_api_key_here"
```

You may also pass `--api-key` and `--model` via CLI arguments.

---

# Usage

CLI entry point:

```bash
python -m app.main --help
```

---

## 1️⃣ Triage Emails

```bash
python -m app.main triage --in emails.json --out out/triage_results.jsonl
```

Options:

- `--model`
- `--dry-run`
- `--no-redact`
- `--max-threads`
- `--api-key`
- `--overwrite`

---

## 2️⃣ Generate Daily Digest + Actions Log

```bash
python -m app.main digest --in out/triage_results.jsonl --outdir out/
```

Outputs:

- `out/digest.txt`
- `out/actions_log.jsonl`

---

## 3️⃣ Ask Questions

```bash
python -m app.main ask --data out/triage_results.jsonl "What should I do first today?"
```

Optional:

- `--top-k`
- `--model`
- `--api-key`

---

# Project Structure

```
app/
  cli/
  domain/
  infra/
  utils/

prompts/
eval/
out/
emails.json
```

---

# Privacy & Data Protection

## PII Redaction

Optional redaction (`--redact`) replaces:

- Email addresses → `<EMAIL_1>`
- Phone numbers → `<PHONE_1>`
- Postcodes → `<POSTCODE_1>`

Operational identifiers (e.g., claim references) are not redacted.

## PII Check in Evaluation

```bash
python -m eval.run_eval \
  --predictions out/triage_results.jsonl \
  --labels eval/labels.jsonl \
  --pii-check
```

---

# Architecture Overview

The system separates concerns into:

- Domain logic – triage rules, digest generation
- Infrastructure – LLM client, redaction, structured query engine
- CLI layer – command orchestration

This enables:

- Replaceable LLM provider
- Deterministic filtering
- Clear audit trail
- Controlled use of RAG

---

# Limitations

- Requires LLM API for full functionality
- Keyword-based retrieval (no vector embeddings)
- Sequential thread processing
- No real mailbox integration (JSON input only)
- Optimised for English email content

---

# Future Improvements

- Vector-based retrieval
- Parallel triage processing
- Multi-provider LLM support
- Secure hosted deployment
- Enhanced name-level PII detection (NER-based)

---

# License

[Add license here]