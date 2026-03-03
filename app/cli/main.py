"""Main CLI entry point."""

import argparse
import logging
import sys
from pathlib import Path
from typing import Any

from app.domain.loader import load_emails
from app.domain.triage import triage_emails
from app.domain.digest import generate_digest
from app.domain.ask import ask_command
from app.domain.models import write_jsonl, read_jsonl
import json


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

logger = logging.getLogger(__name__)


def setup_logging(verbose: bool = False, quiet: bool = False):
    """Configure logging level."""
    if quiet:
        level = logging.WARNING
    elif verbose:
        level = logging.DEBUG
    else:
        level = logging.INFO
    
    logging.getLogger().setLevel(level)

def append_jsonl(path: Path, items: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(item.model_dump(), ensure_ascii=False) + "\n")




def triage_cmd(args: argparse.Namespace) -> None:
    logger.info("Starting triage command")

    # Load emails
    email_data = load_emails(args.in_file)
    logger.info(f"Loaded {len(email_data.emails)} email threads")

    output_path = Path(args.out_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Default behaviour: skip already triaged threads
    done_ids: set[str] = set()

    if output_path.exists() and not args.overwrite and not args.dry_run:
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
        model=args.model,
        api_key=args.api_key,
        redact=not args.no_redact,
        max_threads=args.max_threads,
        dry_run=args.dry_run
    )

    if not results:
        print("Error: No triage results generated", file=sys.stderr)
        sys.exit(1)

    # Write results
    if args.overwrite or not output_path.exists() or args.dry_run:
        write_jsonl(output_path, results)
    else:
        # append mode
        with output_path.open("a", encoding="utf-8") as f:
            for r in results:
                f.write(r.model_dump_json() + "\n")

    print(f"Triaged {len(results)} new threads. Results saved to {output_path}")


def digest_cmd(args: argparse.Namespace) -> None:
    """Handle digest subcommand."""
    logger.info("Starting digest command")
    try:
        from app.domain.models import read_jsonl
        from app.domain.actions_log import build_actions_log

        # Load triage results
        triage_results = read_jsonl(args.in_file)
        
        if not triage_results:
            logger.error(f"No triage results found in {args.in_file}")
            print(f"Error: No triage results found in {args.in_file}", file=sys.stderr)
            sys.exit(1)
        
        logger.info(f"Loaded {len(triage_results)} triage results")
        
        # Generate digest
        digest_text = generate_digest(
            triage_results=triage_results,
            model=args.model,
            api_key=args.api_key
        )
        
        # Save digest
        outdir = Path(args.outdir)
        outdir.mkdir(parents=True, exist_ok=True)
        
        output_path = outdir / "digest.md"
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(digest_text)
        
        # NEW: Save actions log
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
        logger.error(f"Error during digest generation: {e}", exc_info=args.verbose)
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def ask_cmd(args: argparse.Namespace) -> None:
    """Handle ask subcommand."""
    logger.info("Starting ask command")
    
    try:
        ask_command(
            triage_results_path=args.data,
            question=args.question,
            model=args.model,
            top_k=args.top_k,
            api_key=args.api_key,
        )
    except FileNotFoundError as e:
        logger.error(f"File not found: {e}")
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        logger.error(f"Error during ask: {e}", exc_info=args.verbose)
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Email Processing CLI - Triage, digest, and query emails",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Triage emails
  python -m app.main triage --in emails.json --out out/triage_results.jsonl --model gpt-4o-mini --max-threads 10

  # Generate digest
  python -m app.main digest --in out/triage_results.jsonl --outdir out/

  # Ask a question
  python -m app.main ask --data out/triage_results.jsonl "What are the P0 priority threads?" --model gpt-4o-mini --top-k 8
        """
    )
    
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Enable verbose logging (DEBUG level)'
    )
    
    parser.add_argument(
        '-q', '--quiet',
        action='store_true',
        help='Reduce logging output (WARNING level)'
    )
    
    parser.add_argument(
        '--api-key',
        type=str,
        help='LLM API key (or set via environment variable OPENAI_API_KEY)'
    )
    
   
    
    # Subcommands
    subparsers = parser.add_subparsers(dest='command', help='Available commands', required=True)
    
    # Triage subcommand
    triage_parser = subparsers.add_parser(
        'triage',
        help='Triage and categorize emails',
        description='Load emails from JSON and generate triage results in JSONL format.'
    )
    triage_parser.add_argument(
        '--in',
        dest='in_file',
        type=str,
        required=True,
        help='Input emails.json file path'
    )
    triage_parser.add_argument(
        '--out',
        dest='out_file',
        type=str,
        required=True,
        help='Output triage_results.jsonl file path'
    )
    triage_parser.add_argument(
        '--model',
        type=str,
        help='LLM model name (e.g., gpt-4o-mini). Defaults to OPENAI_MODEL env var or gpt-4o-mini'
    )
    triage_parser.add_argument(
        '--max-threads',
        type=int,
        help='Maximum number of threads to process (default: process all)'
    )
    triage_parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Skip LLM calls and generate placeholder results for 2 threads (useful for testing without API key)'
    )
    triage_parser.add_argument(
        '--overwrite',
        action='store_true',
        help='Overwrite output file and re-triage all threads (default: skip threads already in output)'
    )
    triage_parser.add_argument(
        "--no-redact",
        action="store_true",
        help="Disable redaction before sending data to the LLM (NOT recommended)"
    )
    triage_parser.set_defaults(func=triage_cmd)
    
    # Digest subcommand
    digest_parser = subparsers.add_parser(
        'digest',
        help='Generate email digest summary',
        description='Generate a summary digest from triage results JSONL file.'
    )
    digest_parser.add_argument(
        '--in',
        dest='in_file',
        type=str,
        required=True,
        help='Input triage_results.jsonl file path'
    )
    digest_parser.add_argument(
        '--outdir',
        type=str,
        required=True,
        help='Output directory (digest will be saved as digest.txt)'
    )
    digest_parser.add_argument(
        '--model',
        type=str,
        help='LLM model name (e.g., gpt-4o-mini). Defaults to OPENAI_MODEL env var or gpt-4o-mini'
    )
    digest_parser.set_defaults(func=digest_cmd)
    
    # Ask subcommand
    ask_parser = subparsers.add_parser(
        'ask',
        help='Ask a question about triage results',
        description='Answer questions about triage results using RAG or structured queries.'
    )
    ask_parser.add_argument(
        '--data',
        type=str,
        required=True,
        help='Path to triage_results.jsonl file'
    )
    ask_parser.add_argument(
        'question',
        type=str,
        help='Question to answer about the triage results'
    )
    ask_parser.add_argument(
        '--model',
        type=str,
        help='LLM model name (e.g., gpt-4o-mini). Defaults to OPENAI_MODEL env var or gpt-4o-mini'
    )
    ask_parser.add_argument(
        '--top-k',
        type=int,
        default=5,
        help='Number of candidates for RAG retrieval (default: 5)'
    )
    ask_parser.set_defaults(func=ask_cmd)
    
    args = parser.parse_args()
    
    # Setup logging
    setup_logging(verbose=args.verbose, quiet=args.quiet)
    
    # Execute command
    try:
        args.func(args)
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        print("\nInterrupted by user", file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=args.verbose)
        print(f"Unexpected error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
