"""Evaluation script for comparing predicted vs gold labels."""

import argparse
import json
import logging
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List

# Add parent directory to path to allow imports when run directly
if __name__ == '__main__':
    script_dir = Path(__file__).parent
    parent_dir = script_dir.parent
    if str(parent_dir) not in sys.path:
        sys.path.insert(0, str(parent_dir))

# Import patterns from redact module
try:
    from app.infra.redact import EMAIL_PATTERN, PHONE_PATTERNS
except ImportError:
    # Fallback patterns if import fails
    EMAIL_PATTERN = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
    PHONE_PATTERNS = [
        r'\b07\d{3}\s\d{6}\b',
        r'\b07\d{9}\b',
        r'\b0\d{2,3}\s\d{3,4}\s\d{3,4}\b',
        r'\b0\d{9,10}\b',
        r'(?<!\d)\+44\s+\d{2}\s+\d{4}\s+\d{4}(?!\d)',
        r'(?<!\d)\+44\s+\d{4}\s+\d{6}(?!\d)',
        r'(?<!\d)\+44\d{9,10}(?!\d)',
    ]

from app.domain.models import ThreadTriageResult, read_jsonl

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


def load_gold_labels(labels_path: Path) -> Dict[str, Dict[str, str]]:
    """
    Load gold labels from JSONL file.
    
    Expected format: Each line is a JSON object with:
    - thread_id: str
    - classification: str (action_required|informational_archive|irrelevant)
    - priority: str (P0|P1|P2|P3)
    
    Args:
        labels_path: Path to labels.jsonl file
        
    Returns:
        Dictionary mapping thread_id to gold label dict
    """
    gold_labels = {}
    
    if not labels_path.exists():
        raise FileNotFoundError(f"Labels file not found: {labels_path}")
    
    logger.info(f"Loading gold labels from {labels_path}")
    
    with open(labels_path, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            
            try:
                label = json.loads(line)
                thread_id = label.get('thread_id', '').strip()
                
                # Skip empty/template entries
                if not thread_id:
                    continue
                
                classification = label.get('classification', '').strip()
                priority = label.get('priority', '').strip()
                
                if not classification or not priority:
                    logger.warning(f"Line {line_num}: Missing classification or priority for thread {thread_id}")
                    continue
                
                # Validate values
                valid_classifications = {'action_required', 'informational_archive', 'irrelevant'}
                valid_priorities = {'P0', 'P1', 'P2', 'P3'}
                
                if classification not in valid_classifications:
                    logger.warning(f"Line {line_num}: Invalid classification '{classification}' for thread {thread_id}")
                    continue
                
                if priority not in valid_priorities:
                    logger.warning(f"Line {line_num}: Invalid priority '{priority}' for thread {thread_id}")
                    continue
                
                gold_labels[thread_id] = {
                    'classification': classification,
                    'priority': priority
                }
                
            except json.JSONDecodeError as e:
                logger.warning(f"Line {line_num}: Invalid JSON: {e}")
                continue
    
    logger.info(f"Loaded {len(gold_labels)} gold labels")
    return gold_labels


def load_predictions(predictions_path: Path) -> Dict[str, ThreadTriageResult]:
    """
    Load predicted triage results from JSONL file.
    
    Args:
        predictions_path: Path to triage_results.jsonl file
        
    Returns:
        Dictionary mapping thread_id to ThreadTriageResult
    """
    if not predictions_path.exists():
        raise FileNotFoundError(f"Predictions file not found: {predictions_path}")
    
    logger.info(f"Loading predictions from {predictions_path}")
    
    results = read_jsonl(predictions_path)
    predictions = {r.thread_id: r for r in results}
    
    logger.info(f"Loaded {len(predictions)} predictions")
    return predictions


def calculate_accuracy(predicted: List[str], gold: List[str]) -> float:
    """Calculate accuracy given lists of predicted and gold labels."""
    if len(predicted) != len(gold):
        raise ValueError("Predicted and gold lists must have same length")
    
    if not predicted:
        return 0.0
    
    correct = sum(1 for p, g in zip(predicted, gold) if p == g)
    return correct / len(predicted)


def build_confusion_matrix(predicted: List[str], gold: List[str], labels: List[str]) -> Dict[str, Dict[str, int]]:
    """
    Build confusion matrix.
    
    Args:
        predicted: List of predicted labels
        gold: List of gold labels
        labels: List of all possible labels (ordered)
        
    Returns:
        Dictionary mapping (predicted_label, gold_label) to count
    """
    matrix = defaultdict(lambda: defaultdict(int))
    
    for p, g in zip(predicted, gold):
        matrix[p][g] += 1
    
    return matrix


def print_confusion_matrix(matrix: Dict[str, Dict[str, int]], labels: List[str], title: str):
    """
    Print confusion matrix as a formatted table.
    
    Args:
        matrix: Confusion matrix dictionary
        labels: List of labels (ordered)
        title: Title for the matrix
    """
    print(f"\n{title}")
    print("=" * (len(title) + 2))
    
    # Calculate column widths
    label_width = max(len(l) for l in labels) + 2
    num_width = 6
    
    # Header row
    header = f"{'':<{label_width}}"
    for label in labels:
        header += f"{label:>{num_width}}"
    header += f"{'Total':>{num_width}}"
    print(header)
    print("-" * len(header))
    
    # Data rows
    for pred_label in labels:
        row = f"{pred_label:<{label_width}}"
        row_total = 0
        for gold_label in labels:
            count = matrix[pred_label][gold_label]
            row += f"{count:>{num_width}}"
            row_total += count
        row += f"{row_total:>{num_width}}"
        print(row)
    
    # Column totals
    print("-" * len(header))
    col_totals = [0] * len(labels)
    for pred_label in labels:
        for i, gold_label in enumerate(labels):
            col_totals[i] += matrix[pred_label][gold_label]
    
    footer = f"{'Total':<{label_width}}"
    for total in col_totals:
        footer += f"{total:>{num_width}}"
    footer += f"{sum(col_totals):>{num_width}}"
    print(footer)
    print()


def check_pii_in_outputs(predictions: Dict[str, ThreadTriageResult]) -> List[Dict[str, str]]:
    """
    Check for PII (emails, phone numbers) in predicted outputs.
    
    Args:
        predictions: Dictionary of ThreadTriageResult objects
        
    Returns:
        List of dicts with thread_id and detected PII info
    """
    issues = []
    
    for thread_id, result in predictions.items():
        # Check all text fields
        text_fields = [
            ('topic', result.topic),
            ('summary', result.summary),
            ('required_actions', ' '.join(result.required_actions)),
            ('evidence_snippets', ' '.join(result.evidence_snippets)),
        ]
        
        # Check key_entities (convert to string)
        if result.key_entities:
            text_fields.append(('key_entities', json.dumps(result.key_entities)))
        
        for field_name, text in text_fields:
            if not text:
                continue
            
            # Check for emails
            email_matches = re.findall(EMAIL_PATTERN, text)
            if email_matches:
                issues.append({
                    'thread_id': thread_id,
                    'field': field_name,
                    'type': 'email',
                    'matches': email_matches[:3]  # Show first 3
                })
            
            # Check for phone numbers
            phone_matches = []
            for pattern in PHONE_PATTERNS:
                phone_matches.extend(re.findall(pattern, text, re.IGNORECASE))
            if phone_matches:
                issues.append({
                    'thread_id': thread_id,
                    'field': field_name,
                    'type': 'phone',
                    'matches': phone_matches[:3]  # Show first 3
                })
    
    return issues


def main():
    """Main evaluation function."""
    parser = argparse.ArgumentParser(
        description='Evaluate triage predictions against gold labels',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic evaluation
  python eval/run_eval.py --predictions out/triage_results.jsonl --labels eval/labels.jsonl
  
  # With PII check
  python eval/run_eval.py --predictions out/triage_results.jsonl --labels eval/labels.jsonl --pii-check
        """
    )
    
    parser.add_argument(
        '--predictions',
        type=str,
        required=True,
        help='Path to predicted triage_results.jsonl file'
    )
    
    parser.add_argument(
        '--labels',
        type=str,
        required=True,
        help='Path to gold labels.jsonl file'
    )
    
    parser.add_argument(
        '--pii-check',
        action='store_true',
        help='Check for PII (emails, phone numbers) in predicted outputs'
    )
    
    args = parser.parse_args()
    
    try:
        # Load data
        predictions = load_predictions(Path(args.predictions))
        gold_labels = load_gold_labels(Path(args.labels))
        
        # Find common thread_ids
        common_threads = set(predictions.keys()) & set(gold_labels.keys())
        
        if not common_threads:
            logger.error("No common thread_ids found between predictions and gold labels")
            print("Error: No matching thread_ids found. Check that thread_ids match.", file=sys.stderr)
            sys.exit(1)
        
        logger.info(f"Evaluating {len(common_threads)} threads")
        
        # Extract labels for comparison
        predicted_classifications = []
        gold_classifications = []
        predicted_priorities = []
        gold_priorities = []
        
        for thread_id in sorted(common_threads):
            pred = predictions[thread_id]
            gold = gold_labels[thread_id]
            
            predicted_classifications.append(pred.classification)
            gold_classifications.append(gold['classification'])
            predicted_priorities.append(pred.priority)
            gold_priorities.append(gold['priority'])
        
        # Calculate accuracies
        classification_accuracy = calculate_accuracy(predicted_classifications, gold_classifications)
        priority_accuracy = calculate_accuracy(predicted_priorities, gold_priorities)
        
        # Print results
        print("\n" + "=" * 60)
        print("EVALUATION RESULTS")
        print("=" * 60)
        print(f"\nTotal threads evaluated: {len(common_threads)}")
        print(f"\nClassification Accuracy: {classification_accuracy:.2%}")
        print(f"Priority Accuracy: {priority_accuracy:.2%}")
        
        # Classification confusion matrix
        classification_labels = ['action_required', 'informational_archive', 'irrelevant']
        class_matrix = build_confusion_matrix(
            predicted_classifications,
            gold_classifications,
            classification_labels
        )
        print_confusion_matrix(class_matrix, classification_labels, "Classification Confusion Matrix")
        
        # Priority confusion matrix
        priority_labels = ['P0', 'P1', 'P2', 'P3']
        priority_matrix = build_confusion_matrix(
            predicted_priorities,
            gold_priorities,
            priority_labels
        )
        print_confusion_matrix(priority_matrix, priority_labels, "Priority Confusion Matrix")
        
        # PII check
        if args.pii_check:
            print("\n" + "=" * 60)
            print("PII CHECK")
            print("=" * 60)
            
            pii_issues = check_pii_in_outputs(predictions)
            
            if pii_issues:
                print(f"\n⚠️  Found {len(pii_issues)} PII detection(s) in predicted outputs:\n")
                for issue in pii_issues:
                    print(f"  Thread: {issue['thread_id']}")
                    print(f"  Field: {issue['field']}")
                    print(f"  Type: {issue['type']}")
                    print(f"  Matches: {issue['matches']}")
                    print()
                sys.exit(1)
            else:
                print("\n✓ No PII detected in predicted outputs")
        
        print("\n" + "=" * 60)
        
    except FileNotFoundError as e:
        logger.error(f"File not found: {e}")
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        logger.error(f"Error during evaluation: {e}", exc_info=True)
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
