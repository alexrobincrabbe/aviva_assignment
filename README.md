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

Output: `digest.md`

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

### Running Evaluation

Evaluate triage predictions against gold labels:

```bash
python -m eval.run_eval --predictions out/triage_results.jsonl --labels eval/labels.jsonl
```

The evaluation script compares predicted classifications and priorities against gold labels and outputs:

- Overall accuracy metrics
- Classification confusion matrix
- Priority confusion matrix

**Options:**

- `--predictions`: Path to predicted `triage_results.jsonl` file (required)
- `--labels`: Path to gold `labels.jsonl` file (required)
- `--pii-check`: Check for PII (emails, phone numbers) in predicted outputs

**Example:**

```bash
python -m eval.run_eval --predictions out/triage_results.jsonl --labels eval/labels.jsonl
```

---

# Installation

## Requirements

- Python 3.11+
- See `requirements.txt`
- OpenAI API key

---

## Setup

From the project root:

```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### Configuration

Create a `.env` file in the project root:

```bash
OPENAI_API_KEY=your_api_key_here
OPENAI_MODEL=gpt-4o-mini
```

**Note:** The `.env` file is automatically loaded when the application starts. The API key is required for all LLM operations. If `OPENAI_MODEL` is not set, it defaults to `gpt-4o-mini`.

### Logging Configuration

Create a `config.json` file in the project root (optional, defaults to INFO):

```json
{
  "logging": {
    "level": "INFO"
  }
}
```

Supported logging levels: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`

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

- `--max-threads`: Maximum number of threads to process (default: process all)
- `--no-redact`: Disable redaction before sending data to the LLM (NOT recommended)
- `--overwrite`: Overwrite output file and re-triage all threads (default: skip threads already in output)

By default, the command skips threads that have already been triaged (if the output file exists). Use `--overwrite` to re-triage all threads.

---

## 2️⃣ Generate Daily Digest + Actions Log

```bash
python -m app.main digest --in out/triage_results.jsonl --outdir out/
```

Outputs:

- `out/digest.md` - Markdown-formatted daily digest
- `out/actions_log.jsonl` - Audit trail of system decisions

---

## 3️⃣ Ask Questions

```bash
python -m app.main ask --data out/triage_results.jsonl "What should I do first today?"
```

Optional:

- `--top-k`: Number of candidates for RAG retrieval (default: 5)

---

# Project Structure

```
app/
  __init__.py
  main.py                    # Shim for backward compatibility
  utils.py                   # Path resolution utilities
  cli/
    __init__.py
    main.py                  # CLI entry point (argparse)
    commands/
      __init__.py
      triage.py              # Triage command handler
      digest.py              # Digest command handler
      ask.py                 # Ask command handler
      utils.py               # CLI utilities (logging setup)
  domain/
    __init__.py
    models.py                # Pydantic models and JSONL helpers
    loader.py                # Email data loading
    triage.py                # Triage logic
    digest.py                # Digest generation
    ask.py                   # Ask/RAG logic
    actions_log.py           # Actions log generation
  infra/
    __init__.py
    llm.py                   # LLM client (OpenAI)
    redact.py                # PII redaction
    query_engine.py          # Structured query engine

prompts/                     # LLM prompt templates
eval/                        # Evaluation scripts
out/                         # Output directory
config.json                  # Logging configuration
.env                         # Environment variables (API keys)
emails.json                  # Input email data
README.md
requirements.txt
```

---

# Privacy & Data Protection

## PII Redaction

Redaction is enabled by default. Use `--no-redact` to disable it.

When enabled, redaction replaces:

- Email addresses → `<EMAIL_1>`
- Phone numbers → `<PHONE_1>`
- Postcodes → `<POSTCODE_1>`

Operational identifiers (e.g., claim references) are not redacted.

## PII Check in Evaluation

The evaluation script can optionally check for PII (emails, phone numbers) in predicted outputs. If PII is detected, the evaluation will fail with details about where it was found. This helps ensure that redaction is working correctly.

```bash
python -m eval.run_eval --predictions out/triage_results.jsonl --labels eval/labels.jsonl --pii-check
```

---

# Architecture Overview

The system uses a modular architecture separating concerns:

- **CLI Layer** (`app/cli/`) – Command-line interface and argument parsing
  - `main.py` – Entry point with argparse setup
  - `commands/` – Individual command handlers (triage, digest, ask)
  
- **Domain Logic** (`app/domain/`) – Business logic and data models
  - `models.py` – Pydantic models and JSONL I/O
  - `triage.py` – Email triage classification logic
  - `digest.py` – Daily digest generation
  - `ask.py` – Query routing and RAG implementation
  - `loader.py` – Email data loading and parsing
  - `actions_log.py` – Audit trail generation

- **Infrastructure** (`app/infra/`) – External services and utilities
  - `llm.py` – OpenAI LLM client wrapper
  - `redact.py` – PII redaction utilities
  - `query_engine.py` – Deterministic structured query execution

- **Utilities** (`app/utils.py`) – Path resolution and common helpers

This architecture enables:

- Replaceable LLM provider (via `infra/llm.py`)
- Deterministic filtering (via `infra/query_engine.py`)
- Clear audit trail (via `domain/actions_log.py`)
- Controlled use of RAG (via `domain/ask.py`)
- Configuration via `.env` and `config.json` files

---

# Limitations

- Keyword-based retrieval (no vector embeddings)
- Sequential thread processing
- No real mailbox integration (JSON input only)

---

# Future Improvements

- Vector-based retrieval (possibly?)
- Parallel triage processing
- Enhanced name-level PII detection (NER-based)

---
