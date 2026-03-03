"""Ask command handler."""

import logging
import sys

from app.domain.ask import ask_command

logger = logging.getLogger(__name__)


def ask_cmd(args) -> None:
    """Handle ask subcommand."""
    logger.info("Starting ask command")
    
    try:
        ask_command(
            triage_results_path=args.data,
            question=args.question,
            top_k=args.top_k
        )
    except FileNotFoundError as e:
        logger.error(f"File not found: {e}")
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        logger.error(f"Error during ask: {e}", exc_info=True)
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
