"""Main CLI entry point."""

import argparse
import logging
import sys

from app.cli.commands import triage_cmd, digest_cmd, ask_cmd, setup_logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

logger = logging.getLogger(__name__)


def main() -> None:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Email Processing CLI - Triage, digest, and query emails",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Triage emails
  python -m app.main triage --in emails.json --out out/triage_results.jsonl --max-threads 10

  # Generate digest
  python -m app.main digest --in out/triage_results.jsonl --outdir out/

  # Ask a question
  python -m app.main ask --data out/triage_results.jsonl "What are the P0 priority threads?" --top-k 8
        """
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
        '--max-threads',
        type=int,
        help='Maximum number of threads to process (default: process all)'
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
        help='Output directory (digest will be saved as digest.md)'
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
        '--top-k',
        type=int,
        default=5,
        help='Number of candidates for RAG retrieval (default: 5)'
    )
    ask_parser.set_defaults(func=ask_cmd)
    
    args = parser.parse_args()
    
    # Setup logging from config file
    setup_logging()
    
    # Execute command
    try:
        args.func(args)
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        print("\nInterrupted by user", file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        print(f"Unexpected error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
