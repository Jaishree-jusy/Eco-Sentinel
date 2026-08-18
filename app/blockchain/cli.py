"""
CLI for Module 9 - Blockchain Integrity Layer.

Usage (from the eco-sentinel/ project root):

    python -m app.blockchain.cli record     # hash evidence + add blocks to the ledger
    python -m app.blockchain.cli verify       # check the entire chain + re-hash evidence files on disk
"""

import sys
import argparse
from app.blockchain.pipeline import run_blockchain_recording, run_blockchain_verification, BlockchainError


def main():
    parser = argparse.ArgumentParser(description="ECO-SENTINEL Module 9 CLI")
    parser.add_argument("command", choices=["record", "verify"])
    args = parser.parse_args()

    try:
        if args.command == "record":
            print("Running Module 9 - Blockchain Recording...")
            manifest = run_blockchain_recording()

            print("\nBlockchain Recording SUCCESS")
            print(f"  run_id:                    {manifest['run_id']}")
            print(f"  blocks recorded this run:  {manifest['blocks_recorded_this_run']}")
            print(f"  skipped (already recorded): {manifest['skipped_already_recorded']}")
            print(f"  total chain length:        {manifest['chain_length']}")
            print(f"  ledger:                    {manifest['ledger_path']}")
            print(f"  manifest:                  {manifest['manifest_path']}\n")
            preview = manifest["records"][:5]
            for r in preview:
                print(f"    {r['alert_id']}  ->  tx {r['transaction_hash'][:16]}...")
            if len(manifest["records"]) > 5:
                print(f"    ...and {len(manifest['records']) - 5} more (see manifest file for full list)")

        elif args.command == "verify":
            print("Running Module 9 - Blockchain Verification...")
            result = run_blockchain_verification()

            print("\nBlockchain Verification RESULT")
            print(f"  chain length: {result['chain_length']}")
            print(f"  valid:        {result['valid']}")
            if not result["valid"]:
                print("  ISSUES FOUND:")
                for issue in result["issues"][:10]:
                    print(f"    - block {issue['block_index']} ({issue['alert_id']}): {issue['issue']}")
                if len(result["issues"]) > 10:
                    print(f"    ...and {len(result['issues']) - 10} more issues")
            else:
                print("  No tampering detected. All blocks verified against evidence files on disk.\n")

    except BlockchainError as e:
        print(f"\nBlockchain operation FAILED: {e}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
