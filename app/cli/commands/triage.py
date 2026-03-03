"""Triage command handler."""

import json
import logging
import sys
from pathlib import Path

from app.domain.loader import load_emails
from app.domain.triage import triage_emails
from app.domain.models import write_jsonl, read_jsonl

logger = logging.getLogger(__name__)


def triage_cmd(args) -> None:
    """Handle triage subcommand."""
    logger.info("Starting triage command")

    # Load emails
    email_data = load_emails(args.in_file)
    logger.info(f"Loaded {len(email_data.emails)} email threads")

    output_path = Path(args.out_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Default behaviour: skip already triaged threads
    done_ids: set[str] = set()

    if output_path.exists() and not args.overwrite:
        existing_results = read_jsonl(output_path)
        done_ids = {r.thread_id for r in existing_results}

        original_count = len(email_data.emails)

        email_data.emails = [
            t for t in email_data.emails
            if t.messages and t.messages[0].thread_id not in done_ids
        ]

        skipped = original_count - len(email_data.emails)
        logger.info(f"Skipping {skipped} already-triaged threads")

    if not email_data.emails:
        print("No new threads to triage.")
        return

    # Run triage only on remaining threads
    results = triage_emails(
        email_data=email_data,
        redact=not args.no_redact,
        max_threads=args.max_threads
    )

    if not results:
        print("Error: No triage results generated", file=sys.stderr)
        sys.exit(1)

    # Write results
    if args.overwrite or not output_path.exists():
        write_jsonl(output_path, results)
    else:
        # append mode
        with output_path.open("a", encoding="utf-8") as f:
            for r in results:
                f.write(r.model_dump_json() + "\n")

    print(f"Triaged {len(results)} new threads. Results saved to {output_path}")
