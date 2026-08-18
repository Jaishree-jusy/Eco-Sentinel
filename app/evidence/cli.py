"""
CLI for Module 8 - Evidence Generation.

Usage (from the eco-sentinel/ project root):

    python -m app.evidence.cli generate                 # process ALL inside-forest alerts
    python -m app.evidence.cli generate --limit 5        # process only the first 5 (recommended for a first test run)

If you have a large number of inside-forest alerts, start with --limit 5
to confirm everything works before running the full set - each alert
generates a PDF + PNG + GeoJSON + JSON, so a large run can take a while.
"""

import sys
import argparse
from app.evidence.pipeline import run_evidence_generation, EvidenceGenerationError


def main():
    parser = argparse.ArgumentParser(description="ECO-SENTINEL Module 8 CLI")
    parser.add_argument("command", choices=["generate"])
    parser.add_argument("--limit", type=int, default=None, help="Only process the first N alerts (for testing)")
    args = parser.parse_args()

    try:
        print("Running Module 8 - Evidence Generation...")
        if args.limit:
            print(f"(limited to first {args.limit} alerts)")
        manifest = run_evidence_generation(limit=args.limit)

        print("\nEvidence Generation SUCCESS")
        print(f"  run_id:            {manifest['run_id']}")
        print(f"  alerts processed:  {manifest['total_alerts_processed']}")
        print(f"  successful:        {manifest['successful']}")
        print(f"  failed:            {manifest['failed']}")
        if manifest["failed"] > 0:
            print(f"  failures:          {manifest['failures']}")
        print(f"  manifest:          {manifest['manifest_path']}\n")

    except EvidenceGenerationError as e:
        print(f"\nEvidence Generation FAILED: {e}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
