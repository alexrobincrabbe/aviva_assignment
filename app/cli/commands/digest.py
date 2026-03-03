"""Digest command handler."""

import json
import logging
import sys
from pathlib import Path

from app.domain.models import read_jsonl
from app.domain.digest import generate_digest
from app.domain.actions_log import build_actions_log

logger = logging.getLogger(__name__)


def digest_cmd(args) -> None:
    """Handle digest subcommand."""
    logger.info("Starting digest command")
    try:
        # Load triage results
        triage_results = read_jsonl(args.in_file)
        
        if not triage_results:
            logger.error(f"No triage results found in {args.in_file}")
            print(f"Error: No triage results found in {args.in_file}", file=sys.stderr)
            sys.exit(1)
        
        logger.info(f"Loaded {len(triage_results)} triage results")
        
        # Generate digest
        digest_text = generate_digest(
            triage_results=triage_results
        )
        
        # Save digest
        outdir = Path(args.outdir)
        outdir.mkdir(parents=True, exist_ok=True)
        
        output_path = outdir / "digest.md"
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(digest_text)
        
        # Save actions log
        actions_log_path = outdir / "actions_log.jsonl"
        actions_log_records = build_actions_log(triage_results)
        # Write dictionaries directly (not Pydantic models)
        actions_log_path.parent.mkdir(parents=True, exist_ok=True)
        with actions_log_path.open("w", encoding="utf-8") as f:
            for record in actions_log_records:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

        logger.info(f"Digest saved to {output_path}")
        logger.info(f"Actions log saved to {actions_log_path}")

        print(f"Digest generated. Saved to {output_path}")
        print(f"Actions log generated. Saved to {actions_log_path}")
        
    except FileNotFoundError as e:
        logger.error(f"File not found: {e}")
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        logger.error(f"Error during digest generation: {e}", exc_info=True)
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
